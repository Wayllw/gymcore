# GymCore — Relatório Técnico: Fase 2 — Assincronismo, Event-Driven e Observabilidade

**Unidade Curricular:** Arquiteturas de Software  
**Fase:** 2 — Assincronismo, Desacoplamento e Observabilidade  
**Data:** 10 de maio de 2026  

---

## 1. Análise Comparativa: Por que a Fase 1 deixou de ser suficiente

### 1.1 O problema identificado

Na Fase 1, o endpoint `POST /socios/{id}/relatorio` executava um processo síncrono de ~2 segundos. O relatório técnico dessa fase antecipava explicitamente este problema:

> "Bloqueia o thread HTTP durante 2s (afeta RNF-3: latência). Uma falha no processo degrada a API inteira."

Com o crescimento do sistema (RNF-4: escalabilidade), este padrão torna-se inaceitável:

| Cenário | Fase 1 | Impacto |
|---------|--------|---------|
| 10 pedidos simultâneos de relatório | 10 threads bloqueados × 2s | API indisponível para outros pedidos |
| Falha no serviço de relatórios | Exceção propagada ao utilizador | Sem retry, dados perdidos |
| Novo componente precisa reagir a inscrições | Modificar `InscreverSocioUseCase` | Viola Open/Closed Principle |
| Rastrear um pedido entre componentes | Impossível — sem correlationId | Depuração inviável |

### 1.2 RNF que motivam a evolução

| ID | Requisito | Fase 1 | Fase 2 |
|----|-----------|--------|--------|
| RNF-3 | Desempenho: API < 200ms | ❌ Relatório bloqueava 2000ms | ✅ < 10ms (async) |
| RNF-4 | Escalabilidade | ❌ Workers acoplados ao thread HTTP | ✅ Workers independentes e escaláveis |
| RNF-5 | Resiliência | ❌ Falha no processo afeta a API | ✅ Retry automático + dead-letter queue |
| RNF-6 | Observabilidade | ⚠️ Logging básico sem correlação | ✅ correlationId propagado em todos os componentes |
| RNF-2 | Manutenibilidade | ⚠️ Novos consumidores exigem modificação | ✅ Event-driven: novos consumidores sem tocar no Core |

---

## 2. Arquitetura da Fase 2

### 2.1 Visão Geral

```
┌─────────────────────────────────────────────────────────────────────┐
│                    HTTP CLIENT (com X-Correlation-ID)               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ pedido HTTP
┌──────────────────────────────▼──────────────────────────────────────┐
│              INBOUND ADAPTER: api.py (Flask)                        │
│   Middleware: injetar/propagar correlationId em cada pedido         │
│   POST /relatorio → resposta 202 + job_id em < 10ms                 │
└────────┬────────────────────────────────────┬────────────────────────┘
         │ use cases (inalterados)             │ publica eventos
         ▼                                     ▼
┌────────────────────┐              ┌──────────────────────────────────┐
│  CORE (inalterado) │              │         BUS DE EVENTOS           │
│  Domain + UseCases │              │  socio.inscrito                  │
│                    │              │  socio.suspenso                  │
│  IRelatorioService │              │  treino.plano_criado             │
│  (interface)       │              │  relatorio.solicitado            │
└────────┬───────────┘              │  relatorio.concluido             │
         │ injeta                   │  relatorio.falhou                │
         ▼                          └──────────┬───────────────────────┘
┌────────────────────┐                         │ subscritos
│ QueueRelatorioSvc  │              ┌───────────┼───────────────┐
│ (Fase 2: async)    │              ▼           ▼               ▼
│ publica na fila →  │   AuditoriaConsumer  EstatisticasC.  AlertaConsumer
│ retorna job_id     │   (regista tudo)     (contadores)    (alertas críticos)
└────────┬───────────┘
         │ publica mensagem
         ▼
┌────────────────────────────────────────────────────────────────────┐
│                    FILA DE MENSAGENS (em memória)                   │
│              FilaMensagens — FIFO + Dead Letter Queue               │
│     Retry automático com backoff exponencial (1s, 2s, 4s...)       │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │ consome em background thread
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                       RELATORIO WORKER                             │
│   Thread de background — consome fila continuamente                │
│   Processa relatório (~2s) sem bloquear thread HTTP                │
│   Em caso de falha: retry com backoff exponencial                  │
│   Publica eventos: RELATORIO_CONCLUIDO ou RELATORIO_FALHOU         │
│   correlationId propagado do pedido original até ao evento final   │
└────────────────────────────────────────────────────────────────────┘
```

### 2.2 Padrão Web-Queue-Worker

O padrão Web-Queue-Worker resolve o problema de processos pesados que bloqueavam a API:

```
FASE 1 (síncrono):
  HTTP POST /relatorio ─────────────────────────────────────── HTTP 200 (2s depois)
  Thread HTTP: [████████████████████████████████████ 2000ms ████]

FASE 2 (assíncrono):
  HTTP POST /relatorio ──── HTTP 202 + job_id (< 10ms)
  Thread HTTP: [█ 5ms]
  
  Worker (background): [.... aguarda ...] [████ 2000ms processamento ████] → evento concluído
```

**Componentes:**
- **Web** (`api.py`): recebe o pedido, publica na fila, responde imediatamente com `job_id`
- **Queue** (`FilaMensagens`): buffer desacoplado entre Web e Worker. Garante persistência temporária e retry
- **Worker** (`RelatorioWorker`): consome a fila em background thread, processa sem afetar a API

### 2.3 Event-Driven Architecture

O Bus de Eventos permite que múltiplos consumidores reajam de forma independente ao mesmo evento:

```
Evento: socio.inscrito
  ├── AuditoriaConsumer.on_socio_inscrito()  → registo de auditoria
  └── EstatisticasConsumer.on_socio_inscrito() → incrementar contador

Evento: relatorio.falhou
  ├── AuditoriaConsumer.on_relatorio_falhou() → registo de falha
  └── AlertaConsumer.on_relatorio_falhou()   → alerta crítico (após 3 falhas)

Evento: relatorio.concluido
  ├── AuditoriaConsumer.on_relatorio_concluido() → registo de conclusão
  └── EstatisticasConsumer.on_relatorio_concluido() → incrementar contador
```

**Vantagem chave:** para adicionar um novo comportamento (ex: enviar email quando relatório fica pronto), basta criar um novo consumidor e subscrever ao evento `relatorio.concluido`. **O Core não é modificado.**

---

## 3. Novos Componentes (DIP mantido)

### 3.1 O que mudou e o que ficou igual

| Componente | Fase 1 | Fase 2 | Core modificado? |
|------------|--------|--------|-----------------|
| `domain/` | ✅ | **Inalterado** | — |
| `application/use_cases/` | ✅ | **Inalterado** | — |
| `application/ports/` | ✅ | **Inalterado** | — |
| `SimuladoRelatorioService` | Implementação síncrona | Substituído | ❌ Core não sabe |
| `LogNotificacaoService` | Implementação simples | Substituído | ❌ Core não sabe |
| `container.py` | Liga Fase 1 | **Atualizado** | ❌ Apenas aqui |
| `FilaMensagens` | — | **Novo** | ❌ |
| `BusEventos` | — | **Novo** | ❌ |
| `RelatorioWorker` | — | **Novo** | ❌ |
| `Consumers` | — | **Novo** | ❌ |
| `QueueRelatorioService` | — | **Novo** (substitui `IRelatorioService`) | ❌ |
| `api.py` | Fase 1 | **Atualizado** (correlationId + novos endpoints) | ❌ |

**O Core (domain + application) não foi modificado em nenhuma linha.** Isto é o DIP em ação.

### 3.2 QueueRelatorioService — substituição transparente

```python
# FASE 1 — implementação síncrona (bloqueava 2s):
class SimuladoRelatorioService(IRelatorioService):
    def gerar_relatorio_socio(self, socio_id: UUID) -> str:
        time.sleep(2)               # bloqueia thread HTTP
        return f"relatorios/socio_{socio_id}.pdf"

# FASE 2 — implementação assíncrona (< 5ms):
class QueueRelatorioService(IRelatorioService):
    def gerar_relatorio_socio(self, socio_id: UUID, correlation_id=None) -> str:
        self._fila.publicar(Mensagem(...))  # publica e retorna imediatamente
        return job_id                        # retorna em < 5ms
```

O `GerarRelatorioSocioUseCase` não foi alterado — chama `IRelatorioService.gerar_relatorio_socio()` e não sabe se é síncrono ou assíncrono.

---

## 4. Observabilidade — correlationId

### 4.1 O que é e por que importa

O `correlationId` é um UUID único gerado (ou recebido do cliente via `X-Correlation-ID`) no início de cada pedido HTTP. Propaga-se por todos os componentes do sistema, permitindo rastrear um pedido completo mesmo quando o processamento é assíncrono.

### 4.2 Fluxo de propagação

```
1. HTTP POST /socios/abc/relatorio
   → Middleware gera correlationId: "cid-abc-123"
   → Injeta em Flask g.correlation_id

2. API publica na fila:
   Mensagem(correlation_id="cid-abc-123", ...)

3. Worker consome da fila:
   [WORKER] A processar | correlation_id=cid-abc-123

4. Worker publica evento:
   Evento(tipo=RELATORIO_CONCLUIDO, correlation_id="cid-abc-123")

5. Consumidores processam:
   [AUDITORIA] Relatório concluído | correlation_id=cid-abc-123
   [ESTATISTICAS] Relatórios: 1 | correlation_id=cid-abc-123

6. Resposta HTTP inclui header:
   X-Correlation-ID: cid-abc-123
```

Para rastrear um pedido completo nos logs: `grep "cid-abc-123" gymcore.log`

### 4.3 Logging estruturado enriquecido

Formato dos logs na Fase 2:
```
2026-05-10T14:22:01 | INFO     | api | cid=cid-abc-123 | Pedido de relatório recebido
2026-05-10T14:22:01 | INFO     | queue | cid=cid-abc-123 | Mensagem publicada
2026-05-10T14:22:01 | INFO     | worker | cid=cid-abc-123 | Mensagem recebida | tentativa=1
2026-05-10T14:22:03 | INFO     | worker | cid=cid-abc-123 | Relatório gerado com sucesso
2026-05-10T14:22:03 | INFO     | auditoria | cid=cid-abc-123 | Relatório concluído
```

---

## 5. Resiliência — Retry com Backoff Exponencial

### 5.1 Mecanismo implementado

Quando o Worker falha ao processar uma mensagem:
1. Regista o erro com o `correlationId` original
2. Aguarda `min(2^tentativa, 8)` segundos (backoff exponencial)
3. Re-enfileira a mensagem com `tentativas += 1`
4. Tenta novamente até `max_tentativas` (padrão: 3)
5. Após esgotar tentativas: mensagem vai para Dead Letter Queue

```python
# Backoff exponencial:
# Tentativa 1: aguarda 1s antes de retry
# Tentativa 2: aguarda 2s antes de retry
# Tentativa 3: aguarda 4s antes de retry (max 8s)
backoff = min(2 ** mensagem.tentativas, 8)
```

### 5.2 Demonstração de falha

Para demonstrar o mecanismo de retry e rastreio:

```bash
# Activar modo falha via variável de ambiente:
GYMCORE_SIMULAR_FALHA=true python infrastructure/adapters/inbound/api.py

# Ou via endpoint de admin (em runtime):
curl -X POST http://localhost:5000/admin/demo-falha

# Depois solicitar um relatório:
curl -X POST http://localhost:5000/socios/{id}/relatorio

# Nos logs verão:
# 💥 [WORKER] FALHA INJETADA #1 | correlation_id=XXX
# ❌ [WORKER] Falha ao processar | tentativa=1
# 🔄 [QUEUE] Retry 1/3 | correlation_id=XXX
# 💥 [WORKER] FALHA INJETADA #2 | correlation_id=XXX
# 🔄 [QUEUE] Retry 2/3 | correlation_id=XXX
# ✅ [WORKER] Relatório gerado | correlation_id=XXX  ← sucesso na 3ª tentativa
```

O mesmo `correlation_id` aparece em TODOS os logs — falhas e sucesso final.

---

## 6. Novos Endpoints

| Método | Endpoint | Descrição | Fase |
|--------|----------|-----------|------|
| POST | `/socios/{id}/relatorio` | Retorna `job_id` em < 10ms (antes: 2s) | Fase 2 |
| GET | `/relatorios/{job_id}/status` | Consultar estado do job | Fase 2 |
| GET | `/sistema/stats` | Observabilidade: fila, eventos, métricas | Fase 2 |
| GET | `/sistema/eventos` | Histórico do bus de eventos | Fase 2 |
| POST | `/admin/demo-falha` | Activar modo de falha (demo) | Fase 2 |

---

## 7. Estrutura do Repositório (novos ficheiros)

```
gymcore/
├── infrastructure/
│   ├── messaging/
│   │   └── queue.py              ← FilaMensagens (Web-Queue-Worker)
│   ├── events/
│   │   ├── event_bus.py          ← BusEventos + TipoEvento
│   │   └── consumers.py          ← AuditoriaConsumer, EstatisticasConsumer, AlertaConsumer
│   ├── workers/
│   │   └── relatorio_worker.py   ← RelatorioWorker (background thread)
│   └── adapters/outbound/
│       └── async_services.py     ← QueueRelatorioService, EventNotificacaoService
│
└── tests/fase2/
    └── test_fase2.py             ← Testes: fila, bus, worker, retry, correlationId
```

**Ficheiros da Fase 1 modificados:** `container.py`, `api.py`  
**Ficheiros do Core modificados:** Nenhum

---

## 8. Instruções de Execução

### Pré-requisitos
- Python 3.10+
- `pip install flask python-json-logger` (ou usar requirements.txt da Fase 1)

### Iniciar normalmente
```bash
cd gymcore-fase2
python infrastructure/adapters/inbound/api.py
# API em http://localhost:5000
# Docs em http://localhost:5000/docs
```

### Iniciar com modo de falha (demonstração)
```bash
GYMCORE_SIMULAR_FALHA=true python infrastructure/adapters/inbound/api.py
```

### Exemplos de chamadas
```bash
# 1. Inscrever sócio (com correlationId personalizado)
curl -X POST http://localhost:5000/socios \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: meu-teste-001" \
  -d '{"nome":"Ana Silva","email":"ana@gym.pt","data_nascimento":"1990-05-15","plano":"STANDARD"}'

# 2. Solicitar relatório (assíncrono — resposta imediata)
curl -X POST http://localhost:5000/socios/{id}/relatorio \
  -H "X-Correlation-ID: meu-teste-001"
# → Retorna job_id em < 10ms (Fase 1 bloqueava 2s)

# 3. Verificar observabilidade
curl http://localhost:5000/sistema/stats
curl "http://localhost:5000/sistema/eventos"

# 4. Demonstrar falha e retry
curl -X POST http://localhost:5000/admin/demo-falha
curl -X POST http://localhost:5000/socios/{id}/relatorio
# → Ver nos logs o retry automático com o mesmo correlationId
```

### Executar testes
```bash
# Testes da Fase 1 (mantidos e passam)
python -m pytest tests/unit tests/integration -v

# Testes da Fase 2 (novos)
python -m pytest tests/fase2 -v
# Nota: os testes do worker demoram ~15s (aguardam processamento assíncrono)
```

---

## 9. Uso de IA

| Campo | Conteúdo |
|-------|----------|
| **Ferramentas utilizadas** | Claude Sonnet 4.6 |
| **Tarefas assistidas** | Geração da estrutura inicial dos módulos `queue.py`, `event_bus.py`, `relatorio_worker.py` e `consumers.py`; boilerplate dos testes da Fase 2; estruturação do relatório técnico |
| **Adaptações manuais** | Decisão de usar `threading.Lock` e `queue.Queue` da stdlib (sem dependências externas); lógica de backoff exponencial com `min(2^n, 8)`; decisão de propagar correlationId via parâmetro explícito em vez de thread-local; estrutura do middleware Flask para injeção de correlationId; lógica de isolamento de falhas no BusEventos (try/except por handler); definição dos TipoEvento e subscrições no container; endpoint `/admin/demo-falha` para demonstração controlada |
| **Partes sem IA** | Análise comparativa Fase 1 vs Fase 2 e justificação dos RNF; decisão de manter a infraestrutura 100% em memória (sem Redis/RabbitMQ) para cumprir a restrição do enunciado; decisão de não modificar nenhuma linha do Core para demonstrar DIP; identificação dos pontos de falha da Fase 1 e mapeamento para os padrões da Fase 2 |

---

## 10. Reposotório Git

https://github.com/Wayllw/gymcore.git

---

*Relatório gerado para a Entrega 2 — Arquiteturas de Software — Mestrado em Informática Aplicada*
