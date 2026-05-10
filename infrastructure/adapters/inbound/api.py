"""
Adaptador de entrada: API REST com Flask — Fase 2.

Novidades em relação à Fase 1:
  - Middleware de correlationId (rastreio de pedidos ponta-a-ponta)
  - POST /relatorio → resposta imediata com job_id (antes bloqueava 2s)
  - GET /relatorio/{job_id}/status → consultar estado do job
  - GET /sistema/stats → observabilidade do sistema assíncrono
  - GET /sistema/eventos → histórico de eventos
  - POST /admin/demo-falha → injetar falha para demonstração
"""
import logging
import uuid
from datetime import date, datetime
from flask import Flask, jsonify, request, redirect, g
from flask_swagger_ui import get_swaggerui_blueprint

from infrastructure.config.container import container
from application.dtos.dtos import InscreverSocioDTO, CriarPlanoTreinoDTO, ExercicioDTO
from domain.exceptions.dominio_exceptions import (
    GymCoreException,
    SocioNaoEncontradoException,
    SocioJaExisteException,
    PlanoTreinoNaoEncontradoException,
)

# ── Logging estruturado enriquecido ───────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | cid=%(correlation_id)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)

class CorrelationIdFilter(logging.Filter):
    """Injeta correlationId em todos os log records."""
    def filter(self, record):
        record.correlation_id = getattr(g, 'correlation_id', '-') if _has_app_context() else '-'
        return True

def _has_app_context():
    try:
        from flask import has_app_context
        return has_app_context()
    except:
        return False

# Aplicar filtro a todos os handlers
for handler in logging.root.handlers:
    handler.addFilter(CorrelationIdFilter())

logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Middleware: correlationId ─────────────────────────────────────────────────
@app.before_request
def injetar_correlation_id():
    """
    Injeta correlationId em cada pedido HTTP.
    
    Se o cliente enviar X-Correlation-ID, reutiliza (permite rastrear
    pedidos que vêm de sistemas externos).
    Caso contrário, gera um novo UUID.
    
    Este ID propaga-se pelos logs, eventos e mensagens de fila,
    permitindo rastrear um pedido de ponta-a-ponta mesmo através de
    workers assíncronos.
    """
    cid = request.headers.get('X-Correlation-ID', str(uuid.uuid4()))
    g.correlation_id = cid

@app.after_request
def adicionar_correlation_header(response):
    """Devolve o correlationId na resposta para o cliente rastrear."""
    response.headers['X-Correlation-ID'] = getattr(g, 'correlation_id', '-')
    return response

# ── Swagger UI ────────────────────────────────────────────────────────────────
SWAGGER_URL = "/docs"
API_URL = "/swagger.json"
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL, API_URL,
    config={"app_name": "GymCore API — Fase 2: Assíncrono + Event-Driven"},
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
            "title": "GymCore API — Fase 2",
            "version": "2.0.0",
            "description": "Sistema de Gestão de Ginásio — Fase 2: Assincronismo, Event-Driven, Observabilidade"
        },
        "paths": {
            "/health": {"get": {"summary": "Health check", "tags": ["Sistema"], "responses": {"200": {"description": "OK"}}}},
            "/sistema/stats": {"get": {"summary": "Estatísticas do sistema (fila, eventos, métricas)", "tags": ["Observabilidade"], "responses": {"200": {"description": "Estatísticas"}}}},
            "/sistema/eventos": {"get": {"summary": "Histórico de eventos do bus", "tags": ["Observabilidade"], "responses": {"200": {"description": "Eventos"}}}},
            "/admin/demo-falha": {"post": {"summary": "Reiniciar worker com modo falha (demo)", "tags": ["Admin"], "responses": {"200": {"description": "Worker reiniciado"}}}},
            "/socios": {
                "get": {"summary": "Listar sócios", "tags": ["Sócios"], "responses": {"200": {"description": "Lista"}}},
                "post": {"summary": "Inscrever sócio", "tags": ["Sócios"], "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["nome","email","data_nascimento","plano"], "properties": {"nome": {"type": "string"}, "email": {"type": "string", "example": "rui@g.com"}, "data_nascimento": {"type": "string", "example": "1990-05-15"}, "plano": {"type": "string", "enum": ["BASICO","STANDARD","PREMIUM"]}}}}}}, "responses": {"201": {"description": "Criado"}, "409": {"description": "Já existe"}, "400": {"description": "Email inválido ou dados errados"}}}
            },
            "/socios/{socio_id}": {"get": {"summary": "Obter sócio", "tags": ["Sócios"], "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "OK"}, "404": {"description": "Não encontrado"}}}},
            "/socios/{socio_id}/suspender": {"post": {"summary": "Suspender sócio", "tags": ["Sócios"], "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "OK"}}}},
            "/socios/{socio_id}/planos-treino": {
                "get": {"summary": "Listar planos de treino", "tags": ["Planos de Treino"], "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "OK"}}},
                "post": {"summary": "Criar plano de treino", "tags": ["Planos de Treino"], "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}], "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["nome","nivel","exercicios"], "properties": {"nome": {"type": "string"}, "nivel": {"type": "string", "enum": ["INICIANTE","INTERMEDIO","AVANCADO"]}, "exercicios": {"type": "array", "items": {"type": "object"}}}}}}}, "responses": {"201": {"description": "Criado"}}}
            },
            "/socios/{socio_id}/relatorio": {
                "post": {
                    "summary": "Solicitar relatório (assíncrono — resposta imediata)",
                    "description": "Fase 2: retorna job_id imediatamente. Fase 1: bloqueava 2s.",
                    "tags": ["Relatórios"],
                    "parameters": [{"name": "socio_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"202": {"description": "Aceite — processamento em background"}}
                }
            },
            "/relatorios/{job_id}/status": {
                "get": {
                    "summary": "Consultar estado do job de relatório",
                    "tags": ["Relatórios"],
                    "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Estado do job"}}
                }
            }
        }
    })

# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

def _serialize(obj):
    if hasattr(obj, '__dict__'):
        return {k: _serialize(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj

def _ok(data, status=200):
    return jsonify({"sucesso": True, "dados": _serialize(data), "correlation_id": getattr(g, 'correlation_id', '-')}), status

def _erro(mensagem, status=400):
    return jsonify({"sucesso": False, "erro": mensagem, "correlation_id": getattr(g, 'correlation_id', '-')}), status

# ── Error Handlers ────────────────────────────────────────────────────────────
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
    logger.exception("Erro inesperado")
    return _erro("Erro interno do servidor.", 500)

# ── Rotas: Observabilidade ────────────────────────────────────────────────────
@app.route("/sistema/stats", methods=["GET"])
def sistema_stats():
    """Observabilidade: estado da fila, eventos e métricas."""
    return _ok(container.estatisticas())

@app.route("/sistema/eventos", methods=["GET"])
def sistema_eventos():
    """Histórico de eventos do bus — útil para rastreio e debug."""
    tipo = request.args.get("tipo")
    eventos = container.bus_eventos.historico(tipo=tipo)
    return _ok([{
        "tipo": e.tipo,
        "correlation_id": e.correlation_id,
        "timestamp": e.timestamp,
        "origem": e.origem,
        "payload": e.payload,
    } for e in eventos[-50:]])  # últimos 50

@app.route("/admin/demo-falha", methods=["POST"])
def demo_falha():
    """
    Endpoint de demonstração: reinicia o worker com modo falha activo.
    Útil para demonstrar retry, correlationId e dead-letter em ambiente de avaliação.
    """
    logger.warning("⚠️  [ADMIN] Modo demo-falha activado | correlation_id=%s", g.correlation_id)
    container._worker.parar()
    from infrastructure.workers.relatorio_worker import RelatorioWorker
    container._worker = RelatorioWorker(
        fila=container.fila_relatorios,
        bus_eventos=container.bus_eventos,
        simular_falha=True,
        falhas_consecutivas=2,
    )
    container._worker.iniciar()
    return _ok({"mensagem": "Worker reiniciado com modo falha. Próximos 2 pedidos de relatório vão falhar e fazer retry."})

# ── Rotas: Sócios ─────────────────────────────────────────────────────────────
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
    
    # Publicar evento de negócio
    from infrastructure.events.event_bus import Evento, TipoEvento
    container.bus_eventos.publicar(
        Evento(
            tipo=TipoEvento.SOCIO_INSCRITO,
            payload={"socio_id": str(resultado.id), "nome": resultado.nome, "email": resultado.email},
            origem="API",
        ),
        correlation_id=g.correlation_id
    )
    
    logger.info("Sócio inscrito via API | id=%s", resultado.id)
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
    resultado = container.suspender_socio.executar(uuid.UUID(socio_id))
    from infrastructure.events.event_bus import Evento, TipoEvento
    container.bus_eventos.publicar(
        Evento(tipo=TipoEvento.SOCIO_SUSPENSO, payload={"socio_id": socio_id}, origem="API"),
        correlation_id=g.correlation_id
    )
    return _ok(resultado)

# ── Rotas: Planos de Treino ───────────────────────────────────────────────────
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
    resultado = container.criar_plano.executar(dto)
    from infrastructure.events.event_bus import Evento, TipoEvento
    container.bus_eventos.publicar(
        Evento(tipo=TipoEvento.PLANO_CRIADO, payload={"socio_id": socio_id, "plano": body["nome"]}, origem="API"),
        correlation_id=g.correlation_id
    )
    return _ok(resultado, 201)

@app.route("/socios/<socio_id>/planos-treino", methods=["GET"])
def listar_planos_treino(socio_id):
    return _ok(container.listar_planos_socio.executar(uuid.UUID(socio_id)))

@app.route("/planos-treino/<plano_id>", methods=["GET"])
def obter_plano_treino(plano_id):
    return _ok(container.obter_plano.executar(uuid.UUID(plano_id)))

# ── Rotas: Relatórios (Assíncronos) ──────────────────────────────────────────
@app.route("/socios/<socio_id>/relatorio", methods=["POST"])
def solicitar_relatorio(socio_id):
    """
    Fase 2: pedido assíncrono.
    Retorna job_id em < 10ms (antes bloqueava 2s).
    O worker processa em background.
    """
    cid = g.correlation_id
    logger.info(
        "📋 Pedido de relatório recebido | socio_id=%s | correlation_id=%s "
        "[ASSÍNCRONO — a enfileirar para worker]",
        socio_id, cid
    )
    
    # Usar o QueueRelatorioService — mas precisa de passar o correlation_id
    # Como o use case não tem correlation_id, chamamos o serviço directamente aqui
    from uuid import UUID as _UUID
    socio = container._socio_repo.obter_por_id(_UUID(socio_id))
    if not socio:
        from domain.exceptions.dominio_exceptions import SocioNaoEncontradoException
        raise SocioNaoEncontradoException(socio_id)
    
    job_id = container._relatorio.gerar_relatorio_socio(_UUID(socio_id), correlation_id=cid)
    
    return jsonify({
        "sucesso": True,
        "dados": {
            "job_id": job_id,
            "estado": "enfileirado",
            "mensagem": "Relatório em processamento. Consulte /relatorios/{job_id}/status",
            "correlation_id": cid,
        },
        "correlation_id": cid,
    }), 202

@app.route("/relatorios/<job_id>/status", methods=["GET"])
def estado_relatorio(job_id):
    """
    Consultar estado de um job de relatório.
    Verifica o histórico de eventos para determinar o estado.
    """
    eventos_concluidos = container.bus_eventos.historico(tipo="relatorio.concluido")
    eventos_falhados = container.bus_eventos.historico(tipo="relatorio.falhou")
    
    for e in reversed(eventos_concluidos):
        if e.payload.get("job_id") == job_id or True:  # simplificado — em prod usar job_id
            pass
    
    # Estado simplificado baseado no histórico
    stats = container.fila_relatorios.estatisticas()
    return _ok({
        "job_id": job_id,
        "fila_pendentes": stats["pendentes"],
        "total_processados": stats["total_processadas"],
        "total_erros": stats["total_erros"],
        "nota": "Em produção, o job_id seria rastreado numa base de dados de estado.",
    })

# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    stats = container.fila_relatorios.estatisticas()
    return jsonify({
        "status": "ok",
        "fase": "2-assincrono",
        "versao": "2.0.0",
        "fila_pendentes": stats["pendentes"],
        "correlation_id": getattr(g, 'correlation_id', '-'),
    })

if __name__ == "__main__":
    logger.info("🏋️  GymCore — Fase 2: Assíncrono + Event-Driven a iniciar...")
    logger.info("   GYMCORE_SIMULAR_FALHA=%s", __import__('os').environ.get('GYMCORE_SIMULAR_FALHA', 'false'))
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
