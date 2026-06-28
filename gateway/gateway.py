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
