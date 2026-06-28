# Diagrama de Arquitetura — Fase 3 (Mermaid)

Visualizável em https://mermaid.live ou diretamente no GitHub/GitLab.

## Visão de Contentores (nível C4 — Container Diagram)

```mermaid
C4Container
    title GymCore — Fase 3: Microservices

    Person(cliente, "Cliente", "Utilizador da API (Postman, frontend, etc.)")

    System_Boundary(gymcore, "GymCore") {
        Container(gateway, "API Gateway", "Flask/Python", "Ponto único de entrada. Roteamento + correlationId + agregação leve.")
        Container(socios, "Sócios-Service", "Flask + gRPC/Python", "Gestão de sócios e mensalidades. Expõe REST :8001 e gRPC :9001.")
        Container(treinos, "Treinos-Service", "Flask/Python", "Gestão de planos de treino. Cliente gRPC com Circuit Breaker.")
        ContainerDb(socios_db, "socios.db", "SQLite", "Dados de sócios. Acesso exclusivo do Sócios-Service.")
        ContainerDb(treinos_db, "treinos.db", "SQLite", "Dados de planos de treino. Acesso exclusivo do Treinos-Service.")
        Container(redis, "Redis Streams", "Redis 7", "Broker assíncrono. stream:socios e stream:treinos.")
    }

    Rel(cliente, gateway, "HTTPS/REST", "JSON")
    Rel(gateway, socios, "REST", "JSON + X-Correlation-ID")
    Rel(gateway, treinos, "REST", "JSON + X-Correlation-ID")
    Rel(treinos, socios, "gRPC (síncrono)", "ValidarSocio — protegido por Circuit Breaker")
    Rel(socios, socios_db, "Lê/Escreve", "SQL")
    Rel(treinos, treinos_db, "Lê/Escreve", "SQL")
    Rel(socios, redis, "Publica", "stream:socios")
    Rel(treinos, redis, "Consome", "stream:socios (Saga)")
    Rel(treinos, redis, "Publica", "stream:treinos (compensação)")
    Rel(socios, redis, "Consome", "stream:treinos (compensação)")
```

## Fluxo: Saga "Inscrição Completa" (sucesso)

```mermaid
sequenceDiagram
    participant C as Cliente
    participant GW as API Gateway
    participant S as Sócios-Service
    participant R as Redis Streams
    participant T as Treinos-Service

    C->>GW: POST /socios {nome, email, plano}
    GW->>S: POST /socios (X-Correlation-ID: cid-001)
    S->>S: Persiste sócio (SQLite)
    S->>R: XADD stream:socios {tipo: socio.inscrito, cid-001}
    S-->>GW: 201 Created
    GW-->>C: 201 Created

    Note over R,T: Processamento assíncrono — já não bloqueia o cliente

    R->>T: XREADGROUP (consumer group)
    T->>S: gRPC ValidarSocio(socio_id, cid-001)
    S-->>T: existe=true, ativo=true
    T->>T: Cria "Plano Inicial de Adaptação" (SQLite)
    T->>R: XADD stream:treinos {tipo: plano_inicial.criado, cid-001}
    T->>R: XACK
```

## Fluxo: Saga "Inscrição Completa" (falha + compensação)

```mermaid
sequenceDiagram
    participant R as Redis Streams
    participant T as Treinos-Service
    participant S as Sócios-Service

    R->>T: XREADGROUP socio.inscrito (cid-002)
    T->>S: gRPC ValidarSocio(socio_id, cid-002)

    alt Circuito aberto (Sócios-Service indisponível)
        T->>T: pybreaker rejeita imediatamente (CircuitBreakerError)
    else Sócio suspenso/inexistente
        S-->>T: existe=false OU ativo=false
    end

    T->>T: NÃO cria plano (sem rollback de inscrição)
    T->>R: XADD stream:treinos {tipo: plano_inicial.falhou, motivo, cid-002}
    T->>R: XACK

    R->>S: XREADGROUP plano_inicial.falhou (cid-002)
    S->>S: MarcarParaAcompanhamentoUseCase (ação de compensação)
    S->>R: XACK

    Note over S,T: Saga coreografada: cada serviço decide a sua<br/>própria reação, sem transação distribuída.
```

## Fluxo: Circuit Breaker (chamada síncrona gRPC)

```mermaid
stateDiagram-v2
    [*] --> CLOSED
    CLOSED --> CLOSED: chamada bem-sucedida
    CLOSED --> OPEN: 3ª falha consecutiva (fail_max=3)
    OPEN --> OPEN: chamadas rejeitadas imediatamente\n(CircuitBreakerError, sem tentar a rede)
    OPEN --> HALF_OPEN: após reset_timeout=10s
    HALF_OPEN --> CLOSED: chamada de teste bem-sucedida
    HALF_OPEN --> OPEN: chamada de teste falha
```
