"""
Fila de mensagens em memória — Web-Queue-Worker pattern.

Na Fase 3, esta implementação seria substituída por RabbitMQ ou Redis Streams.
O Core nunca sabe que existe esta fila — apenas conhece a interface IRelatorioService.

Padrão: Queue (FIFO) com suporte a mensagens com correlationId para rastreio.
"""
import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class Mensagem:
    """Envelope de mensagem com metadados de rastreio."""
    tipo: str
    payload: Dict[str, Any]
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    tentativas: int = 0
    max_tentativas: int = 3

    def pode_retentar(self) -> bool:
        return self.tentativas < self.max_tentativas


class FilaMensagens:
    """
    Fila de mensagens em memória thread-safe.
    
    Simula o comportamento de um broker de mensagens (RabbitMQ/Redis).
    Thread-safe para uso com workers em background threads.
    """

    def __init__(self, nome: str = "default", maxsize: int = 100):
        self.nome = nome
        self._fila: queue.Queue = queue.Queue(maxsize=maxsize)
        self._fila_erros: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._total_publicadas = 0
        self._total_processadas = 0
        self._total_erros = 0

    def publicar(self, mensagem: Mensagem) -> None:
        """Publica uma mensagem na fila."""
        try:
            self._fila.put_nowait(mensagem)
            with self._lock:
                self._total_publicadas += 1
            logger.info(
                "📤 [QUEUE:%s] Mensagem publicada | tipo=%s | correlation_id=%s",
                self.nome, mensagem.tipo, mensagem.correlation_id
            )
        except queue.Full:
            logger.error(
                "❌ [QUEUE:%s] Fila cheia! Mensagem descartada | tipo=%s | correlation_id=%s",
                self.nome, mensagem.tipo, mensagem.correlation_id
            )
            raise RuntimeError(f"Fila '{self.nome}' está cheia.")

    def consumir(self, timeout: float = 1.0) -> Optional[Mensagem]:
        """Consome a próxima mensagem da fila. Retorna None se timeout."""
        try:
            msg = self._fila.get(timeout=timeout)
            with self._lock:
                self._total_processadas += 1
            return msg
        except queue.Empty:
            return None

    def confirmar(self) -> None:
        """Confirma que a última mensagem foi processada com sucesso."""
        self._fila.task_done()

    def rejeitar(self, mensagem: Mensagem) -> None:
        """Rejeita mensagem — vai para dead letter queue se esgotou tentativas."""
        self._fila.task_done()
        mensagem.tentativas += 1

        if mensagem.pode_retentar():
            # Re-enqueue para retry
            logger.warning(
                "🔄 [QUEUE:%s] Retry %d/%d | tipo=%s | correlation_id=%s",
                self.nome, mensagem.tentativas, mensagem.max_tentativas,
                mensagem.tipo, mensagem.correlation_id
            )
            self._fila.put(mensagem)
        else:
            # Dead Letter Queue
            logger.error(
                "💀 [QUEUE:%s] Mensagem para DLQ após %d falhas | tipo=%s | correlation_id=%s",
                self.nome, mensagem.tentativas, mensagem.tipo, mensagem.correlation_id
            )
            self._fila_erros.put(mensagem)
            with self._lock:
                self._total_erros += 1

    def estatisticas(self) -> Dict[str, Any]:
        return {
            "fila": self.nome,
            "pendentes": self._fila.qsize(),
            "dead_letter": self._fila_erros.qsize(),
            "total_publicadas": self._total_publicadas,
            "total_processadas": self._total_processadas,
            "total_erros": self._total_erros,
        }
