"""
Adaptador de entrada: API REST do Treinos-Service (Flask).

Porta: 8002
Comunica com o Sócios-Service via gRPC (porta 9001, com Circuit Breaker)
para validar sócios antes de criar planos de treino.
"""
import logging
import uuid
from datetime import date

from flask import Flask, jsonify, request, g

from infrastructure.config.container import container
from application.dtos.dtos import CriarPlanoTreinoDTO, ExercicioDTO
from domain.exceptions.dominio_exceptions import (
    TreinosServiceException,
    PlanoTreinoNaoEncontradoException,
    SocioInvalidoException,
    SocioValidationIndisponivelException,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | treinos-service | cid=%(correlation_id)s | %(message)s',
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


@app.errorhandler(PlanoTreinoNaoEncontradoException)
def handle_not_found(e):
    return _erro(str(e), 404)


@app.errorhandler(SocioInvalidoException)
def handle_socio_invalido(e):
    return _erro(str(e), 422)


@app.errorhandler(SocioValidationIndisponivelException)
def handle_indisponivel(e):
    # 503 Service Unavailable — sinaliza claramente que é um problema
    # de dependência externa (circuito aberto), não do pedido em si.
    return _erro(str(e), 503)


@app.errorhandler(TreinosServiceException)
def handle_domain(e):
    return _erro(str(e), 400)


@app.errorhandler(Exception)
def handle_generic(e):
    logger.exception("Erro inesperado")
    return _erro("Erro interno do servidor.", 500)


@app.route("/health", methods=["GET"])
def health():
    from infrastructure.resilience.grpc_client import socio_validation_breaker
    return jsonify({
        "status": "ok",
        "servico": "treinos-service",
        "versao": "3.0.0",
        "circuit_breaker_estado": socio_validation_breaker.current_state,
        "correlation_id": getattr(g, "correlation_id", "-"),
    })


@app.route("/socios/<socio_id>/planos-treino", methods=["POST"])
def criar_plano_treino(socio_id):
    body = request.get_json(force=True)
    exercicios = [
        ExercicioDTO(
            nome=ex["nome"], series=ex["series"], repeticoes=ex["repeticoes"],
            descanso_segundos=ex["descanso_segundos"], tipo=ex["tipo"],
        )
        for ex in body.get("exercicios", [])
    ]
    dto = CriarPlanoTreinoDTO(
        socio_id=uuid.UUID(socio_id), nome=body["nome"],
        nivel=body["nivel"], exercicios=exercicios,
    )
    resultado = container.criar_plano.executar(dto, correlation_id=g.correlation_id)
    return _ok(resultado, 201)


@app.route("/socios/<socio_id>/planos-treino", methods=["GET"])
def listar_planos_treino(socio_id):
    return _ok(container.listar_planos_socio.executar(uuid.UUID(socio_id)))


@app.route("/planos-treino/<plano_id>", methods=["GET"])
def obter_plano_treino(plano_id):
    return _ok(container.obter_plano.executar(uuid.UUID(plano_id)))


if __name__ == "__main__":
    logger.info("🏋️  Treinos-Service a iniciar...")

    # Iniciar consumer de eventos do Sócios-Service (gatilho da Saga)
    container.iniciar_background()

    app.run(debug=False, host="0.0.0.0", port=8002, use_reloader=False)
