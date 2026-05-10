"""
Container de Injeção de Dependências — Fase 2.

O que mudou em relação à Fase 1:
  - SimuladoRelatorioService → QueueRelatorioService (async)
  - LogNotificacaoService → EventNotificacaoService (event-driven)
  - Adicionados: FilaMensagens, BusEventos, RelatorioWorker, Consumers

O Core (use cases, domain) não mudou NENHUMA LINHA.
Apenas este ficheiro e os novos adaptadores foram alterados/criados.
Isto demonstra o DIP na prática: trocar infraestrutura sem tocar no Core.
"""
import os
from infrastructure.messaging.queue import FilaMensagens
from infrastructure.events.event_bus import BusEventos, TipoEvento
from infrastructure.events.consumers import AuditoriaConsumer, EstatisticasConsumer, AlertaConsumer
from infrastructure.workers.relatorio_worker import RelatorioWorker
from infrastructure.adapters.outbound.json_repositories import (
    JsonSocioRepository,
    JsonPlanoTreinoRepository,
)
from infrastructure.adapters.outbound.async_services import (
    QueueRelatorioService,
    EventNotificacaoService,
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
    Composition Root da Fase 2.
    Instancia e liga todos os componentes, incluindo a infraestrutura assíncrona.
    """

    def __init__(self, simular_falha: bool = False):
        # ── Infraestrutura Assíncrona (NOVO na Fase 2) ─────────────────
        self.fila_relatorios = FilaMensagens(nome="relatorios")
        self.bus_eventos = BusEventos()

        # ── Consumidores de Eventos (NOVO na Fase 2) ───────────────────
        self._auditoria = AuditoriaConsumer()
        self._estatisticas = EstatisticasConsumer()
        self._alerta = AlertaConsumer()

        # Subscrever consumidores aos eventos relevantes
        self.bus_eventos.subscrever(TipoEvento.SOCIO_INSCRITO, self._auditoria.on_socio_inscrito)
        self.bus_eventos.subscrever(TipoEvento.SOCIO_INSCRITO, self._estatisticas.on_socio_inscrito)
        self.bus_eventos.subscrever(TipoEvento.SOCIO_SUSPENSO, self._auditoria.on_socio_suspenso)
        self.bus_eventos.subscrever(TipoEvento.PLANO_CRIADO, self._estatisticas.on_plano_criado)
        self.bus_eventos.subscrever(TipoEvento.RELATORIO_CONCLUIDO, self._auditoria.on_relatorio_concluido)
        self.bus_eventos.subscrever(TipoEvento.RELATORIO_CONCLUIDO, self._estatisticas.on_relatorio_concluido)
        self.bus_eventos.subscrever(TipoEvento.RELATORIO_FALHOU, self._auditoria.on_relatorio_falhou)
        self.bus_eventos.subscrever(TipoEvento.RELATORIO_FALHOU, self._alerta.on_relatorio_falhou)

        # ── Worker (NOVO na Fase 2) ────────────────────────────────────
        self._worker = RelatorioWorker(
            fila=self.fila_relatorios,
            bus_eventos=self.bus_eventos,
            simular_falha=simular_falha,
            falhas_consecutivas=2,
        )
        self._worker.iniciar()

        # ── Repositórios (iguais à Fase 1) ────────────────────────────
        self._socio_repo = JsonSocioRepository("dados/socios.json")
        self._plano_repo = JsonPlanoTreinoRepository("dados/planos.json")

        # ── Serviços (substituídos — DIP em ação) ─────────────────────
        self._notificacao = EventNotificacaoService(self.bus_eventos)
        self._relatorio = QueueRelatorioService(self.fila_relatorios, self.bus_eventos)

        # ── Use Cases (INALTERADOS em relação à Fase 1) ───────────────
        self.inscrever_socio = InscreverSocioUseCase(self._socio_repo, self._notificacao)
        self.obter_socio = ObterSocioUseCase(self._socio_repo)
        self.listar_socios = ListarSociosUseCase(self._socio_repo)
        self.atualizar_plano = AtualizarPlanoSocioUseCase(self._socio_repo)
        self.suspender_socio = SuspenderSocioUseCase(self._socio_repo)
        self.criar_plano = CriarPlanoTreinoUseCase(self._plano_repo, self._socio_repo, self._notificacao)
        self.listar_planos_socio = ListarPlanosPorSocioUseCase(self._plano_repo)
        self.obter_plano = ObterPlanoTreinoUseCase(self._plano_repo)
        self.gerar_relatorio = GerarRelatorioSocioUseCase(self._socio_repo, self._relatorio)

    def estatisticas(self) -> dict:
        return {
            "fila": self.fila_relatorios.estatisticas(),
            "eventos": {"historico_total": len(self.bus_eventos.historico())},
            "metricas": self._estatisticas.estatisticas(),
        }

    def parar(self) -> None:
        self._worker.parar()


SIMULAR_FALHA = os.environ.get("GYMCORE_SIMULAR_FALHA", "false").lower() == "true"
container = Container(simular_falha=SIMULAR_FALHA)
