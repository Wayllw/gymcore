"""
Adaptador de entrada: API REST com Flask.

O Flask é um detalhe de infraestrutura — o Core não sabe que existe.
Se amanhã mudarmos para FastAPI ou Django, apenas este ficheiro muda.
"""
import logging
import uuid
from datetime import date, datetime
from flask import Flask, jsonify, request, redirect
from flask_swagger_ui import get_swaggerui_blueprint

from infrastructure.config.container import container
from application.dtos.dtos import (
    InscreverSocioDTO,
    CriarPlanoTreinoDTO,
    ExercicioDTO,
)
from domain.exceptions.dominio_exceptions import (
    GymCoreException,
    SocioNaoEncontradoException,
    SocioJaExisteException,
    PlanoTreinoNaoEncontradoException,
)

# ── Configuração de logging estruturado ────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Swagger UI ─────────────────────────────────────────────────────────────────
SWAGGER_URL = "/docs"
API_URL = "/swagger.json"

swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={"app_name": "GymCore API — Fase 1"},
)
app.register_blueprint(swaggerui_blueprint)

@app.route("/")
def index():
    return redirect("/docs")

@app.route("/swagger.json")
def swagger_spec():
    return jsonify({
        "openapi": "3.0.0",
        "info": {
            "title": "GymCore API",
            "version": "1.0.0",
            "description": "Sistema de Gestão de Ginásio — Fase 1: Monólito Hexagonal"
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health check",
                    "tags": ["Sistema"],
                    "responses": {"200": {"description": "API online"}}
                }
            },
            "/socios": {
                "get": {
                    "summary": "Listar todos os sócios",
                    "tags": ["Sócios"],
                    "responses": {"200": {"description": "Lista de sócios"}}
                },
                "post": {
                    "summary": "Inscrever novo sócio",
                    "tags": ["Sócios"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["nome", "email", "data_nascimento", "plano"],
                                    "properties": {
                                        "nome": {"type": "string", "example": "Ana Silva"},
                                        "email": {"type": "string", "example": "ana@gym.pt"},
                                        "data_nascimento": {"type": "string", "example": "1990-05-15"},
                                        "plano": {"type": "string", "enum": ["BASICO", "STANDARD", "PREMIUM"]}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "Sócio criado"}, "409": {"description": "Email já existe"}}
                }
            },
            "/socios/{socio_id}": {
                "get": {
                    "summary": "Obter sócio por ID",
                    "tags": ["Sócios"],
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Sócio encontrado"}, "404": {"description": "Não encontrado"}}
                }
            },
            "/socios/{socio_id}/plano": {
                "patch": {
                    "summary": "Atualizar plano do sócio",
                    "tags": ["Sócios"],
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "plano": {"type": "string", "enum": ["BASICO", "STANDARD", "PREMIUM"]}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Plano atualizado"}}
                }
            },
            "/socios/{socio_id}/suspender": {
                "post": {
                    "summary": "Suspender sócio",
                    "tags": ["Sócios"],
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Sócio suspenso"}}
                }
            },
            "/socios/{socio_id}/planos-treino": {
                "get": {
                    "summary": "Listar planos de treino do sócio",
                    "tags": ["Planos de Treino"],
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Lista de planos"}}
                },
                "post": {
                    "summary": "Criar plano de treino",
                    "tags": ["Planos de Treino"],
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["nome", "nivel", "exercicios"],
                                    "properties": {
                                        "nome": {"type": "string", "example": "Plano Força"},
                                        "nivel": {"type": "string", "enum": ["INICIANTE", "INTERMEDIO", "AVANCADO"]},
                                        "exercicios": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "nome": {"type": "string", "example": "Supino"},
                                                    "series": {"type": "integer", "example": 3},
                                                    "repeticoes": {"type": "integer", "example": 10},
                                                    "descanso_segundos": {"type": "integer", "example": 60},
                                                    "tipo": {"type": "string", "enum": ["FORCA", "CARDIO", "FLEXIBILIDADE", "FUNCIONAL"]}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "Plano criado"}}
                }
            },
            "/planos-treino/{plano_id}": {
                "get": {
                    "summary": "Obter plano de treino por ID",
                    "tags": ["Planos de Treino"],
                    "parameters": [{"name": "plano_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Plano encontrado"}, "404": {"description": "Não encontrado"}}
                }
            },
            "/socios/{socio_id}/relatorio": {
                "post": {
                    "summary": "Gerar relatório do sócio (processo pesado ~2s)",
                    "tags": ["Relatórios"],
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Relatório gerado"}}
                }
            }
        }
    })


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _serialize(obj):
    """Serialização recursiva de DTOs para JSON."""
    if hasattr(obj, '__dict__'):
        return {k: _serialize(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, (uuid.UUID,)):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj


def _ok(data, status=200):
    return jsonify({"sucesso": True, "dados": _serialize(data)}), status


def _erro(mensagem: str, status=400):
    return jsonify({"sucesso": False, "erro": mensagem}), status


# ── Error handlers ─────────────────────────────────────────────────────────────

@app.errorhandler(SocioNaoEncontradoException)
@app.errorhandler(PlanoTreinoNaoEncontradoException)
def handle_not_found(e):
    return _erro(str(e), 404)


@app.errorhandler(SocioJaExisteException)
def handle_conflict(e):
    return _erro(str(e), 409)


@app.errorhandler(GymCoreException)
def handle_domain(e):
    return _erro(str(e), 400)


@app.errorhandler(Exception)
def handle_generic(e):
    logger.exception("Erro inesperado: %s", e)
    return _erro("Erro interno do servidor.", 500)


# ── Rotas: Sócios ──────────────────────────────────────────────────────────────

@app.route("/socios", methods=["POST"])
def inscrever_socio():
    body = request.get_json(force=True)
    dto = InscreverSocioDTO(
        nome=body["nome"],
        email=body["email"],
        data_nascimento=_parse_date(body["data_nascimento"]),
        plano=body["plano"],
    )
    resultado = container.inscrever_socio.executar(dto)
    return _ok(resultado, 201)


@app.route("/socios", methods=["GET"])
def listar_socios():
    resultado = container.listar_socios.executar()
    return _ok(resultado)


@app.route("/socios/<socio_id>", methods=["GET"])
def obter_socio(socio_id: str):
    resultado = container.obter_socio.executar(uuid.UUID(socio_id))
    return _ok(resultado)


@app.route("/socios/<socio_id>/plano", methods=["PATCH"])
def atualizar_plano_socio(socio_id: str):
    body = request.get_json(force=True)
    resultado = container.atualizar_plano.executar(
        uuid.UUID(socio_id), body["plano"]
    )
    return _ok(resultado)


@app.route("/socios/<socio_id>/suspender", methods=["POST"])
def suspender_socio(socio_id: str):
    resultado = container.suspender_socio.executar(uuid.UUID(socio_id))
    return _ok(resultado)


# ── Rotas: Planos de Treino ────────────────────────────────────────────────────

@app.route("/socios/<socio_id>/planos-treino", methods=["POST"])
def criar_plano_treino(socio_id: str):
    body = request.get_json(force=True)
    exercicios = [
        ExercicioDTO(
            nome=ex["nome"],
            series=ex["series"],
            repeticoes=ex["repeticoes"],
            descanso_segundos=ex["descanso_segundos"],
            tipo=ex["tipo"],
        )
        for ex in body.get("exercicios", [])
    ]
    dto = CriarPlanoTreinoDTO(
        socio_id=uuid.UUID(socio_id),
        nome=body["nome"],
        nivel=body["nivel"],
        exercicios=exercicios,
    )
    resultado = container.criar_plano.executar(dto)
    return _ok(resultado, 201)


@app.route("/socios/<socio_id>/planos-treino", methods=["GET"])
def listar_planos_treino(socio_id: str):
    resultado = container.listar_planos_socio.executar(uuid.UUID(socio_id))
    return _ok(resultado)


@app.route("/planos-treino/<plano_id>", methods=["GET"])
def obter_plano_treino(plano_id: str):
    resultado = container.obter_plano.executar(uuid.UUID(plano_id))
    return _ok(resultado)


# ── Rotas: Relatórios (processo pesado) ───────────────────────────────────────

@app.route("/socios/<socio_id>/relatorio", methods=["POST"])
def gerar_relatorio(socio_id: str):
    resultado = container.gerar_relatorio.executar(uuid.UUID(socio_id))
    return _ok({"caminho": resultado})


# ── Health check ───────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "fase": "1-monolito", "versao": "1.0.0"})


if __name__ == "__main__":
    logger.info("🏋️  GymCore — Fase 1: Monólito Hexagonal a iniciar...")
    app.run(debug=True, host="0.0.0.0", port=5000)