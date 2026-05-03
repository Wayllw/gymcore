# GymCore 🏋️

**Sistema de Gestão de Ginásio — Fase 1: Monólito Hexagonal**

Arquitetura Hexagonal (Ports & Adapters) com DIP, testes unitários sem infraestrutura, e persistência em memória.

## Instalação

```bash
pip install -r requirements.txt
```

## Testes

```bash
python -m pytest tests/ -v
# 42 testes, 0 falhas
```

## Executar API

```bash
python infrastructure/adapters/inbound/api.py
# http://localhost:5000
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

Ver `RELATORIO_FASE1.md` para documentação técnica completa.
