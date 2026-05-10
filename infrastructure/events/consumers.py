"""
Consumidores de Eventos — Event-Driven Architecture.

Múltiplos consumidores independentes que reagem ao mesmo evento.
Cada consumidor tem responsabilidade única e não conhece os outros.

Eventos → Consumidores:
  socio.inscrito     → [AuditoriaConsumer, EstatisticasConsumer]
  socio.suspenso     → [AuditoriaConsumer]
  treino.plano_criado → [EstatisticasConsumer]
  relatorio.concluido → [NotificacaoConsumer, AuditoriaConsumer]
  relatorio.falhou    → [AlertaConsumer, AuditoriaConsumer]

Nota: os consumidores são desacoplados da infraestrutura (DIP).
A falha de um consumidor não afeta os outros (garantido pelo BusEventos).
"""
import logging
from infrastructure.events.event_bus import Evento

logger = logging.getLogger(__name__)


class AuditoriaConsumer:
    """
    Regista todos os eventos relevantes para fins de auditoria.
    Na Fase 3 escreveria para base de dados de auditoria.
    """

    def on_socio_inscrito(self, evento: Evento) -> None:
        logger.info(
            "📋 [AUDITORIA] Novo sócio inscrito | socio_id=%s | nome=%s | correlation_id=%s",
            evento.payload.get("socio_id"),
            evento.payload.get("nome"),
            evento.correlation_id,
        )

    def on_socio_suspenso(self, evento: Evento) -> None:
        logger.warning(
            "📋 [AUDITORIA] Sócio suspenso | socio_id=%s | correlation_id=%s",
            evento.payload.get("socio_id"),
            evento.correlation_id,
        )

    def on_relatorio_concluido(self, evento: Evento) -> None:
        logger.info(
            "📋 [AUDITORIA] Relatório concluído | socio_id=%s | caminho=%s | correlation_id=%s",
            evento.payload.get("socio_id"),
            evento.payload.get("caminho"),
            evento.correlation_id,
        )

    def on_relatorio_falhou(self, evento: Evento) -> None:
        logger.error(
            "📋 [AUDITORIA] Relatório falhou | socio_id=%s | erro=%s | tentativa=%s | correlation_id=%s",
            evento.payload.get("socio_id"),
            evento.payload.get("erro"),
            evento.payload.get("tentativa"),
            evento.correlation_id,
        )


class EstatisticasConsumer:
    """
    Mantém contadores de estatísticas do sistema em memória.
    Na Fase 3 escreveria para um serviço de métricas (Prometheus/InfluxDB).
    """

    def __init__(self):
        self._socios_inscritos = 0
        self._planos_criados = 0
        self._relatorios_gerados = 0

    def on_socio_inscrito(self, evento: Evento) -> None:
        self._socios_inscritos += 1
        logger.info(
            "📊 [ESTATISTICAS] Sócios inscritos: %d | correlation_id=%s",
            self._socios_inscritos, evento.correlation_id
        )

    def on_plano_criado(self, evento: Evento) -> None:
        self._planos_criados += 1
        logger.info(
            "📊 [ESTATISTICAS] Planos de treino criados: %d | correlation_id=%s",
            self._planos_criados, evento.correlation_id
        )

    def on_relatorio_concluido(self, evento: Evento) -> None:
        self._relatorios_gerados += 1
        logger.info(
            "📊 [ESTATISTICAS] Relatórios gerados: %d | correlation_id=%s",
            self._relatorios_gerados, evento.correlation_id
        )

    def estatisticas(self) -> dict:
        return {
            "socios_inscritos": self._socios_inscritos,
            "planos_criados": self._planos_criados,
            "relatorios_gerados": self._relatorios_gerados,
        }


class AlertaConsumer:
    """
    Emite alertas quando operações críticas falham.
    Na Fase 3 enviaria para Slack, PagerDuty, etc.
    """

    def on_relatorio_falhou(self, evento: Evento) -> None:
        tentativa = evento.payload.get("tentativa", 0)
        logger.error(
            "🚨 [ALERTA] Falha na geração de relatório! "
            "socio_id=%s | tentativa=%d | erro=%s | "
            "correlation_id=%s — Rastrear logs com este ID para diagnóstico completo.",
            evento.payload.get("socio_id"),
            tentativa,
            evento.payload.get("erro"),
            evento.correlation_id,
        )
        # Após 3 falhas, alerta crítico
        if tentativa >= 2:
            logger.critical(
                "🆘 [ALERTA CRÍTICO] Relatório excedeu limite de retries! "
                "socio_id=%s | correlation_id=%s",
                evento.payload.get("socio_id"),
                evento.correlation_id,
            )
