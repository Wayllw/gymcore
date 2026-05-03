"""
Testes Unitários: Casos de Uso com Mocks

DEMONSTRAÇÃO DO DIP:
Os use cases dependem de interfaces (ISocioRepository, INotificacaoService).
Aqui substituímos as implementações reais por mocks — o use case não sabe a diferença.
Isto é o DIP em ação: testamos a lógica de aplicação sem NENHUMA infraestrutura.
"""
import pytest
from datetime import date
from unittest.mock import MagicMock, call
from uuid import uuid4

from application.use_cases.socios_use_cases import (
    InscreverSocioUseCase,
    ObterSocioUseCase,
    AtualizarPlanoSocioUseCase,
    SuspenderSocioUseCase,
)
from application.use_cases.plano_treino_use_cases import (
    CriarPlanoTreinoUseCase,
    ListarPlanosPorSocioUseCase,
)
from application.dtos.dtos import InscreverSocioDTO, CriarPlanoTreinoDTO, ExercicioDTO
from domain.entities.socio import Socio
from domain.value_objects.plano_mensalidade import PlanoMensalidade
from domain.value_objects.estado_socio import EstadoSocio
from domain.exceptions.dominio_exceptions import (
    SocioJaExisteException,
    SocioNaoEncontradoException,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_socio_repo():
    return MagicMock()


@pytest.fixture
def mock_plano_repo():
    return MagicMock()


@pytest.fixture
def mock_notificacao():
    return MagicMock()


@pytest.fixture
def socio_exemplo():
    return Socio(
        nome="Carlos Matos",
        email="carlos@gym.pt",
        data_nascimento=date(1990, 5, 15),
        plano=PlanoMensalidade.STANDARD,
    )


# ─── Testes: InscreverSocioUseCase ────────────────────────────────────────────

class TestInscreverSocioUseCase:

    def test_inscrever_socio_com_sucesso(self, mock_socio_repo, mock_notificacao):
        mock_socio_repo.obter_por_email.return_value = None  # não existe ainda

        uc = InscreverSocioUseCase(mock_socio_repo, mock_notificacao)
        dto = InscreverSocioDTO(
            nome="Carlos Matos",
            email="carlos@gym.pt",
            data_nascimento=date(1990, 5, 15),
            plano="STANDARD",
        )
        resultado = uc.executar(dto)

        assert resultado.nome == "Carlos Matos"
        assert resultado.plano == "STANDARD"
        mock_socio_repo.guardar.assert_called_once()
        mock_notificacao.enviar_boas_vindas.assert_called_once_with(
            "carlos@gym.pt", "Carlos Matos"
        )

    def test_inscrever_socio_duplicado_levanta_excecao(
        self, mock_socio_repo, mock_notificacao, socio_exemplo
    ):
        mock_socio_repo.obter_por_email.return_value = socio_exemplo  # já existe

        uc = InscreverSocioUseCase(mock_socio_repo, mock_notificacao)
        dto = InscreverSocioDTO(
            nome="Carlos Matos",
            email="carlos@gym.pt",
            data_nascimento=date(1990, 5, 15),
            plano="STANDARD",
        )
        with pytest.raises(SocioJaExisteException):
            uc.executar(dto)

        mock_socio_repo.guardar.assert_not_called()
        mock_notificacao.enviar_boas_vindas.assert_not_called()

    def test_inscrever_retorna_mensalidade_calculada(self, mock_socio_repo, mock_notificacao):
        mock_socio_repo.obter_por_email.return_value = None
        uc = InscreverSocioUseCase(mock_socio_repo, mock_notificacao)
        dto = InscreverSocioDTO(
            nome="Test",
            email="t@gym.pt",
            data_nascimento=date(1990, 1, 1),
            plano="PREMIUM",
        )
        resultado = uc.executar(dto)
        assert resultado.mensalidade == 60.00


# ─── Testes: ObterSocioUseCase ────────────────────────────────────────────────

class TestObterSocioUseCase:

    def test_obter_socio_existente(self, mock_socio_repo, socio_exemplo):
        mock_socio_repo.obter_por_id.return_value = socio_exemplo
        uc = ObterSocioUseCase(mock_socio_repo)
        resultado = uc.executar(socio_exemplo.id)
        assert resultado.email == "carlos@gym.pt"

    def test_obter_socio_inexistente_levanta_excecao(self, mock_socio_repo):
        mock_socio_repo.obter_por_id.return_value = None
        uc = ObterSocioUseCase(mock_socio_repo)
        with pytest.raises(SocioNaoEncontradoException):
            uc.executar(uuid4())


# ─── Testes: AtualizarPlanoSocioUseCase ──────────────────────────────────────

class TestAtualizarPlanoSocioUseCase:

    def test_atualizar_plano_com_sucesso(self, mock_socio_repo, socio_exemplo):
        mock_socio_repo.obter_por_id.return_value = socio_exemplo
        uc = AtualizarPlanoSocioUseCase(mock_socio_repo)
        resultado = uc.executar(socio_exemplo.id, "PREMIUM")
        assert resultado.plano == "PREMIUM"
        mock_socio_repo.guardar.assert_called_once()

    def test_atualizar_plano_socio_inexistente(self, mock_socio_repo):
        mock_socio_repo.obter_por_id.return_value = None
        uc = AtualizarPlanoSocioUseCase(mock_socio_repo)
        with pytest.raises(SocioNaoEncontradoException):
            uc.executar(uuid4(), "PREMIUM")


# ─── Testes: SuspenderSocioUseCase ───────────────────────────────────────────

class TestSuspenderSocioUseCase:

    def test_suspender_socio_ativo(self, mock_socio_repo, socio_exemplo):
        mock_socio_repo.obter_por_id.return_value = socio_exemplo
        uc = SuspenderSocioUseCase(mock_socio_repo)
        resultado = uc.executar(socio_exemplo.id)
        assert resultado.estado == "SUSPENSO"

    def test_suspender_socio_inexistente(self, mock_socio_repo):
        mock_socio_repo.obter_por_id.return_value = None
        uc = SuspenderSocioUseCase(mock_socio_repo)
        with pytest.raises(SocioNaoEncontradoException):
            uc.executar(uuid4())


# ─── Testes: CriarPlanoTreinoUseCase ─────────────────────────────────────────

class TestCriarPlanoTreinoUseCase:

    def test_criar_plano_com_sucesso(
        self, mock_plano_repo, mock_socio_repo, mock_notificacao, socio_exemplo
    ):
        mock_socio_repo.obter_por_id.return_value = socio_exemplo

        uc = CriarPlanoTreinoUseCase(mock_plano_repo, mock_socio_repo, mock_notificacao)
        dto = CriarPlanoTreinoDTO(
            socio_id=socio_exemplo.id,
            nome="Plano Força",
            nivel="INTERMEDIO",
            exercicios=[
                ExercicioDTO("Supino", 3, 10, 60, "FORCA"),
                ExercicioDTO("Agachamento", 4, 8, 90, "FORCA"),
            ],
        )
        resultado = uc.executar(dto)

        assert resultado.nome == "Plano Força"
        assert len(resultado.exercicios) == 2
        mock_plano_repo.guardar.assert_called_once()
        mock_notificacao.notificar_plano_criado.assert_called_once_with(
            socio_exemplo.email, "Plano Força"
        )

    def test_criar_plano_socio_inexistente(
        self, mock_plano_repo, mock_socio_repo, mock_notificacao
    ):
        mock_socio_repo.obter_por_id.return_value = None
        uc = CriarPlanoTreinoUseCase(mock_plano_repo, mock_socio_repo, mock_notificacao)
        dto = CriarPlanoTreinoDTO(
            socio_id=uuid4(), nome="P", nivel="INICIANTE", exercicios=[]
        )
        with pytest.raises(SocioNaoEncontradoException):
            uc.executar(dto)
