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
