"""
Adaptador de saída: Publicador de eventos via Redis Streams.

Implementa IEventPublisher — substitui o BusEventos em memória da Fase 2.
Agora os eventos atravessam a fronteira do processo: outro serviço
(Treinos-Service) consome estes eventos a partir de um stream Redis
partilhado, sem qualquer acoplamento de código entre os dois serviços.

Stream usado: "stream:socios"
Cada mensagem inclui: tipo, payload (JSON), correlation_id, timestamp.
"""
import json
import logging
import time
from datetime import datetime, timezone

import redis

from application.ports.output_ports import IEventPublisher

logger = logging.getLogger(__name__)


class RedisStreamEventPublisher(IEventPublisher):

    def __init__(self, redis_client: redis.Redis, stream_name: str = "stream:socios"):
        self._redis = redis_client
        self._stream = stream_name

    def publicar(self, tipo_evento: str, payload: dict, correlation_id: str) -> None:
        mensagem = {
            "tipo": tipo_evento,
            "payload": json.dumps(payload),
            "correlation_id": correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "origem": "socios-service",
        }
        message_id = self._redis.xadd(self._stream, mensagem)
        logger.info(
            "📤 [REDIS-STREAM:%s] Evento publicado | tipo=%s | id=%s | correlation_id=%s",
            self._stream, tipo_evento, message_id, correlation_id,
        )
