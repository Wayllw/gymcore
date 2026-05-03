"""
Testes de Integração: Repositórios em Memória + Use Cases

Testa o fluxo completo com os adaptadores reais (mas sem infraestrutura externa).
Demonstra que as implementações concretas cumprem os contratos das interfaces.
"""
import pytest
from datetime import date
from uuid import uuid4

from infrastructure.adapters.outbound.in_memory_repositories import (
    InMemorySocioRepository,
    InMemoryPlanoTreinoRepository,
)
from infrastructure.adapters.outbound.simulated_services import (
    LogNotificacaoService,
)
from application.use_cases.socios_use_cases import (
    InscreverSocioUseCase,
    ListarSociosUseCase,
    ObterSocioUseCase,
)
from application.use_cases.plano_treino_use_cases import (
    CriarPlanoTreinoUseCase,
    ListarPlanosPorSocioUseCase,
)
from application.dtos.dtos import InscreverSocioDTO, CriarPlanoTreinoDTO, ExercicioDTO
from domain.exceptions.dominio_exceptions import SocioJaExisteException


@pytest.fixture
def repo_socios():
    return InMemorySocioRepository()


@pytest.fixture
def repo_planos():
    return InMemoryPlanoTreinoRepository()


@pytest.fixture
def notificacao():
    return LogNotificacaoService()


class TestIntegracaoSocios:

    def test_inscrever_e_obter_socio(self, repo_socios, notificacao):
        inscrever = InscreverSocioUseCase(repo_socios, notificacao)
        obter = ObterSocioUseCase(repo_socios)

        dto = InscreverSocioDTO("Marta Silva", "marta@gym.pt", date(1995, 3, 10), "BASICO")
        criado = inscrever.executar(dto)
        obtido = obter.executar(criado.id)

        assert obtido.email == "marta@gym.pt"
        assert obtido.id == criado.id

    def test_listar_socios_vazio(self, repo_socios):
        listar = ListarSociosUseCase(repo_socios)
        assert listar.executar() == []

    def test_inscrever_varios_e_listar(self, repo_socios, notificacao):
        inscrever = InscreverSocioUseCase(repo_socios, notificacao)
        listar = ListarSociosUseCase(repo_socios)

        for i in range(3):
            inscrever.executar(InscreverSocioDTO(
                f"Sócio {i}", f"socio{i}@gym.pt", date(1990, 1, 1), "STANDARD"
            ))

        assert len(listar.executar()) == 3

    def test_email_duplicado_rejeitado(self, repo_socios, notificacao):
        inscrever = InscreverSocioUseCase(repo_socios, notificacao)
        dto = InscreverSocioDTO("João", "joao@gym.pt", date(1988, 6, 20), "BASICO")
        inscrever.executar(dto)
        with pytest.raises(SocioJaExisteException):
            inscrever.executar(dto)


class TestIntegracaoPlanosTreino:

    def test_criar_e_listar_planos(self, repo_socios, repo_planos, notificacao):
        # Criar sócio primeiro
        inscrever = InscreverSocioUseCase(repo_socios, notificacao)
        socio = inscrever.executar(
            InscreverSocioDTO("Pedro Costa", "pedro@gym.pt", date(1992, 8, 5), "PREMIUM")
        )

        # Criar plano
        criar = CriarPlanoTreinoUseCase(repo_planos, repo_socios, notificacao)
        listar = ListarPlanosPorSocioUseCase(repo_planos)

        dto = CriarPlanoTreinoDTO(
            socio_id=socio.id,
            nome="Força Máxima",
            nivel="AVANCADO",
            exercicios=[ExercicioDTO("Deadlift", 5, 5, 120, "FORCA")],
        )
        criar.executar(dto)

        planos = listar.executar(socio.id)
        assert len(planos) == 1
        assert planos[0].nome == "Força Máxima"
        assert planos[0].duracao_estimada_minutos > 0
