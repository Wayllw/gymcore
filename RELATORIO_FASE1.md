# GymCore — Relatório Técnico: Fase 1 — Monólito Hexagonal

**Unidade Curricular:** Arquiteturas de Software  
**Fase:** 1 — Monólito Bem Estruturado  
**Data:** 3 de maio de 2025  

---

## 1. Descrição do Sistema

O **GymCore** é um sistema de gestão de ginásio que cobre dois domínios distintos:

- **Domínio de Sócios** — inscrição, suspensão, gestão de planos de mensalidade e geração de relatórios individuais.
- **Domínio de Treino** — criação e gestão de planos de treino personalizados com exercícios, séries, repetições e duração estimada.

O sistema inclui ainda um processo pesado identificado: a **geração de relatórios de progresso**, que na Fase 1 é simulada de forma síncrona (~2s) e que justificará a introdução do padrão Web-Queue-Worker na Fase 2.

---

## 2. Requisitos Não Funcionais (RNF)

Os RNF foram definidos antes de qualquer decisão arquitetural e são o motor de toda a evolução do sistema.

| ID    | Requisito             | Métrica / Critério                                                                 | Fase relevante     |
|-------|-----------------------|------------------------------------------------------------------------------------|--------------------|
| RNF-1 | **Testabilidade**     | Cobertura de testes unitários no Core ≥ 80%, sem necessidade de infraestrutura    | 1, 2, 3            |
| RNF-2 | **Manutenibilidade**  | Qualquer camada substituível sem alterar o Core. Acoplamento medido por imports    | 1, 2, 3            |
| RNF-3 | **Desempenho**        | Respostas da API < 200ms (exceto processo pesado). Throughput ≥ 50 req/s no monólito | 1 (baseline)     |
| RNF-4 | **Escalabilidade**    | Suportar 10× crescimento de sócios sem redesenho do Core                          | 2, 3               |
| RNF-5 | **Resiliência**       | Falha num processo pesado não afeta o fluxo principal                             | 2, 3               |
| RNF-6 | **Observabilidade**   | Logging estruturado em todas as camadas; rastreabilidade de erros                 | 1 (base), 2, 3     |
| RNF-7 | **Portabilidade**     | Execução local sem dependências externas (sem cloud, sem Docker na Fase 1)        | 1                  |
| RNF-8 | **Segurança**         | Validação de input no domínio; sem exposição de IDs internos em erros              | 1, 2, 3            |

---

## 3. Arquitetura: Hexagonal (Ports & Adapters)

### 3.1 Justificação da Arquitetura

A arquitetura hexagonal foi escolhida sobre a N-camadas por três razões concretas ligadas aos RNF:

1. **RNF-1 (Testabilidade):** O Core é completamente isolado de frameworks. É possível testar toda a lógica de negócio com `pytest` e mocks, sem iniciar o Flask ou qualquer repositório real.

2. **RNF-2 (Manutenibilidade):** A troca do repositório em memória por PostgreSQL (Fase 3) ou do Flask por FastAPI é feita num único ponto — o Container de DI — sem tocar no Core.

3. **RNF-4 (Escalabilidade futura):** A separação em portos facilita a extração de serviços para microservices (Fase 3), mantendo os contratos de interface.

### 3.2 Diagrama de Camadas (C4 — Nível de Componentes)

```
┌──────────────────────────────────────────────────────────────┐
│                     INFRAESTRUTURA (Adaptadores)              │
│                                                              │
│  ┌─────────────────┐              ┌──────────────────────┐  │
│  │  INBOUND         │              │  OUTBOUND             │  │
│  │                 │              │                      │  │
│  │  api.py (Flask) │              │  InMemoryRepos       │  │
│  │  → Controllers  │              │  LogNotificacao      │  │
│  │                 │              │  SimuladoRelatorio   │  │
│  └────────┬────────┘              └──────────┬───────────┘  │
│           │                                  │              │
│  ┌────────▼──────────────────────────────────▼───────────┐  │
│  │              container.py (Composition Root / DI)      │  │
│  └────────┬──────────────────────────────────────────────┘  │
└───────────│──────────────────────────────────────────────────┘
            │  Injeta implementações concretas nas abstrações
┌───────────▼──────────────────────────────────────────────────┐
│                    APLICAÇÃO (Use Cases + DTOs)               │
│                                                              │
│  InscreverSocioUseCase    CriarPlanoTreinoUseCase            │
│  ObterSocioUseCase        GerarRelatorioSocioUseCase         │
│  ...                                                         │
│                                                              │
│  ◄── Depende apenas de PORTOS (interfaces) ──►               │
│                                                              │
│  ISocioRepository  IPlanoTreinoRepository                    │
│  INotificacaoService  IRelatorioService                      │
└───────────┬──────────────────────────────────────────────────┘
            │  Usa apenas entidades e value objects do domínio
┌───────────▼──────────────────────────────────────────────────┐
│                       DOMÍNIO (Core)                         │
│                                                              │
│  Entities: Socio, PlanoTreino, Exercicio                     │
│  Value Objects: PlanoMensalidade, EstadoSocio, NivelTreino   │
│  Exceptions: GymCoreException e subtipos                     │
│                                                              │
│  ✗ SEM imports de Flask, pytest, SQLAlchemy ou similares     │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Fluxo Principal: Inscrição de Sócio

```
HTTP POST /socios
      │
      ▼
api.py (Flask Controller)
  → parse JSON → InscreverSocioDTO
      │
      ▼
InscreverSocioUseCase.executar(dto)
  → verifica duplicado via ISocioRepository
  → cria entidade Socio (validação no __post_init__)
  → ISocioRepository.guardar(socio)
  → INotificacaoService.enviar_boas_vindas(...)
      │
      ▼
InMemorySocioRepository.guardar(socio)   [Infra]
LogNotificacaoService.enviar_boas_vindas(...)  [Infra]
      │
      ▼
HTTP 201 Created + SocioResponseDTO
```

---

## 4. Princípio da Inversão de Dependência (DIP)

### 4.1 Como é aplicado

O DIP é aplicado de forma sistemática através de três mecanismos:

**a) Interfaces no pacote `application/ports/`**

```python
# O Core define o contrato:
class ISocioRepository(ABC):
    @abstractmethod
    def guardar(self, socio: Socio) -> None: ...

# A Infraestrutura implementa:
class InMemorySocioRepository(ISocioRepository):
    def guardar(self, socio: Socio) -> None:
        self._store[socio.id] = socio
```

**b) Injeção via construtor nos Use Cases**

```python
class InscreverSocioUseCase:
    def __init__(self, socio_repo: ISocioRepository, ...):
        self._repo = socio_repo  # abstração, nunca concretização
```

**c) Composition Root em `container.py`**

O único lugar onde o Core "encontra" a Infraestrutura. Na Fase 3, trocar `InMemorySocioRepository` por `PostgresSocioRepository` é feito **apenas aqui**, numa linha.

### 4.2 Prova: o domínio não importa infraestrutura

Executar o seguinte comando não deve produzir nenhum import de Flask, SQLAlchemy, etc.:

```bash
grep -r "import flask\|import sqlalchemy\|import redis" domain/ application/
# Resultado esperado: nenhuma linha
```

---

## 5. Persistência em Memória

Conforme requisito da Fase 1, não são utilizadas bases de dados externas. Os dados são guardados em dicionários Python com `threading.Lock` para thread-safety:

```python
class InMemorySocioRepository(ISocioRepository):
    def __init__(self):
        self._store: Dict[UUID, Socio] = {}
        self._lock = threading.Lock()
```

**Limitação conhecida e intencional:** os dados perdem-se quando o processo termina. Isto é aceitável na Fase 1 e será resolvido na Fase 3 com base de dados por serviço.

---

## 6. Processo Pesado — Justificação para Fase 2

O endpoint `POST /socios/{id}/relatorio` simula um processo que demora ~2 segundos. No contexto da Fase 1, este bloqueio é aceitável dado o volume reduzido de utilizadores. 

**Por que este processo justifica o Web-Queue-Worker na Fase 2:**
- Bloqueia o thread HTTP durante 2s (afeta RNF-3: latência)
- Não pode ser escalado horizontalmente sem coordenação
- Uma falha no processo degrada a API inteira

O interface `IRelatorioService` já existe no Core. Na Fase 2, a implementação `SimuladoRelatorioService` será substituída por um `QueueRelatorioService` que publica uma mensagem numa fila — **o Core não mudará uma linha** (DIP em ação).

---

## 7. Observabilidade (Fase 1 — Base)

Logging estruturado com níveis adequados em todos os use cases:

```
2025-05-03T10:22:01 | INFO     | socios_use_cases | Sócio inscrito: id=abc-123, email=ana@gym.pt
2025-05-03T10:22:05 | WARNING  | simulated_services | ⚠️ Processo pesado síncrono — Fase 2 migrará para Worker
```

Na Fase 2 será adicionado `correlationId` para rastrear pedidos através de workers e consumidores de eventos.

---

## 8. Justificação do Monólito nesta Fase

**Por que o monólito é adequado na Fase 1?**

1. **Volume reduzido:** Num ginásio em fase de arranque, o número de sócios simultâneos é baixo. O overhead de rede de uma arquitetura distribuída não se justifica.

2. **Complexidade operacional:** Microservices exigem service discovery, balanceamento de carga, gestão de falhas de rede entre serviços — complexidade que não traz valor quando há apenas um utilizador por vez.

3. **Velocidade de desenvolvimento:** Um monólito bem estruturado (hexagonal) permite iterar rapidamente sobre a lógica de negócio sem preocupações de deployment de múltiplos serviços.

4. **A estrutura já prevê a evolução:** A separação em portos e o DIP garantem que os dois domínios (Sócios e Treino) podem ser extraídos para microservices independentes na Fase 3 sem refactoring do Core.

**Quando o monólito deixará de ser suficiente (Fase 2):**
- Quando o processo de geração de relatórios começar a afetar a latência da API (RNF-3 violado)
- Quando múltiplos componentes precisarem de reagir ao mesmo evento (ex: inscrição de sócio → notificação + relatório de boas-vindas + faturação)

---

## 9. Estrutura do Repositório

```
gymcore/
├── domain/                          # Core — sem dependências externas
│   ├── entities/
│   │   ├── socio.py
│   │   └── plano_treino.py
│   ├── value_objects/
│   │   ├── plano_mensalidade.py
│   │   ├── estado_socio.py
│   │   ├── nivel_treino.py
│   │   └── tipo_exercicio.py
│   └── exceptions/
│       └── dominio_exceptions.py
│
├── application/                     # Orquestração — depende só de abstrações
│   ├── ports/
│   │   └── output_ports.py          # Interfaces (DIP)
│   ├── use_cases/
│   │   ├── socios_use_cases.py
│   │   ├── plano_treino_use_cases.py
│   │   └── relatorio_use_cases.py
│   └── dtos/
│       └── dtos.py
│
├── infrastructure/                  # Detalhes técnicos — implementa interfaces
│   ├── adapters/
│   │   ├── inbound/
│   │   │   └── api.py               # Flask (adaptador de entrada)
│   │   └── outbound/
│   │       ├── in_memory_repositories.py
│   │       └── simulated_services.py
│   └── config/
│       └── container.py             # Composition Root (DI)
│
├── tests/
│   ├── unit/
│   │   ├── test_domain.py           # 31 testes — Core puro
│   │   └── test_use_cases.py        # 11 testes — Use Cases com mocks
│   └── integration/
│       └── test_integration.py      # 5 testes — Fluxos completos
│
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## 10. Instruções de Execução

### Pré-requisitos
- Python 3.10+

### Instalação
```bash
cd gymcore
pip install -r requirements.txt
```

### Executar os testes
```bash
# Todos os testes
python -m pytest tests/ -v

# Com cobertura
python -m pytest tests/ --cov=domain --cov=application --cov-report=term-missing
```

### Iniciar a API
```bash
cd gymcore
python infrastructure/adapters/inbound/api.py
# API disponível em http://localhost:5000
```

### Exemplos de chamadas à API
```bash
# Inscrever sócio
curl -X POST http://localhost:5000/socios \
  -H "Content-Type: application/json" \
  -d '{"nome":"Ana Silva","email":"ana@gym.pt","data_nascimento":"1990-05-15","plano":"STANDARD"}'

# Listar sócios
curl http://localhost:5000/socios

# Criar plano de treino (substituir {id} pelo id obtido acima)
curl -X POST http://localhost:5000/socios/{id}/planos-treino \
  -H "Content-Type: application/json" \
  -d '{"nome":"Plano A","nivel":"INICIANTE","exercicios":[{"nome":"Supino","series":3,"repeticoes":10,"descanso_segundos":60,"tipo":"FORCA"}]}'

# Health check
curl http://localhost:5000/health
```

---

## 11. Uso de IA

| Campo | Conteúdo |
|-------|----------|
| **Ferramentas utilizadas** | Claude Sonnet 4.6 |
| **Tarefas assistidas** | Geração do boilerplate dos adaptadores em memória; estrutura inicial dos ficheiros de teste; revisão da coerência entre DTOs e entidades de domínio |
| **Adaptações manuais** | Regras de negócio (desconto seniores, limite 20 exercícios, cálculo de duração) definidas e validadas pelo grupo; decisões sobre quais interfaces criar e onde; toda a justificação arquitetural dos RNF; decisão de usar `threading.Lock` nos repositórios; estrutura do Container de DI |
| **Partes sem IA** | Definição dos RNF e suas métricas; decisão pela arquitetura hexagonal sobre N-camadas; identificação do processo pesado e antecipação do Web-Queue-Worker; organização do relatório técnico |

---

*Relatório gerado para a Entrega 1 — Arquiteturas de Software — Mestrado em Informática Aplicada*
