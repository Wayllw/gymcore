"""
Consumidor de eventos via Redis Streams — lado Treinos-Service.

Escuta o stream "stream:socios" à procura do evento `socio.inscrito`,
publicado pelo Sócios-Service após uma inscrição bem-sucedida.

Ao receber este evento, desencadeia o segundo passo da Saga "Inscrição
Completa": tentar criar um plano de treino inicial automático
(CriarPlanoInicialUseCase). É este o ponto da Saga onde a comunicação
deixa de ser síncrona (gRPC) e passa a ser assíncrona (evento) — a
inscrição do sócio já está confirmada e persistida antes deste passo
correr, por isso não pode haver rollback da inscrição; só compensação.
"""
import json
import logging
import threading
import time
from typing import Callable
from uuid import UUID

import redis

logger = logging.getLogger(__name__)


class SociosEventConsumer:

    GROUP_NAME = "treinos-service-group"
    CONSUMER_NAME = "treinos-service-consumer-1"

    def __init__(
        self,
        redis_client: redis.Redis,
        on_socio_inscrito: Callable[[UUID, str], None],
        stream_name: str = "stream:socios",
    ):
        self._redis = redis_client
        self._stream = stream_name
        self._handler = on_socio_inscrito
        self._ativo = False
        self._thread = None
        self._garantir_grupo()

    def _garantir_grupo(self) -> None:
        try:
            self._redis.xgroup_create(self._stream, self.GROUP_NAME, id="0", mkstream=True)
            logger.info("Consumer group '%s' criado em '%s'", self.GROUP_NAME, self._stream)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def iniciar(self) -> None:
        self._ativo = True
        self._thread = threading.Thread(target=self._loop, name="SociosEventConsumer", daemon=True)
        self._thread.start()
        logger.info("🚀 [CONSUMER] SociosEventConsumer iniciado | stream=%s", self._stream)

    def parar(self) -> None:
        self._ativo = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("🛑 [CONSUMER] SociosEventConsumer parado.")

    def _loop(self) -> None:
        while self._ativo:
            try:
                resultados = self._redis.xreadgroup(
                    self.GROUP_NAME, self.CONSUMER_NAME,
                    {self._stream: ">"}, count=10, block=1000,
                )
            except redis.exceptions.ConnectionError:
                time.sleep(1)
                continue

            if not resultados:
                continue

            for _stream_name, mensagens in resultados:
                for message_id, campos in mensagens:
                    self._processar(message_id, campos)

    def _processar(self, message_id: str, campos: dict) -> None:
        tipo = campos.get("tipo", "")
        correlation_id = campos.get("correlation_id", "-")

        if tipo == "socio.inscrito":
            payload = json.loads(campos.get("payload", "{}"))
            socio_id_str = payload.get("socio_id")
            logger.info(
                "📥 [CONSUMER] socio.inscrito recebido | socio_id=%s | correlation_id=%s "
                "[SAGA: a tentar criar plano inicial]",
                socio_id_str, correlation_id,
            )
            try:
                self._handler(UUID(socio_id_str), correlation_id)
            except Exception as e:
                logger.error(
                    "❌ [CONSUMER] Erro ao processar socio.inscrito | erro=%s | correlation_id=%s",
                    str(e), correlation_id,
                )

        self._redis.xack(self._stream, self.GROUP_NAME, message_id)
