# GymCore — Relatório Técnico: Fase 3 — Microservices, Persistência e Interoperabilidade

**Unidade Curricular:** Arquiteturas de Software
**Fase:** 3 — Microservices, Persistência e Interoperabilidade
**Data:** 20 de maio de 2026

---

## 1. Análise Comparativa: Por que a Fase 2 deixou de ser suficiente

### 1.1 O problema identificado

Na Fase 2, o sistema continuava a ser um único processo (monólito), apesar de ter ganho processamento assíncrono e comunicação por eventos *internos* (em memória). Isto significava:

- **Acoplamento de deployment**: qualquer alteração ao domínio de Treino obrigava a reiniciar todo o sistema, incluindo Sócios.
- **Escalabilidade acoplada**: não era possível escalar o processamento de planos de treino sem escalar também a gestão de sócios — mesmo que tivessem padrões de carga completamente diferentes.
- **Falha sistémica**: um erro não tratado em qualquer parte do processo Python podia derrubar a aplicação inteira, incluindo funcionalidades não relacionadas.
- **Um único ponto de persistência**: ambos os domínios partilhavam o mesmo processo e, implicitamente, a mesma "unidade de evolução" — uma mudança de schema para Treinos arriscava efeitos colaterais em Sócios.

O enunciado da Fase 3 exige explicitamente a evolução para microservices com bases de dados independentes — e os dois domínios já identificados desde a Fase 1 (Sócios e Planos de Treino) tornam essa fronteira natural.

### 1.2 RNF que motivam a evolução

| ID | Requisito | Fase 2 | Fase 3 |
|----|-----------|--------|--------|
| RNF-2 | Manutenibilidade | ⚠️ Módulos separados, mas no mesmo deployment | ✅ Serviços com ciclo de vida e deployment independentes |
| RNF-4 | Escalabilidade | ❌ Só é possível escalar o processo inteiro | ✅ Cada serviço escala de forma independente |
| RNF-5 | Resiliência | ⚠️ Retry e DLQ, mas falhas internas (mesmo processo) | ✅ Circuit Breaker entre serviços + Saga com compensação |
| RNF-6 | Observabilidade | ✅ correlationId num único processo | ✅ correlationId propagado entre **processos e protocolos** (REST + gRPC + Redis) |
| Database-per-Service | — | ❌ Repositórios em memória partilhados | ✅ SQLite isolado, um ficheiro por serviço |

---

## 2. Decomposição DDD: Bounded Contexts

A decisão de fronteira segue diretamente os dois domínios já identificados desde a Fase 1:

| Bounded Context | Serviço | Responsabilidade | Dados que possui |
|---|---|---|---|
| **Gestão de Sócios** | `socios-service` | Inscrição, suspensão, planos de mensalidade, cálculo de quotas | `Socio` (nome, email, plano, estado) |
| **Gestão de Treino** | `treinos-service` | Criação e gestão de planos de treino e exercícios | `PlanoTreino`, `Exercicio` |

**Linguagem ubíqua por contexto**: dentro de `socios-service`, "plano" significa `PlanoMensalidade` (BASICO/STANDARD/PREMIUM). Dentro de `treinos-service`, "plano" significa `PlanoTreino` (uma sequência de exercícios). Este é exatamente o tipo de ambiguidade que o DDD resolve ao definir fronteiras de contexto explícitas — o mesmo termo tem significados diferentes em modelos diferentes, e isso é aceitável porque cada serviço só usa o seu próprio vocabulário.

**Relação entre contextos**: `PlanoTreino.socio_id` é uma referência fraca (apenas um UUID) — nunca uma foreign key de base de dados. O Treinos-Service nunca lê a tabela de Sócios diretamente; só conhece a *existência* de um sócio através da API gRPC exposta pelo Sócios-Service.

---

## 3. Database-per-Service

Cada serviço gere o seu próprio ficheiro SQLite, sem qualquer acesso direto de um serviço aos dados do outro:

```
socios-service/dados/socios.db    ← só o Sócios-Service lê/escreve aqui
treinos-service/dados/treinos.db  ← só o Treinos-Service lê/escreve aqui
```

**Porquê SQLite e não PostgreSQL/MySQL?**
O enunciado pede execução local obrigatória sem serviços cloud geridos, e SQLite cumpre exatamente isso sem exigir um servidor de BD adicional no `docker-compose`. A interface `IPlanoTreinoRepository`/`ISocioRepository` (definida no Core de cada serviço) significa que trocar SQLite por PostgreSQL exigiria apenas uma nova implementação do repositório e uma linha no `container.py` — exatamente a mesma demonstração de DIP já feita nas Fases 1 e 2, agora aplicada por serviço.

**Implicação arquitetural directa**: como não há JOIN possível entre `socios.db` e `treinos.db`, qualquer operação que precise de dados de ambos os domínios *tem* de atravessar a rede — é isto que justifica tanto o gRPC (síncrono) como os eventos via Redis Streams (assíncrono) descritos abaixo.

---

## 4. Comunicação Síncrona: gRPC

### 4.1 Porquê gRPC e não apenas REST?

O Treinos-Service precisa de confirmar, em sincronia, que um sócio existe e está ativo *antes* de persistir um plano de treino — não pode "criar primeiro e validar depois", pois isso permitiria planos órfãos associados a sócios inexistentes.

Esta validação:
- É **tráfego interno** (nunca exposta a clientes externos)
- Acontece em **todos** os pedidos de criação de plano (alta frequência)
- Beneficia de um **contrato fortemente tipado** (Protocol Buffers) — qualquer alteração ao contrato é detetada em tempo de compilação do stub, não em runtime como aconteceria com JSON

REST continua a ser usado para tudo o que é exposto a clientes externos (através do API Gateway), porque aí a prioridade é interoperabilidade universal, não desempenho máximo.

### 4.2 Contrato (`proto/socio_validation.proto`)

```protobuf
service SocioValidationService {
  rpc ValidarSocio (ValidarSocioRequest) returns (ValidarSocioResponse);
}

message ValidarSocioRequest {
  string socio_id = 1;
  string correlation_id = 2;
}

message ValidarSocioResponse {
  bool existe = 1;
  bool ativo = 2;
  string nome = 3;
  string estado = 4;
  string mensagem = 5;
}
```

Note-se que `correlation_id` faz parte do contrato — a observabilidade distribuída exige que o ID viaje mesmo através do protocolo binário gRPC, não apenas em headers HTTP.

### 4.3 Fluxo

```
Treinos-Service                          Sócios-Service
CriarPlanoTreinoUseCase
   │
   ▼
GrpcSocioValidationClient
   │ (envolvido em pybreaker)
   ▼
gRPC ValidarSocio(socio_id, correlation_id) ──────► SocioValidationServicer
                                                          │
                                                          ▼
                                                    ISocioRepository.obter_por_id()
                                                          │
   ◄────────────────────────────────────────────── existe, ativo, nome, mensagem
   ▼
Decide: persistir plano OU SocioInvalidoException
```

---

## 5. Comunicação Assíncrona: Redis Streams

### 5.1 Porquê Redis Streams?

Redis Streams foi escolhido sobre RabbitMQ por:
- **Já fazer parte do ecossistema conhecido** do grupo (uso prévio em trabalho de NoSQL)
- **Persistência leve**: mensagens não confirmadas (sem XACK) permanecem no stream e podem ser reprocessadas — comportamento equivalente a uma fila durável, sem a complexidade operacional de um broker dedicado
- **Consumer Groups nativos**: permitem que cada serviço tenha o seu próprio ponto de leitura (offset) no mesmo stream, com garantia de entrega "at-least-once"

### 5.2 Streams usados

| Stream | Produtor | Consumidor | Eventos |
|---|---|---|---|
| `stream:socios` | Sócios-Service | Treinos-Service | `socio.inscrito`, `socio.suspenso` |
| `stream:treinos` | Treinos-Service | Sócios-Service | `plano_inicial.criado`, `plano_inicial.falhou` |

Cada consumidor usa um **Consumer Group** dedicado (`socios-service-group`, `treinos-service-group`), o que permite a qualquer serviço reiniciar sem perder mensagens pendentes — ao reiniciar, o `XREADGROUP` retoma exatamente onde tinha ficado.

---

## 6. Saga Coreografada: "Inscrição Completa"

### 6.1 O problema que a Saga resolve

Quando um sócio se inscreve, o requisito de negócio é que receba também um plano de treino inicial automático. Mas:
- A criação do sócio e a criação do plano vivem em **bases de dados diferentes**
- Não existe transação distribuída (2PC) disponível, nem seria desejável (acopla os serviços e bloqueia recursos)

A solução é uma **Saga coreografada**: em vez de um orquestrador central que comanda os dois passos, cada serviço reage de forma autónoma aos eventos que recebe, sem qualquer coordenador.

### 6.2 Passo a passo

```
1. Cliente → POST /socios → Sócios-Service
2. Sócios-Service persiste o sócio (commit local, imediato)
3. Sócios-Service publica evento "socio.inscrito" (stream:socios)
4. [resposta HTTP 201 já devolvida ao cliente — não espera pelo passo 5]

5. Treinos-Service consome "socio.inscrito"
6. Treinos-Service valida o sócio via gRPC (ValidarSocio)
7a. SUCESSO: cria "Plano Inicial de Adaptação", persiste localmente,
    publica "plano_inicial.criado" (apenas para registo/observabilidade)
7b. FALHA: publica "plano_inicial.falhou" com o motivo (stream:treinos)

8. [só no caminho de falha] Sócios-Service consome "plano_inicial.falhou"
9. Sócios-Service aplica a ação de COMPENSAÇÃO:
   marca o sócio para acompanhamento manual (MarcarParaAcompanhamentoUseCase)
```

### 6.3 Por que não há rollback da inscrição

Uma Saga clássica com compensação "desfaria" o primeiro passo se o segundo falhasse (ex: apagar o sócio). Aqui isso seria uma decisão de negócio péssima: o sócio pagou, está inscrito, e um problema técnico na geração automática de um plano de treino *não deveria* cancelar a inscrição. A compensação escolhida — marcar para acompanhamento manual — reflete melhor a realidade: um funcionário do ginásio cria manualmente o plano em falta.

Isto demonstra o princípio central das Sagas coreografadas: a compensação não é "undo automático", é uma decisão de negócio tomada pelo serviço dono dos dados afetados.

### 6.4 Demonstração de falha

Dois cenários provocam o caminho de compensação, ambos testados (ver `tests/integration/`):

1. **Sócio inexistente** no momento da validação (race condition simulada) → `existe=False`
2. **Circuito aberto** (Sócios-Service indisponível) → `SocioValidationIndisponivelException`

Em ambos os casos, `CriarPlanoInicialUseCase` **nunca propaga a exceção para fora** — sempre publica `plano_inicial.falhou` e retorna normalmente. Isto é crítico: se a exceção escapasse, o consumer do Redis Stream não faria `XACK`, a mensagem ficaria pendente indefinidamente, e o sistema ficaria num estado inconsistente sem qualquer sinal visível do problema.

---

## 7. Resiliência: Circuit Breaker

### 7.1 Porquê Circuit Breaker (e não apenas retry)

Um simples retry no cliente gRPC, sem circuit breaker, teria um efeito perverso: se o Sócios-Service estiver genuinamente em baixo (não apenas lento), cada pedido de criação de plano no Treinos-Service ficaria à espera do timeout antes de falhar — multiplicando a carga sobre um serviço já com problemas e degradando também a latência do Treinos-Service (falha em cascata).

O Circuit Breaker resolve isto com três estados:

| Estado | Comportamento |
|---|---|
| **CLOSED** | Tudo normal. Chamadas passam, falhas são contadas. |
| **OPEN** | Após `fail_max=3` falhas consecutivas, todas as chamadas falham **imediatamente** com `CircuitBreakerError`, sem tentar a rede. |
| **HALF_OPEN** | Após `reset_timeout=10s`, deixa passar **uma** chamada de teste. Sucesso → volta a CLOSED. Falha → volta a OPEN. |

### 7.2 Implementação (`pybreaker`)

```python
socio_validation_breaker = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=10,
    name="SocioValidationService",
    listeners=[CircuitBreakerLogListener()],
)

class GrpcSocioValidationClient(ISocioValidationClient):
    @socio_validation_breaker
    def _chamar_grpc(self, socio_id_str, correlation_id):
        ...  # chamada gRPC real
```

O decorator `@socio_validation_breaker` envolve a chamada real — todas as exceções lançadas dentro dela contam como falha para o pybreaker. O `CircuitBreakerLogListener` regista cada transição de estado nos logs estruturados, com o `correlation_id` do pedido que provocou a transição.

### 7.3 Demonstração de falha verificada

Teste de integração (`tests/integration/test_circuit_breaker.py`) confirma o comportamento real:

```
Tentativa 1: FALHOU | circuito=closed | erro=erro gRPC: UNAVAILABLE
Tentativa 2: FALHOU | circuito=closed | erro=erro gRPC: UNAVAILABLE
Tentativa 3: FALHOU | circuito=closed → open | erro=erro gRPC: UNAVAILABLE
Tentativa 4: FALHOU | circuito=open | erro=circuito aberto — Sócios-Service temporariamente indisponível
Tentativa 5: FALHOU | circuito=open | erro=circuito aberto — Sócios-Service temporariamente indisponível
```

A partir da tentativa 4, o erro muda de "erro gRPC: UNAVAILABLE" para "circuito aberto" — prova de que a chamada de rede deixou de ser tentada.

---

## 8. Observabilidade Distribuída

### 8.1 O desafio acrescentado pela Fase 3

Na Fase 2, o correlationId viajava dentro de **um único processo** (HTTP → fila em memória → worker → eventos em memória). Na Fase 3, o mesmo ID tem de sobreviver a:

- Serialização/desserialização em **3 protocolos diferentes**: HTTP/JSON (Gateway ↔ serviços), gRPC/Protobuf (Treinos ↔ Sócios), Redis Streams (eventos assíncronos)
- **Processos diferentes**, cada um com o seu próprio logger e ciclo de vida

### 8.2 Propagação ponta-a-ponta

```
Cliente → Gateway:        header X-Correlation-ID (gerado se ausente)
Gateway → Sócios/Treinos: header X-Correlation-ID (propagado, nunca regenerado)
Treinos → Sócios (gRPC):  campo correlation_id na mensagem protobuf
Sócios → Redis Stream:    campo "correlation_id" no XADD
Redis Stream → Treinos:   campo lido do XREADGROUP, usado no use case
```

Em qualquer ponto do sistema, `grep "cid-abc-123" *.log` revela o percurso completo de um pedido através de três serviços e dois protocolos distintos.

### 8.3 Exemplo real (Saga de sucesso, capturado em testes manuais)

```
[socios-service]  Sócio inscrito: id=...  | correlation_id=saga-demo-cid-001
[socios-service]  Evento publicado | tipo=socio.inscrito | correlation_id=saga-demo-cid-001
[treinos-service] socio.inscrito recebido | correlation_id=saga-demo-cid-001
[treinos-service] gRPC ValidarSocio | correlation_id=saga-demo-cid-001
[socios-service]  Sócio validado | ativo=True | correlation_id=saga-demo-cid-001
[treinos-service] Plano inicial criado | correlation_id=saga-demo-cid-001
[treinos-service] Evento publicado | tipo=plano_inicial.criado | correlation_id=saga-demo-cid-001
```

---

## 9. API Gateway

O Gateway (porta 8000) é o único ponto de entrada externo. Não contém lógica de negócio — apenas:

1. **Geração/propagação do correlationId** (se o cliente não enviar, gera um novo)
2. **Roteamento simples** por prefixo de path (`/socios/*` → Sócios-Service, `/socios/{id}/planos-treino` → Treinos-Service)
3. **Agregação leve**: o endpoint `GET /socios/{id}/completo` combina dados de ambos os serviços numa única resposta — demonstra que o Gateway pode compor visões sem que os serviços saibam um do outro

O Gateway **não faz** autenticação, balanceamento de carga, ou cache nesta POC — fora do âmbito do enunciado, e adicioná-los sem necessidade demonstrada seria complexidade não justificada (ver nota final do enunciado: "uma solução simples, mas bem justificada, será sempre preferível").

---

## 10. Containerização (Docker Compose)

```yaml
services:
  redis:            # broker assíncrono, healthcheck via redis-cli ping
  socios-service:   # REST :8001 + gRPC :9001, depende de redis saudável
  treinos-service:  # REST :8002, depende de redis + socios-service
  gateway:          # REST :8000, único serviço com porta exposta ao "exterior" conceptual
```

Cada serviço tem o seu próprio `Dockerfile` e `requirements.txt` — não há imagem partilhada, reforçando a autonomia de deployment. Os volumes `socios-data` e `treinos-data` garantem persistência dos ficheiros SQLite entre reinícios dos contentores.

Execução: `docker-compose up --build` — um único comando arranca a topologia completa, incluindo o Redis, sem qualquer serviço cloud gerido (cumprindo "execução local obrigatória").

---

## 11. Estrutura do Repositório

```
gymcore-fase3/
├── proto/
│   └── socio_validation.proto       # Contrato gRPC partilhado
├── socios-service/
│   ├── domain/                      # Core — sem dependências externas
│   ├── application/                 # Use cases + ports (DIP)
│   ├── infrastructure/
│   │   ├── adapters/outbound/sqlite_repository.py
│   │   ├── adapters/inbound/api.py  # REST :8001
│   │   ├── grpc/grpc_server.py      # gRPC :9001
│   │   └── messaging/               # Redis Streams (publisher + consumer)
│   ├── tests/                       # Testes unitários do Core (fakes)
│   ├── Dockerfile
│   └── requirements.txt
├── treinos-service/
│   ├── domain/ application/         # (estrutura simétrica)
│   ├── infrastructure/
│   │   ├── resilience/grpc_client.py  # Cliente gRPC + Circuit Breaker
│   │   └── messaging/
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── gateway/
│   ├── gateway.py
│   ├── Dockerfile
│   └── requirements.txt
├── tests/integration/
│   └── test_circuit_breaker.py      # Teste com gRPC real (subprocess)
├── docs/diagramas/arquitetura.md    # C4 + sequência (Mermaid)
├── docker-compose.yml
├── run_local.sh                     # Alternativa sem Docker
└── RELATORIO_FASE3.md
```

---

## 12. Instruções de Execução

### Opção A — Docker Compose (recomendado, fiel ao enunciado)

```bash
cd gymcore-fase3
docker-compose up --build
```

Serviços disponíveis:
- Gateway: http://localhost:8000
- Sócios-Service: http://localhost:8001 (REST) + porta 9001 (gRPC)
- Treinos-Service: http://localhost:8002

### Opção B — Local sem Docker (desenvolvimento)

```bash
redis-server &                  # arrancar Redis localmente
chmod +x run_local.sh
./run_local.sh start
./run_local.sh logs             # acompanhar logs dos 3 serviços
./run_local.sh stop             # parar tudo
```

### Exemplos de chamadas

```bash
# 1. Inscrever sócio (dispara a Saga)
curl -X POST http://localhost:8000/socios \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: demo-001" \
  -d '{"nome":"Sofia Mendes","email":"sofia@gym.pt","data_nascimento":"1998-02-10","plano":"PREMIUM"}'

# 2. Verificar que a Saga criou o plano inicial automaticamente (aguardar ~1-2s)
curl "http://localhost:8000/socios/{id}/planos-treino"

# 3. Criar um plano manual
curl -X POST "http://localhost:8000/socios/{id}/planos-treino" \
  -H "Content-Type: application/json" \
  -d '{"nome":"Plano Hipertrofia","nivel":"AVANCADO","exercicios":[{"nome":"Supino Reto","series":4,"repeticoes":8,"descanso_segundos":90,"tipo":"FORCA"}]}'

# 4. Visão agregada (combina os 2 serviços)
curl "http://localhost:8000/socios/{id}/completo"

# 5. Verificar estado do circuit breaker
curl http://localhost:8002/health

# 6. Demonstrar falha: parar o socios-service e tentar criar um plano
docker-compose stop socios-service
curl -X POST "http://localhost:8000/socios/{id}/planos-treino" -d '...'
# → 503, e após 3 tentativas o circuito abre (ver logs do treinos-service)
docker-compose start socios-service
```

### Executar testes

```bash
cd socios-service  && python -m pytest tests/ -v   # 9 testes, Core isolado
cd treinos-service && python -m pytest tests/ -v   # 9 testes, Core isolado (inclui Saga)
cd gymcore-fase3   && python -m pytest tests/integration/ -v  # Circuit Breaker real
```

---

## 13. Análise Global: Comparação das Três Arquiteturas

| Dimensão | Fase 1 (Monólito) | Fase 2 (Assíncrono) | Fase 3 (Microservices) |
|---|---|---|---|
| **Unidade de deployment** | 1 processo | 1 processo | 3 processos/contentores independentes |
| **Persistência** | Em memória | Em memória | SQLite por serviço |
| **Comunicação interna** | Chamada direta | Bus de eventos (memória) | gRPC (síncrono) + Redis Streams (assíncrono) |
| **Falha de um componente** | Derruba tudo | Derruba tudo | Isolada ao serviço afetado (com Circuit Breaker a conter o impacto) |
| **Escalabilidade** | Vertical apenas | Vertical apenas | Horizontal, por serviço |
| **Complexidade operacional** | Mínima | Baixa | Alta (rede, observabilidade distribuída, consistência eventual) |
| **Latência típica (relatório)** | 2000ms (bloqueante) | <10ms (fila em memória) | <10ms + latência de rede gRPC/Redis (ainda <50ms local) |
| **Consistência** | Forte (memória partilhada) | Forte (memória partilhada) | Eventual (Saga coreografada, sem transação distribuída) |

### Trade-offs explícitos

**O que se ganhou:**
- Deployment e escala independentes por domínio de negócio
- Isolamento de falhas — o Circuit Breaker demonstra que uma falha no Sócios-Service não bloqueia indefinidamente o Treinos-Service
- Bases de dados isoladas elimina acoplamento acidental via schema partilhado

**O que se perdeu / o custo pago:**
- **Consistência forte → eventual**: entre a inscrição do sócio e a criação do plano inicial existe uma janela de tempo onde o sistema está temporariamente inconsistente (sócio existe, plano ainda não). Isto exigiu desenhar explicitamente a Saga e a compensação — trabalho que não existia nas fases anteriores.
- **Complexidade operacional**: observabilidade distribuída (correlationId entre protocolos), gestão de múltiplas bases de dados, e Docker Compose para orquestrar tudo. Para o volume de utilizadores real deste projeto (um ginásio pequeno), esta complexidade seria provavelmente desproporcionada — é justificada aqui como demonstração académica dos padrões, não como recomendação de produção.
- **Testabilidade mais difícil**: testar a Saga completa exige (como mostrado em `tests/integration/`) arrancar servidores reais em subprocessos, porque os dois serviços não podem coexistir no mesmo processo Python sem conflitos de módulos — um sintoma saudável de que são, de facto, unidades de deployment independentes.

### Sustentabilidade

Do ponto de vista de sustentabilidade computacional, a Fase 3 introduz overhead claro face à Fase 1/2: três processos sempre ativos (vs. um), serialização/desserialização adicional em cada fronteira de rede, e um broker de mensagens a correr permanentemente. Para um sistema com a carga reduzida descrita nos RNF da Fase 1 ("ginásio em fase de arranque"), este custo energético adicional só se justifica pelo valor pedagógico de demonstrar os padrões — n um cenário real de baixo volume, o monólito bem estruturado da Fase 1 seria a escolha mais sustentável. A arquitetura de microservices só compensa esse custo quando os domínios crescem o suficiente para precisarem de escalar de forma independente (RNF-4), o que reforça a tese central do enunciado: a arquitetura deve evoluir em resposta a requisitos reais, não por adoção de tecnologia pela tecnologia.

---

## 14. Uso de IA

| Campo | Conteúdo |
|-------|----------|
| **Ferramentas utilizadas** | Claude Sonnet 4.6 |
| **Tarefas assistidas** | Geração do boilerplate dos dois serviços (entidades, ports, repositórios SQLite, adaptadores REST); geração e adaptação dos stubs gRPC a partir do `.proto`; estrutura inicial do `GrpcSocioValidationClient` com `pybreaker`; estrutura dos consumers Redis Streams com Consumer Groups; boilerplate dos testes unitários (fakes) e do teste de integração com subprocess; estrutura do `docker-compose.yml` e Dockerfiles; redação inicial deste relatório técnico |
| **Adaptações manuais** | Decisão da fronteira de bounded contexts (Sócios vs Treinos) e do que cada serviço pode/não pode aceder; decisão de usar SQLite em vez de PostgreSQL para cumprir "execução local obrigatória" sem complexidade adicional; decisão de Redis Streams sobre RabbitMQ (familiaridade prévia do grupo); desenho da Saga — nomeadamente a decisão de a compensação ser "marcar para acompanhamento" em vez de "apagar o sócio", que é uma decisão de negócio e não técnica; valores de `fail_max=3` e `reset_timeout=10` no Circuit Breaker, escolhidos para a demonstração ser visível em segundos; correção do conflito de `sys.path`/módulos Python ao testar dois serviços no mesmo processo, que motivou a reescrita do teste de integração para usar subprocessos isolados; toda a análise comparativa e de trade-offs da secção 13 |
| **Partes sem IA** | Identificação dos dois domínios desde a Fase 1 (decisão herdada, não recriada agora); decisão de quais RNF justificam cada padrão introduzido; validação manual de todos os fluxos end-to-end (Saga de sucesso e de falha) correndo os três serviços localmente antes de aceitar o código como correto; decisão final sobre o que entra no relatório e o que se omite |

---

*Relatório gerado para a Entrega 3 — Arquiteturas de Software — Mestrado em Informática Aplicada*
