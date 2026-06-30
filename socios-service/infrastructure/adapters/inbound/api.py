"""
Adaptador de entrada: API REST do Sócios-Service (Flask).

Porta: 8001
Expõe também um servidor gRPC na porta 9001 (ver infrastructure/grpc/grpc_server.py),
arrancado na mesma inicialização, numa thread separada.

Observabilidade distribuída: o correlationId é lido do header X-Correlation-ID
(propagado pelo API Gateway ou por outro serviço) e devolvido na resposta.
"""
import logging
import threading
import uuid
from datetime import date, datetime

from flask import Flask, jsonify, request, g

from infrastructure.config.container import container
from infrastructure.grpc.grpc_server import criar_servidor_grpc
from application.dtos.dtos import InscreverSocioDTO
from domain.exceptions.dominio_exceptions import (
    SociosServiceException,
    SocioNaoEncontradoException,
    SocioJaExisteException,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | socios-service | cid=%(correlation_id)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        try:
            from flask import has_app_context
            record.correlation_id = getattr(g, 'correlation_id', '-') if has_app_context() else '-'
        except Exception:
            record.correlation_id = '-'
        return True


for handler in logging.root.handlers:
    handler.addFilter(CorrelationIdFilter())

logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.before_request
def injetar_correlation_id():
    g.correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


@app.after_request
def adicionar_correlation_header(response):
    response.headers["X-Correlation-ID"] = getattr(g, "correlation_id", "-")
    return response


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _serialize(obj):
    if hasattr(obj, "__dict__"):
        return {k: _serialize(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj


# ── Swagger UI (via CDN — sem dependência do pacote flask-swagger-ui) ────────
SWAGGER_UI_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Sócios-Service — API Docs</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.17.14/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.17.14/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {
      window.ui = SwaggerUIBundle({
        url: '/swagger.json',
        dom_id: '#swagger-ui',
        presets: [SwaggerUIBundle.presets.apis],
      });
    };
  </script>
</body>
</html>
"""


@app.route("/docs", methods=["GET"])
def docs():
    return SWAGGER_UI_HTML


@app.route("/", methods=["GET"])
def index():
    from flask import redirect
    return redirect("/docs")


@app.route("/swagger.json", methods=["GET"])
def swagger_spec():
    return jsonify({
        "openapi": "3.0.0",
        "info": {
            "title": "GymCore — Sócios-Service",
            "version": "3.0.0",
            "description": (
                "Bounded Context: Gestão de Sócios e Mensalidades. "
                "Expõe REST (esta API) e gRPC :9001 (ValidarSocio, usado internamente "
                "pelo Treinos-Service). Database-per-Service: SQLite próprio (socios.db)."
            ),
        },
        "tags": [
            {"name": "Sistema", "description": "Health check"},
            {"name": "Sócios", "description": "Gestão de sócios e mensalidades"},
            {"name": "Saga", "description": "Observabilidade da Saga 'Inscrição Completa'"},
        ],
        "paths": {
            "/health": {
                "get": {
                    "tags": ["Sistema"],
                    "summary": "Health check",
                    "responses": {"200": {"description": "Serviço operacional"}},
                }
            },
            "/socios": {
                "get": {
                    "tags": ["Sócios"],
                    "summary": "Listar todos os sócios",
                    "responses": {"200": {"description": "Lista de sócios"}},
                },
                "post": {
                    "tags": ["Sócios"],
                    "summary": "Inscrever novo sócio",
                    "description": (
                        "Cria o sócio e publica o evento 'socio.inscrito' no Redis Stream "
                        "'stream:socios', desencadeando a Saga 'Inscrição Completa' no "
                        "Treinos-Service."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["nome", "email", "data_nascimento", "plano"],
                                    "properties": {
                                        "nome": {"type": "string", "example": "Sofia Mendes"},
                                        "email": {"type": "string", "example": "sofia@gym.pt"},
                                        "data_nascimento": {"type": "string", "example": "1998-02-10"},
                                        "plano": {"type": "string", "enum": ["BASICO", "STANDARD", "PREMIUM"]},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {"description": "Sócio criado"},
                        "409": {"description": "Email já existe"},
                    },
                },
            },
            "/socios/{socio_id}": {
                "get": {
                    "tags": ["Sócios"],
                    "summary": "Obter sócio por ID",
                    "parameters": [
                        {"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Não encontrado"}},
                }
            },
            "/socios/{socio_id}/plano": {
                "patch": {
                    "tags": ["Sócios"],
                    "summary": "Atualizar plano de mensalidade",
                    "parameters": [
                        {"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["plano"],
                                    "properties": {
                                        "plano": {"type": "string", "enum": ["BASICO", "STANDARD", "PREMIUM"]}
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/socios/{socio_id}/suspender": {
                "post": {
                    "tags": ["Sócios"],
                    "summary": "Suspender sócio",
                    "parameters": [
                        {"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/socios/{socio_id}/acompanhamento": {
                "get": {
                    "tags": ["Saga"],
                    "summary": "Verificar se o sócio foi marcado para acompanhamento manual",
                    "description": (
                        "Ação de compensação da Saga: quando o Treinos-Service não consegue "
                        "criar o plano inicial automático, publica 'plano_inicial.falhou'. "
                        "Este serviço reage marcando o sócio aqui."
                    ),
                    "parameters": [
                        {"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    })


def _ok(data, status=200):
    return jsonify({
        "sucesso": True,
        "dados": _serialize(data),
        "correlation_id": getattr(g, "correlation_id", "-"),
    }), status


def _erro(mensagem, status=400):
    return jsonify({
        "sucesso": False,
        "erro": mensagem,
        "correlation_id": getattr(g, "correlation_id", "-"),
    }), status


@app.errorhandler(SocioNaoEncontradoException)
def handle_not_found(e):
    return _erro(str(e), 404)


@app.errorhandler(SocioJaExisteException)
def handle_conflict(e):
    return _erro(str(e), 409)


@app.errorhandler(SociosServiceException)
def handle_domain(e):
    return _erro(str(e), 400)


@app.errorhandler(Exception)
def handle_generic(e):
    logger.exception("Erro inesperado")
    return _erro("Erro interno do servidor.", 500)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "servico": "socios-service",
        "versao": "3.0.0",
        "correlation_id": getattr(g, "correlation_id", "-"),
    })


@app.route("/socios", methods=["POST"])
def inscrever_socio():
    body = request.get_json(force=True)
    dto = InscreverSocioDTO(
        nome=body["nome"],
        email=body["email"],
        data_nascimento=_parse_date(body["data_nascimento"]),
        plano=body["plano"],
    )
    resultado = container.inscrever_socio.executar(dto, correlation_id=g.correlation_id)
    logger.info("Sócio inscrito via API | id=%s | correlation_id=%s", resultado.id, g.correlation_id)
    return _ok(resultado, 201)


@app.route("/socios", methods=["GET"])
def listar_socios():
    return _ok(container.listar_socios.executar())


@app.route("/socios/<socio_id>", methods=["GET"])
def obter_socio(socio_id):
    return _ok(container.obter_socio.executar(uuid.UUID(socio_id)))


@app.route("/socios/<socio_id>/plano", methods=["PATCH"])
def atualizar_plano_socio(socio_id):
    body = request.get_json(force=True)
    return _ok(container.atualizar_plano.executar(uuid.UUID(socio_id), body["plano"]))


@app.route("/socios/<socio_id>/suspender", methods=["POST"])
def suspender_socio(socio_id):
    return _ok(container.suspender_socio.executar(uuid.UUID(socio_id)))


@app.route("/socios/<socio_id>/acompanhamento", methods=["GET"])
def estado_acompanhamento(socio_id):
    """
    Observabilidade da Saga: permite verificar se um sócio foi marcado
    para acompanhamento manual devido a falha na criação do plano inicial.
    """
    marcado = container.marcar_acompanhamento.esta_marcado(uuid.UUID(socio_id))
    return _ok({"socio_id": socio_id, "necessita_acompanhamento": marcado})


def iniciar_grpc_server():
    server = criar_servidor_grpc(container.socio_repo, porta=9001)
    server.start()
    logger.info("📡 Servidor gRPC do Sócios-Service a escutar na porta 9001")
    server.wait_for_termination()


if __name__ == "__main__":
    logger.info("🏋️  Sócios-Service a iniciar...")

    # Iniciar consumer de eventos do Treinos-Service (compensação da Saga)
    container.iniciar_background()

    # Iniciar servidor gRPC numa thread separada
    grpc_thread = threading.Thread(target=iniciar_grpc_server, daemon=True)
    grpc_thread.start()

    # Iniciar API REST (thread principal)
    app.run(debug=False, host="0.0.0.0", port=8001, use_reloader=False)
