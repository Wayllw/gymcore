"""
Container de Injeção de Dependências — Sócios-Service.

Composition Root: único sítio onde se decide quais implementações concretas
satisfazem os ports definidos no Core.
"""
import os
import redis

from infrastructure.adapters.outbound.sqlite_repository import SqliteSocioRepository
from infrastructure.messaging.redis_publisher import RedisStreamEventPublisher
from infrastructure.messaging.redis_consumer import TreinosEventConsumer
from application.use_cases.socios_use_cases import (
    InscreverSocioUseCase,
    ObterSocioUseCase,
    ListarSociosUseCase,
    AtualizarPlanoSocioUseCase,
    SuspenderSocioUseCase,
    MarcarParaAcompanhamentoUseCase,
)


class Container:

    def __init__(self):
        redis_host = os.environ.get("REDIS_HOST", "localhost")
        redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        bd_caminho = os.environ.get("SOCIOS_DB_PATH", "dados/socios.db")

        self.redis_client = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True
        )

        # ── Repositório (SQLite — Database-per-Service) ────────────────
        self.socio_repo = SqliteSocioRepository(bd_caminho)

        # ── Publicador de eventos (Redis Streams) ──────────────────────
        self.event_publisher = RedisStreamEventPublisher(self.redis_client, "stream:socios")

        # ── Use Cases ────────────────────────────────────────────────────
        self.inscrever_socio = InscreverSocioUseCase(self.socio_repo, self.event_publisher)
        self.obter_socio = ObterSocioUseCase(self.socio_repo)
        self.listar_socios = ListarSociosUseCase(self.socio_repo)
        self.atualizar_plano = AtualizarPlanoSocioUseCase(self.socio_repo)
        self.suspender_socio = SuspenderSocioUseCase(self.socio_repo)
        self.marcar_acompanhamento = MarcarParaAcompanhamentoUseCase(self.socio_repo)

        # ── Consumer de eventos do Treinos-Service (compensação da Saga) ─
        self.treinos_consumer = TreinosEventConsumer(
            self.redis_client,
            on_plano_inicial_falhou=self._on_plano_inicial_falhou,
        )

    def _on_plano_inicial_falhou(self, socio_id: str, motivo: str, correlation_id: str) -> None:
        from uuid import UUID
        self.marcar_acompanhamento.executar(UUID(socio_id), motivo, correlation_id)

    def iniciar_background(self) -> None:
        self.treinos_consumer.iniciar()

    def parar(self) -> None:
        self.treinos_consumer.parar()


container = Container()
