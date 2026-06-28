"""
Container de Injeção de Dependências — Treinos-Service.
"""
import os
import redis

from infrastructure.adapters.outbound.sqlite_repository import SqlitePlanoTreinoRepository
from infrastructure.resilience.grpc_client import GrpcSocioValidationClient
from infrastructure.messaging.redis_publisher import RedisStreamEventPublisher
from infrastructure.messaging.redis_consumer import SociosEventConsumer
from application.use_cases.plano_treino_use_cases import (
    CriarPlanoTreinoUseCase,
    ListarPlanosPorSocioUseCase,
    ObterPlanoTreinoUseCase,
    CriarPlanoInicialUseCase,
)


class Container:

    def __init__(self):
        redis_host = os.environ.get("REDIS_HOST", "localhost")
        redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        bd_caminho = os.environ.get("TREINOS_DB_PATH", "dados/treinos.db")
        socios_grpc_host = os.environ.get("SOCIOS_GRPC_HOST", "localhost")
        socios_grpc_port = int(os.environ.get("SOCIOS_GRPC_PORT", "9001"))

        self.redis_client = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True
        )

        # ── Repositório (SQLite — Database-per-Service) ────────────────
        self.plano_repo = SqlitePlanoTreinoRepository(bd_caminho)

        # ── Cliente gRPC com Circuit Breaker ────────────────────────────
        self.socio_validation = GrpcSocioValidationClient(
            host=socios_grpc_host, porta=socios_grpc_port
        )

        # ── Publicador de eventos (Redis Streams) ──────────────────────
        self.event_publisher = RedisStreamEventPublisher(self.redis_client, "stream:treinos")

        # ── Use Cases ────────────────────────────────────────────────────
        self.criar_plano = CriarPlanoTreinoUseCase(self.plano_repo, self.socio_validation)
        self.listar_planos_socio = ListarPlanosPorSocioUseCase(self.plano_repo)
        self.obter_plano = ObterPlanoTreinoUseCase(self.plano_repo)
        self.criar_plano_inicial = CriarPlanoInicialUseCase(
            self.plano_repo, self.socio_validation, self.event_publisher
        )

        # ── Consumer de eventos do Sócios-Service (gatilho da Saga) ─────
        self.socios_consumer = SociosEventConsumer(
            self.redis_client,
            on_socio_inscrito=self._on_socio_inscrito,
        )

    def _on_socio_inscrito(self, socio_id, correlation_id: str) -> None:
        self.criar_plano_inicial.executar(socio_id, correlation_id)

    def iniciar_background(self) -> None:
        self.socios_consumer.iniciar()

    def parar(self) -> None:
        self.socios_consumer.parar()


container = Container()
