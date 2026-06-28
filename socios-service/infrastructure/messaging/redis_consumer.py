"""
Consumidor de eventos via Redis Streams — lado Sócios-Service.

Escuta o stream "stream:treinos" à procura do evento `plano_inicial.falhou`,
publicado pelo Treinos-Service quando a Saga "Inscrição Completa" não
consegue criar o plano de treino inicial automático.

Esta é a ação de compensação da Saga coreografada: este serviço reage
de forma autónoma à falha do outro, sem qualquer transação distribuída.

Corre numa thread de background, em consumer group dedicado, o que
permite reiniciar o serviço sem perder mensagens não confirmadas (ACK).
"""
import json
import logging
import threading
import time
from typing import Callable

import redis

logger = logging.getLogger(__name__)


class TreinosEventConsumer:
    """
    Consome o stream Redis "stream:treinos" via consumer group.
    Aplica a ação de compensação quando recebe plano_inicial.falhou.
    """

    GROUP_NAME = "socios-service-group"
    CONSUMER_NAME = "socios-service-consumer-1"

    def __init__(
        self,
        redis_client: redis.Redis,
        on_plano_inicial_falhou: Callable[[str, str, str], None],
        stream_name: str = "stream:treinos",
    ):
        self._redis = redis_client
        self._stream = stream_name
        self._handler_falha = on_plano_inicial_falhou
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
            # Grupo já existe — normal em reinícios

    def iniciar(self) -> None:
        self._ativo = True
        self._thread = threading.Thread(target=self._loop, name="TreinosEventConsumer", daemon=True)
        self._thread.start()
        logger.info("🚀 [CONSUMER] TreinosEventConsumer iniciado | stream=%s", self._stream)

    def parar(self) -> None:
        self._ativo = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("🛑 [CONSUMER] TreinosEventConsumer parado.")

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

        if tipo == "plano_inicial.falhou":
            payload = json.loads(campos.get("payload", "{}"))
            socio_id = payload.get("socio_id")
            motivo = payload.get("motivo", "desconhecido")
            logger.warning(
                "📥 [CONSUMER] plano_inicial.falhou recebido | socio_id=%s | "
                "motivo=%s | correlation_id=%s",
                socio_id, motivo, correlation_id,
            )
            try:
                self._handler_falha(socio_id, motivo, correlation_id)
            except Exception as e:
                logger.error(
                    "❌ [CONSUMER] Erro ao aplicar compensação | erro=%s | correlation_id=%s",
                    str(e), correlation_id,
                )

        # ACK sempre — mesmo eventos não relevantes, para não bloquear o stream
        self._redis.xack(self._stream, self.GROUP_NAME, message_id)
