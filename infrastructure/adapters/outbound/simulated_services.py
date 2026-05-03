"""
Adaptadores de saída: Serviços Simulados (Stubs)

Fase 1: Implementações simples que apenas fazem log.
Fase 2: Serão substituídas por clientes de fila de mensagens (RabbitMQ/Redis).
O Core nunca saberá desta troca — é o DIP a funcionar.
"""
import logging
import time
from uuid import UUID

from application.ports.output_ports import INotificacaoService, IRelatorioService

logger = logging.getLogger(__name__)


class LogNotificacaoService(INotificacaoService):
    """
    Simula envio de emails via log estruturado.
    Fase 2: substituído por publicação de evento numa queue.
    """

    def enviar_boas_vindas(self, email: str, nome: str) -> None:
        logger.info(
            "📧 [NOTIFICAÇÃO] Boas-vindas enviadas",
            extra={"destinatario": email, "nome": nome, "tipo": "boas_vindas"},
        )
        print(f"  [EMAIL SIMULADO] Boas-vindas para {nome} <{email}>")

    def notificar_plano_criado(self, email: str, nome_plano: str) -> None:
        logger.info(
            "📧 [NOTIFICAÇÃO] Plano criado notificado",
            extra={"destinatario": email, "plano": nome_plano, "tipo": "plano_criado"},
        )
        print(f"  [EMAIL SIMULADO] Plano '{nome_plano}' criado — notificação para {email}")


class SimuladoRelatorioService(IRelatorioService):
    """
    Simula geração de relatório.
    
    NOTA PARA FASE 2:
    Este processo leva 2 segundos (simulado). Num sistema real, geraria PDF,
    consultaria histórico de treinos, calcularia métricas, etc.
    É exatamente por isso que na Fase 2 passará para um Worker assíncrono —
    não faz sentido bloquear o pedido HTTP durante 2 segundos.
    """

    def gerar_relatorio_socio(self, socio_id: UUID) -> str:
        logger.warning(
            "⚠️  [RELATORIO] Processo pesado a correr de forma SÍNCRONA. "
            "Fase 2 migrará para Web-Queue-Worker para não bloquear.",
            extra={"socio_id": str(socio_id)},
        )
        # Simular processo demorado — justifica Web-Queue-Worker na Fase 2
        time.sleep(2)
        caminho = f"relatorios/socio_{socio_id}.pdf"
        logger.info("✅ [RELATORIO] Relatório simulado gerado: %s", caminho)
        return caminho
