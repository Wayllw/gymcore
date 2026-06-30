"""
API Gateway — GymCore Fase 3.

Único ponto de entrada externo (porta 8000). Não contém lógica de negócio:
apenas encaminha pedidos para o serviço correto e garante que o
correlationId é gerado (se ainda não existir) e propagado a jusante.

Responsabilidades de um Gateway nesta arquitetura:
  - Ponto único de entrada para clientes externos
  - Geração/propagação do correlationId (observabilidade distribuída)
  - Roteamento simples por prefixo de path
  - Agregação leve (endpoint /socios/{id}/completo combina os 2 serviços)

O que o Gateway DELIBERADAMENTE NÃO faz nesta POC:
  - Autenticação/autorização (fora de âmbito do enunciado)
  - Balanceamento de carga (cada serviço tem uma única instância)
  - Cache de respostas
"""
import logging
import os
import uuid

import requests
from flask import Flask, jsonify, request, g

SOCIOS_SERVICE_URL = os.environ.get("SOCIOS_SERVICE_URL", "http://localhost:8001")
TREINOS_SERVICE_URL = os.environ.get("TREINOS_SERVICE_URL", "http://localhost:8002")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | gateway | cid=%(correlation_id)s | %(message)s',
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


def _headers_propagados():
    """Headers a propagar em todos os pedidos a jusante — chave da observabilidade distribuída."""
    return {"X-Correlation-ID": g.correlation_id, "Content-Type": "application/json"}


# ── Swagger UI (via CDN — sem dependência do pacote flask-swagger-ui) ────────
SWAGGER_UI_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>GymCore API Gateway — Docs</title>
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


@app.route("/swagger.json", methods=["GET"])
def swagger_spec():
    return jsonify({
        "openapi": "3.0.0",
        "info": {
            "title": "GymCore — API Gateway",
            "version": "3.0.0",
            "description": (
                "Ponto único de entrada externo. Encaminha pedidos para o "
                "Sócios-Service (:8001) e o Treinos-Service (:8002), propagando "
                "o header X-Correlation-ID para observabilidade distribuída. "
                "Para a documentação detalhada de cada serviço, ver também "
                "http://localhost:8001/docs e http://localhost:8002/docs."
            ),
        },
        "tags": [
            {"name": "Sistema", "description": "Health check do próprio Gateway"},
            {"name": "Sócios", "description": "Encaminhado para o Sócios-Service"},
            {"name": "Planos de Treino", "description": "Encaminhado para o Treinos-Service"},
            {"name": "Agregação", "description": "Combina dados de ambos os serviços"},
        ],
        "paths": {
            "/health": {
                "get": {"tags": ["Sistema"], "summary": "Health check do Gateway",
                         "responses": {"200": {"description": "OK"}}}
            },
            "/socios": {
                "get": {"tags": ["Sócios"], "summary": "Listar sócios (→ Sócios-Service)",
                         "responses": {"200": {"description": "OK"}}},
                "post": {
                    "tags": ["Sócios"],
                    "summary": "Inscrever sócio (→ Sócios-Service, dispara a Saga)",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["nome", "email", "data_nascimento", "plano"],
                            "properties": {
                                "nome": {"type": "string", "example": "Sofia Mendes"},
                                "email": {"type": "string", "example": "sofia@gym.pt"},
                                "data_nascimento": {"type": "string", "example": "1998-02-10"},
                                "plano": {"type": "string", "enum": ["BASICO", "STANDARD", "PREMIUM"]},
                            },
                        }}},
                    },
                    "responses": {"201": {"description": "Criado"}, "409": {"description": "Email já existe"}},
                },
            },
            "/socios/{socio_id}": {
                "get": {
                    "tags": ["Sócios"], "summary": "Obter sócio (→ Sócios-Service)",
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Não encontrado"}},
                }
            },
            "/socios/{socio_id}/plano": {
                "patch": {
                    "tags": ["Sócios"], "summary": "Atualizar plano de mensalidade (→ Sócios-Service)",
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object", "required": ["plano"],
                            "properties": {"plano": {"type": "string", "enum": ["BASICO", "STANDARD", "PREMIUM"]}},
                        }}},
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/socios/{socio_id}/suspender": {
                "post": {
                    "tags": ["Sócios"], "summary": "Suspender sócio (→ Sócios-Service)",
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/socios/{socio_id}/acompanhamento": {
                "get": {
                    "tags": ["Sócios"], "summary": "Estado de compensação da Saga (→ Sócios-Service)",
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/socios/{socio_id}/planos-treino": {
                "get": {
                    "tags": ["Planos de Treino"], "summary": "Listar planos de treino (→ Treinos-Service)",
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "tags": ["Planos de Treino"],
                    "summary": "Criar plano de treino (→ Treinos-Service, valida via gRPC)",
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["nome", "nivel", "exercicios"],
                            "properties": {
                                "nome": {"type": "string", "example": "Plano Hipertrofia"},
                                "nivel": {"type": "string", "enum": ["INICIANTE", "INTERMEDIO", "AVANCADO"]},
                                "exercicios": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "nome": {"type": "string"},
                                            "series": {"type": "integer"},
                                            "repeticoes": {"type": "integer"},
                                            "descanso_segundos": {"type": "integer"},
                                            "tipo": {"type": "string", "enum": ["FORCA", "CARDIO", "FLEXIBILIDADE", "FUNCIONAL"]},
                                        },
                                    },
                                },
                            },
                        }}},
                    },
                    "responses": {
                        "201": {"description": "Criado"},
                        "422": {"description": "Sócio inválido"},
                        "503": {"description": "Circuito aberto — Sócios-Service indisponível"},
                    },
                },
            },
            "/planos-treino/{plano_id}": {
                "get": {
                    "tags": ["Planos de Treino"], "summary": "Obter plano por ID (→ Treinos-Service)",
                    "parameters": [{"name": "plano_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Não encontrado"}},
                }
            },
            "/socios/{socio_id}/completo": {
                "get": {
                    "tags": ["Agregação"],
                    "summary": "Visão combinada: sócio + planos de treino",
                    "description": "Demonstra agregação no Gateway: 2 chamadas internas, 1 resposta.",
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    })


def _proxy(method, base_url, path, **kwargs):
    url = f"{base_url}{path}"
    logger.info("➡️  [GATEWAY] %s %s | correlation_id=%s", method, url, g.correlation_id)
    try:
        resp = requests.request(
            method, url, headers=_headers_propagados(), timeout=10, **kwargs
        )
        return resp.content, resp.status_code, {"Content-Type": "application/json"}
    except requests.exceptions.ConnectionError:
        logger.error("🔴 [GATEWAY] Serviço indisponível | url=%s | correlation_id=%s", url, g.correlation_id)
        return (
            jsonify({
                "sucesso": False,
                "erro": f"Serviço indisponível: {base_url}",
                "correlation_id": g.correlation_id,
            }).get_data(),
            503,
            {"Content-Type": "application/json"},
        )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servico": "api-gateway", "correlation_id": g.correlation_id})


# ── Roteamento: Sócios-Service ────────────────────────────────────────────────
@app.route("/socios", methods=["GET", "POST"])
def socios():
    kwargs = {"json": request.get_json(force=True, silent=True)} if request.method == "POST" else {}
    return _proxy(request.method, SOCIOS_SERVICE_URL, "/socios", **kwargs)


@app.route("/socios/<socio_id>", methods=["GET"])
def obter_socio(socio_id):
    return _proxy("GET", SOCIOS_SERVICE_URL, f"/socios/{socio_id}")


@app.route("/socios/<socio_id>/plano", methods=["PATCH"])
def atualizar_plano(socio_id):
    return _proxy("PATCH", SOCIOS_SERVICE_URL, f"/socios/{socio_id}/plano", json=request.get_json(force=True))


@app.route("/socios/<socio_id>/suspender", methods=["POST"])
def suspender_socio(socio_id):
    return _proxy("POST", SOCIOS_SERVICE_URL, f"/socios/{socio_id}/suspender")


@app.route("/socios/<socio_id>/acompanhamento", methods=["GET"])
def acompanhamento(socio_id):
    return _proxy("GET", SOCIOS_SERVICE_URL, f"/socios/{socio_id}/acompanhamento")


# ── Roteamento: Treinos-Service ───────────────────────────────────────────────
@app.route("/socios/<socio_id>/planos-treino", methods=["GET", "POST"])
def planos_treino(socio_id):
    kwargs = {"json": request.get_json(force=True, silent=True)} if request.method == "POST" else {}
    return _proxy(request.method, TREINOS_SERVICE_URL, f"/socios/{socio_id}/planos-treino", **kwargs)


@app.route("/planos-treino/<plano_id>", methods=["GET"])
def obter_plano(plano_id):
    return _proxy("GET", TREINOS_SERVICE_URL, f"/planos-treino/{plano_id}")


# ── Agregação leve: visão combinada de um sócio ───────────────────────────────
@app.route("/socios/<socio_id>/completo", methods=["GET"])
def socio_completo(socio_id):
    """
    Demonstra agregação no Gateway: combina dados de dois serviços
    independentes numa única resposta, propagando o mesmo correlationId
    a ambas as chamadas — útil para rastrear o pedido completo nos logs
    de ambos os serviços.
    """
    headers = _headers_propagados()
    try:
        resp_socio = requests.get(f"{SOCIOS_SERVICE_URL}/socios/{socio_id}", headers=headers, timeout=10)
        resp_planos = requests.get(
            f"{TREINOS_SERVICE_URL}/socios/{socio_id}/planos-treino", headers=headers, timeout=10
        )
    except requests.exceptions.ConnectionError as e:
        return jsonify({"sucesso": False, "erro": str(e), "correlation_id": g.correlation_id}), 503

    if resp_socio.status_code != 200:
        return resp_socio.content, resp_socio.status_code, {"Content-Type": "application/json"}

    socio_data = resp_socio.json().get("dados")
    planos_data = resp_planos.json().get("dados", []) if resp_planos.status_code == 200 else []

    return jsonify({
        "sucesso": True,
        "dados": {"socio": socio_data, "planos_treino": planos_data},
        "correlation_id": g.correlation_id,
    })


if __name__ == "__main__":
    logger.info("🚪 API Gateway a iniciar | socios=%s | treinos=%s", SOCIOS_SERVICE_URL, TREINOS_SERVICE_URL)
    app.run(debug=False, host="0.0.0.0", port=8000, use_reloader=False)
