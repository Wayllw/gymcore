"""
Bus de Eventos — Event-Driven Architecture.

Permite que múltiplos consumidores independentes reajam ao mesmo evento,
sem acoplamento entre eles. Os publicadores não conhecem os consumidores.

Padrão: Observer/Pub-Sub com suporte a correlationId para rastreabilidade.

Exemplo de fluxo:
  SocioInscritoEvent → [NotificacaoConsumer, RelatorioConsumer, AuditoriaConsumer]
  Cada consumidor processa de forma independente.
"""
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Evento:
    """Evento de domínio com metadados de rastreio."""
    tipo: str
    payload: Dict[str, Any]
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    origem: str = "gymcore"

    def __str__(self):
        return f"Evento({self.tipo}, correlation_id={self.correlation_id})"


# Tipos de eventos do domínio GymCore
class TipoEvento:
    SOCIO_INSCRITO = "socio.inscrito"
    SOCIO_SUSPENSO = "socio.suspenso"
    PLANO_CRIADO = "treino.plano_criado"
    RELATORIO_SOLICITADO = "relatorio.solicitado"
    RELATORIO_CONCLUIDO = "relatorio.concluido"
    RELATORIO_FALHOU = "relatorio.falhou"


HandlerEvento = Callable[[Evento], None]


class BusEventos:
    """
    Bus de eventos thread-safe.
    
    Permite registar múltiplos handlers para o mesmo tipo de evento.
    Cada handler é independente — falha de um não afeta os outros.
    
    Na Fase 3 seria substituído por Kafka, RabbitMQ Exchanges, ou similar.
    """

    def __init__(self):
        self._handlers: Dict[str, List[HandlerEvento]] = {}
        self._lock = threading.Lock()
        self._historico: List[Evento] = []
        self._max_historico = 1000

    def subscrever(self, tipo_evento: str, handler: HandlerEvento) -> None:
        """Regista um handler para um tipo de evento."""
        with self._lock:
            if tipo_evento not in self._handlers:
                self._handlers[tipo_evento] = []
            self._handlers[tipo_evento].append(handler)
        logger.debug(
            "📡 [EVENTBUS] Handler registado | evento=%s | handler=%s",
            tipo_evento, handler.__name__
        )

    def publicar(self, evento: Evento, correlation_id: Optional[str] = None) -> None:
        """
        Publica um evento para todos os handlers registados.
        
        Se correlation_id for fornecido, é propagado (rastreio entre componentes).
        """
        if correlation_id:
            evento.correlation_id = correlation_id

        logger.info(
            "📢 [EVENTBUS] Evento publicado | tipo=%s | correlation_id=%s | origem=%s",
            evento.tipo, evento.correlation_id, evento.origem
        )

        # Guardar no histórico
        with self._lock:
            self._historico.append(evento)
            if len(self._historico) > self._max_historico:
                self._historico.pop(0)
            handlers = list(self._handlers.get(evento.tipo, []))

        if not handlers:
            logger.warning(
                "⚠️  [EVENTBUS] Nenhum handler para evento | tipo=%s",
                evento.tipo
            )
            return

        # Chamar cada handler de forma independente
        for handler in handlers:
            try:
                handler(evento)
                logger.debug(
                    "✅ [EVENTBUS] Handler executado | evento=%s | handler=%s | correlation_id=%s",
                    evento.tipo, handler.__name__, evento.correlation_id
                )
            except Exception as e:
                # Falha num handler não afeta os outros (isolamento)
                logger.error(
                    "❌ [EVENTBUS] Falha em handler | evento=%s | handler=%s | erro=%s | correlation_id=%s",
                    evento.tipo, handler.__name__, str(e), evento.correlation_id
                )

    def historico(self, tipo: Optional[str] = None) -> List[Evento]:
        """Devolve histórico de eventos (útil para debug/observabilidade)."""
        with self._lock:
            if tipo:
                return [e for e in self._historico if e.tipo == tipo]
            return list(self._historico)
