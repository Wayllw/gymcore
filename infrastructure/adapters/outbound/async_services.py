"""
Adaptadores de saída — Fase 2.

QueueRelatorioService: substitui SimuladoRelatorioService da Fase 1.
O Core (IRelatorioService) não mudou nenhuma linha — DIP em ação.

Diferença crucial:
  Fase 1: gerar_relatorio_socio() → bloqueava 2s → retornava caminho
  Fase 2: gerar_relatorio_socio() → publica mensagem na fila → retorna job_id imediatamente
          Worker processa em background → publica evento de conclusão
"""
import logging
import uuid
from uuid import UUID

from application.ports.output_ports import IRelatorioService, INotificacaoService
from infrastructure.messaging.queue import FilaMensagens, Mensagem
from infrastructure.events.event_bus import BusEventos, Evento, TipoEvento

logger = logging.getLogger(__name__)


class QueueRelatorioService(IRelatorioService):
    """
    Implementação assíncrona do IRelatorioService usando fila de mensagens.
    
    O Core chama gerar_relatorio_socio() e recebe um job_id imediatamente.
    O processamento pesado acontece no RelatorioWorker em background.
    
    Esta é a única mudança de infraestrutura em relação à Fase 1 — o Core
    continua a chamar a mesma interface IRelatorioService.
    """

    def __init__(self, fila: FilaMensagens, bus_eventos: BusEventos):
        self._fila = fila
        self._bus = bus_eventos

    def gerar_relatorio_socio(self, socio_id: UUID, correlation_id: str = None) -> str:
        """
        Publica pedido de geração na fila e retorna job_id imediatamente.
        Tempo de resposta: < 5ms (vs 2000ms na Fase 1).
        """
        job_id = str(uuid.uuid4())
        cid = correlation_id or str(uuid.uuid4())

        mensagem = Mensagem(
            tipo="gerar_relatorio",
            payload={
                "socio_id": str(socio_id),
                "job_id": job_id,
            },
            correlation_id=cid,
        )

        self._fila.publicar(mensagem)

        # Publicar evento de que o relatório foi solicitado
        self._bus.publicar(
            Evento(
                tipo=TipoEvento.RELATORIO_SOLICITADO,
                payload={
                    "socio_id": str(socio_id),
                    "job_id": job_id,
                },
                origem="QueueRelatorioService",
            ),
            correlation_id=cid
        )

        logger.info(
            "⚡ [RELATORIO] Pedido enfileirado | job_id=%s | socio_id=%s | "
            "correlation_id=%s | [ASSÍNCRONO — resposta imediata]",
            job_id, socio_id, cid
        )

        return job_id  # Retorna imediatamente — processamento em background


class EventNotificacaoService(INotificacaoService):
    """
    Serviço de notificação orientado a eventos.
    Em vez de notificar diretamente, publica eventos que outros consumidores processam.
    
    Mantém compatibilidade com a interface INotificacaoService do Core.
    """

    def __init__(self, bus_eventos: BusEventos):
        self._bus = bus_eventos

    def enviar_boas_vindas(self, email: str, nome: str, correlation_id: str = None) -> None:
        logger.info(
            "📧 [NOTIFICACAO] Boas-vindas (via evento) | email=%s | nome=%s",
            email, nome
        )
        # Na Fase 3: publicaria evento "notificacao.email_solicitado"
        # que um serviço de Email processaria de forma independente
        print(f"  [EMAIL SIMULADO] Boas-vindas para {nome} <{email}>")

    def notificar_plano_criado(self, email: str, nome_plano: str, correlation_id: str = None) -> None:
        logger.info(
            "📧 [NOTIFICACAO] Plano criado (via evento) | email=%s | plano=%s",
            email, nome_plano
        )
        print(f"  [EMAIL SIMULADO] Plano '{nome_plano}' criado — notificação para {email}")
