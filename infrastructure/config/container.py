"""
Container de Injeção de Dependências.

Aqui é onde as abstrações são "ligadas" às implementações concretas.
Este é o único lugar no sistema onde o Core "encontra" a Infraestrutura.
Mudar de InMemory para PostgreSQL na Fase 3 é feito APENAS aqui.
"""
from infrastructure.adapters.outbound.in_memory_repositories import (
    InMemorySocioRepository,
    InMemoryPlanoTreinoRepository,
)
from infrastructure.adapters.outbound.simulated_services import (
    LogNotificacaoService,
    SimuladoRelatorioService,
)
from application.use_cases.socios_use_cases import (
    InscreverSocioUseCase,
    ObterSocioUseCase,
    ListarSociosUseCase,
    AtualizarPlanoSocioUseCase,
    SuspenderSocioUseCase,
)
from application.use_cases.plano_treino_use_cases import (
    CriarPlanoTreinoUseCase,
    ListarPlanosPorSocioUseCase,
    ObterPlanoTreinoUseCase,
)
from application.use_cases.relatorio_use_cases import GerarRelatorioSocioUseCase


class Container:
    """
    Container singleton que instancia e injeta dependências.
    
    Padrão: Composition Root — toda a "fiação" do DIP acontece aqui,
    não dentro das classes do Core.
    """

    def __init__(self):
        # ── Infraestrutura ─────────────────────────────────────────────
        # Fase 3: trocar por PostgresSocioRepository(connection_string=...)
        self._socio_repo = InMemorySocioRepository()
        self._plano_repo = InMemoryPlanoTreinoRepository()
        self._notificacao = LogNotificacaoService()
        self._relatorio = SimuladoRelatorioService()

        # ── Use Cases: Sócios ──────────────────────────────────────────
        self.inscrever_socio = InscreverSocioUseCase(
            self._socio_repo, self._notificacao
        )
        self.obter_socio = ObterSocioUseCase(self._socio_repo)
        self.listar_socios = ListarSociosUseCase(self._socio_repo)
        self.atualizar_plano = AtualizarPlanoSocioUseCase(self._socio_repo)
        self.suspender_socio = SuspenderSocioUseCase(self._socio_repo)

        # ── Use Cases: Planos de Treino ────────────────────────────────
        self.criar_plano = CriarPlanoTreinoUseCase(
            self._plano_repo, self._socio_repo, self._notificacao
        )
        self.listar_planos_socio = ListarPlanosPorSocioUseCase(self._plano_repo)
        self.obter_plano = ObterPlanoTreinoUseCase(self._plano_repo)

        # ── Use Cases: Relatórios ──────────────────────────────────────
        self.gerar_relatorio = GerarRelatorioSocioUseCase(
            self._socio_repo, self._relatorio
        )


# Instância global — criada uma vez, partilhada por toda a aplicação
container = Container()
