"""
Adaptador de saída: Publicador de eventos via Redis Streams — Treinos-Service.

Implementa IEventPublisher. Publica no stream "stream:treinos", consumido
pelo Sócios-Service (ação de compensação da Saga).
"""
import json
import logging
from datetime import datetime, timezone

import redis

from application.ports.output_ports import IEventPublisher

logger = logging.getLogger(__name__)


class RedisStreamEventPublisher(IEventPublisher):

    def __init__(self, redis_client: redis.Redis, stream_name: str = "stream:treinos"):
        self._redis = redis_client
        self._stream = stream_name

    def publicar(self, tipo_evento: str, payload: dict, correlation_id: str) -> None:
        mensagem = {
            "tipo": tipo_evento,
            "payload": json.dumps(payload),
            "correlation_id": correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "origem": "treinos-service",
        }
        message_id = self._redis.xadd(self._stream, mensagem)
        logger.info(
            "📤 [REDIS-STREAM:%s] Evento publicado | tipo=%s | id=%s | correlation_id=%s",
            self._stream, tipo_evento, message_id, correlation_id,
        )
