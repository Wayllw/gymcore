# GymCore — Fase 3: Microservices, Persistência e Interoperabilidade

Sistema de gestão de ginásio evoluído de monólito hexagonal (Fase 1) → assíncrono/event-driven (Fase 2) → **microservices com bases de dados independentes** (Fase 3).

## Topologia

```
                    ┌─────────────┐
   Cliente ────────▶│ API Gateway │  :8000
                    └──────┬──────┘
                 ┌─────────┴─────────┐
                 ▼                   ▼
        ┌─────────────────┐  ┌──────────────────┐
        │  Sócios-Service  │  │ Treinos-Service  │
        │  REST :8001      │◀─┤ REST :8002        │
        │  gRPC :9001      │gRPC (Circuit Breaker)│
        │  BD: socios.db   │  │  BD: treinos.db   │
        └────────┬─────────┘  └─────────┬─────────┘
                 │                      │
                 └──────────┬───────────┘
                             ▼
                   ┌──────────────────┐
                   │  Redis Streams    │  :6379
                   │  (Saga + eventos) │
                   └──────────────────┘
```

## Novidades na Fase 3

| O que mudou | Fase 2 | Fase 3 |
|---|---|---|
| Deployment | 1 processo | 2 microservices + Gateway + Redis (4 contentores) |
| Persistência | Em memória / ficheiro JSON | SQLite — 1 BD por serviço, sem acesso cruzado |
| Comunicação síncrona | Chamadas Python diretas | gRPC entre serviços (Treinos → Sócios) |
| Comunicação assíncrona | Bus de eventos em memória | Redis Streams (Consumer Groups) |
| Resiliência | Retry + backoff | + Circuit Breaker (pybreaker) entre serviços |
| Padrão distribuído | — | Saga coreografada ("Inscrição Completa") com compensação |
| Observabilidade | correlationId num processo | correlationId entre 3 protocolos (REST/gRPC/Redis) |
| Execução | `python api.py` | `docker-compose up` |

## Execução Rápida

```bash
docker-compose up --build
```

- Gateway: http://localhost:8000
- Sócios-Service: http://localhost:8001 (gRPC :9001)
- Treinos-Service: http://localhost:8002

Alternativa sem Docker: ver `run_local.sh` (requer Redis local).

## Demonstração da Saga

```bash
# Inscrever sócio — dispara a Saga "Inscrição Completa"
curl -X POST http://localhost:8000/socios \
  -H "Content-Type: application/json" \
  -d '{"nome":"Sofia Mendes","email":"sofia@gym.pt","data_nascimento":"1998-02-10","plano":"PREMIUM"}'

# Aguardar ~1-2s e verificar o plano inicial criado automaticamente
curl http://localhost:8000/socios/{id}/planos-treino
```

## Demonstração do Circuit Breaker

```bash
docker-compose stop socios-service
curl -X POST http://localhost:8000/socios/{id}/planos-treino -d '{"nome":"X","nivel":"INICIANTE","exercicios":[]}'
# Repetir 3x → circuito abre → erro muda de "timeout gRPC" para "circuito aberto"
curl http://localhost:8002/health   # mostra circuit_breaker_estado
docker-compose start socios-service
```

## Testes

```bash
cd socios-service  && python -m pytest tests/ -v
cd treinos-service && python -m pytest tests/ -v
python -m pytest tests/integration/ -v   # Circuit Breaker com gRPC real
```

## Documentação

- `RELATORIO_FASE3.md` — relatório técnico completo (RNF, decisões, Saga, trade-offs)
- `docs/diagramas/arquitetura.md` — diagramas C4 e de sequência (Mermaid)
- `proto/socio_validation.proto` — contrato gRPC
