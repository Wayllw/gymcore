Grupo constituido por:
Rui Duarte - 190200190
Laysa Siqueira - 220000005
David Carreira - 200100294


# GymCore 🏋️

**Sistema de Gestão de Ginásio — Fase 1: Monólito Hexagonal**

Arquitetura Hexagonal (Ports & Adapters) com DIP, testes unitários sem infraestrutura, e persistência em memória.

## Instalação

```bash
pip install -r requirements.txt
```


# GymCore — Fase 2: Assincronismo, Event-Driven e Observabilidade

Sistema de gestão de ginásio evoluído da arquitetura monolítica hexagonal (Fase 1) para um sistema com processamento assíncrono, comunicação orientada a eventos e observabilidade distribuída.

## Novidades na Fase 2

| O que mudou | Fase 1 | Fase 2 |
|-------------|--------|--------|
| Geração de relatório | Síncrono (bloqueava 2s) | Assíncrono (< 10ms, worker em background) |
| Comunicação entre componentes | Chamada direta | Bus de eventos (pub/sub) |
| Rastreabilidade | Logs básicos | correlationId propagado ponta-a-ponta |
| Resiliência | Sem retry | Retry com backoff exponencial + Dead Letter Queue |
| Observabilidade | Logging simples | Logs estruturados + endpoints de stats |
| Core (domain/use cases) | Inalterado | **Inalterado** (DIP em ação) |

## Executar API

```bash
python infrastructure/adapters/inbound/api.py
# http://localhost:5000
ou

correr run.py
```

## Endpoints

| Método | URL | Descrição |
|--------|-----|-----------|
| GET | `/health` | Estado da aplicação |
| POST | `/socios` | Inscrever sócio |
| GET | `/socios` | Listar todos os sócios |
| GET | `/socios/{id}` | Obter sócio |
| PATCH | `/socios/{id}/plano` | Atualizar plano |
| POST | `/socios/{id}/suspender` | Suspender sócio |
| POST | `/socios/{id}/planos-treino` | Criar plano de treino |
| GET | `/socios/{id}/planos-treino` | Listar planos do sócio |
| GET | `/planos-treino/{id}` | Obter plano de treino |
| POST | `/socios/{id}/relatorio` | Gerar relatório (processo pesado ~2s) |



## Demonstração de Falha

```bash
# Activar modo de falha em runtime
curl -X POST http://localhost:5000/admin/demo-falha

# Solicitar relatório — falha 2x, sucesso na 3ª
curl -X POST http://localhost:5000/socios/{id}/relatorio \
  -H "X-Correlation-ID: demo-falha-001"

# Seguir nos logs pelo mesmo correlationId
```

Ver RELATORIO_FASE2.md para análise arquitetural completa.
