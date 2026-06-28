"""
Testes unitários do Core do Treinos-Service — SEM infraestrutura real.

Usa fakes em memória para IPlanoTreinoRepository, ISocioValidationClient
e IEventPublisher. Testa especificamente:
  - Criação de plano com validação bem-sucedida/falhada
  - A Saga "Inscrição Completa": criação do plano inicial e compensação
  - Comportamento correto quando a validação remota está indisponível
    (simula circuito aberto sem precisar de gRPC real)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from uuid import UUID, uuid4
import pytest

from domain.entities.plano_treino import PlanoTreino
from domain.exceptions.dominio_exceptions import (
    PlanoTreinoNaoEncontradoException,
    SocioInvalidoException,
    SocioValidationIndisponivelException,
)
from application.ports.output_ports import (
    IPlanoTreinoRepository,
    ISocioValidationClient,
    IEventPublisher,
)
from application.dtos.dtos import CriarPlanoTreinoDTO, ExercicioDTO
from application.use_cases.plano_treino_use_cases import (
    CriarPlanoTreinoUseCase,
    ListarPlanosPorSocioUseCase,
    ObterPlanoTreinoUseCase,
    CriarPlanoInicialUseCase,
)


class FakePlanoTreinoRepository(IPlanoTreinoRepository):

    def __init__(self):
        self._dados = {}

    def guardar(self, plano):
        self._dados[plano.id] = plano

    def obter_por_id(self, plano_id):
        return self._dados.get(plano_id)

    def listar_por_socio(self, socio_id):
        return [p for p in self._dados.values() if p.socio_id == socio_id]

    def eliminar(self, plano_id):
        self._dados.pop(plano_id, None)


class FakeSocioValidationClient(ISocioValidationClient):
    """
    Fake configurável — permite simular qualquer resposta do
    Sócios-Service (sócio válido, inexistente, suspenso) ou a
    indisponibilidade do circuito, sem qualquer gRPC real.
    """

    def __init__(self, existe=True, ativo=True, nome="Sócio Teste", mensagem="OK", indisponivel=False):
        self.existe = existe
        self.ativo = ativo
        self.nome = nome
        self.mensagem = mensagem
        self.indisponivel = indisponivel
        self.chamadas = []

    def validar_socio(self, socio_id, correlation_id):
        self.chamadas.append((socio_id, correlation_id))
        if self.indisponivel:
            raise SocioValidationIndisponivelException("circuito aberto (simulado)")
        return (self.existe, self.ativo, self.nome, self.mensagem)


class FakeEventPublisher(IEventPublisher):

    def __init__(self):
        self.eventos_publicados = []

    def publicar(self, tipo_evento, payload, correlation_id):
        self.eventos_publicados.append((tipo_evento, payload, correlation_id))


def _exercicio_dto():
    return ExercicioDTO(nome="Supino", series=3, repeticoes=10, descanso_segundos=60, tipo="FORCA")


class TestCriarPlanoTreinoUseCase:

    def test_cria_plano_quando_socio_valido(self):
        repo = FakePlanoTreinoRepository()
        validacao = FakeSocioValidationClient(existe=True, ativo=True)
        uc = CriarPlanoTreinoUseCase(repo, validacao)

        dto = CriarPlanoTreinoDTO(
            socio_id=uuid4(), nome="Plano Teste", nivel="INTERMEDIO",
            exercicios=[_exercicio_dto()],
        )
        resultado = uc.executar(dto, correlation_id="cid-1")

        assert resultado.nome == "Plano Teste"
        assert len(resultado.exercicios) == 1
        assert len(validacao.chamadas) == 1

    def test_rejeita_quando_socio_nao_existe(self):
        repo = FakePlanoTreinoRepository()
        validacao = FakeSocioValidationClient(existe=False, ativo=False, mensagem="Sócio não encontrado.")
        uc = CriarPlanoTreinoUseCase(repo, validacao)

        dto = CriarPlanoTreinoDTO(
            socio_id=uuid4(), nome="Plano Teste", nivel="INICIANTE", exercicios=[],
        )
        with pytest.raises(SocioInvalidoException):
            uc.executar(dto, correlation_id="cid-1")

        assert len(repo._dados) == 0  # nada foi persistido

    def test_rejeita_quando_socio_suspenso(self):
        repo = FakePlanoTreinoRepository()
        validacao = FakeSocioValidationClient(existe=True, ativo=False, mensagem="Sócio está SUSPENSO")
        uc = CriarPlanoTreinoUseCase(repo, validacao)

        dto = CriarPlanoTreinoDTO(
            socio_id=uuid4(), nome="Plano Teste", nivel="INICIANTE", exercicios=[],
        )
        with pytest.raises(SocioInvalidoException):
            uc.executar(dto, correlation_id="cid-1")

    def test_propaga_excecao_quando_validacao_indisponivel(self):
        """Quando o circuito está aberto, o use case deve propagar a exceção,
        não tentar persistir o plano de qualquer forma."""
        repo = FakePlanoTreinoRepository()
        validacao = FakeSocioValidationClient(indisponivel=True)
        uc = CriarPlanoTreinoUseCase(repo, validacao)

        dto = CriarPlanoTreinoDTO(
            socio_id=uuid4(), nome="Plano Teste", nivel="INICIANTE", exercicios=[],
        )
        with pytest.raises(SocioValidationIndisponivelException):
            uc.executar(dto, correlation_id="cid-1")

        assert len(repo._dados) == 0


class TestObterPlanoTreinoUseCase:

    def test_lanca_excecao_se_nao_encontrado(self):
        repo = FakePlanoTreinoRepository()
        uc = ObterPlanoTreinoUseCase(repo)
        with pytest.raises(PlanoTreinoNaoEncontradoException):
            uc.executar(uuid4())


class TestCriarPlanoInicialUseCase:
    """
    Testa o participante da Saga "Inscrição Completa" no lado do
    Treinos-Service — tanto o caminho de sucesso como o de compensação.
    """

    def test_cria_plano_inicial_quando_socio_valido(self):
        repo = FakePlanoTreinoRepository()
        validacao = FakeSocioValidationClient(existe=True, ativo=True, nome="Sofia")
        eventos = FakeEventPublisher()
        uc = CriarPlanoInicialUseCase(repo, validacao, eventos)

        socio_id = uuid4()
        uc.executar(socio_id, correlation_id="cid-saga-1")

        planos = repo.listar_por_socio(socio_id)
        assert len(planos) == 1
        assert planos[0].nome == CriarPlanoInicialUseCase.PLANO_PADRAO_NOME
        assert len(planos[0].exercicios) == 3  # os 3 exercícios padrão

        # Deve publicar evento de sucesso
        tipos = [t for t, _, _ in eventos.eventos_publicados]
        assert "plano_inicial.criado" in tipos

    def test_publica_falha_quando_socio_nao_existe(self):
        """Caminho de compensação: sócio inexistente no momento da Saga."""
        repo = FakePlanoTreinoRepository()
        validacao = FakeSocioValidationClient(existe=False, ativo=False, mensagem="Sócio não encontrado.")
        eventos = FakeEventPublisher()
        uc = CriarPlanoInicialUseCase(repo, validacao, eventos)

        socio_id = uuid4()
        uc.executar(socio_id, correlation_id="cid-saga-falha-1")

        assert len(repo.listar_por_socio(socio_id)) == 0  # nenhum plano criado
        tipo, payload, cid = eventos.eventos_publicados[0]
        assert tipo == "plano_inicial.falhou"
        assert payload["socio_id"] == str(socio_id)
        assert cid == "cid-saga-falha-1"

    def test_publica_falha_quando_validacao_indisponivel(self):
        """
        Caminho de compensação quando o circuito está aberto.
        Este teste prova que a Saga não fica bloqueada — reage à
        indisponibilidade publicando o evento de compensação, em vez de
        propagar a exceção (que ficaria sem handler no consumer).
        """
        repo = FakePlanoTreinoRepository()
        validacao = FakeSocioValidationClient(indisponivel=True)
        eventos = FakeEventPublisher()
        uc = CriarPlanoInicialUseCase(repo, validacao, eventos)

        socio_id = uuid4()
        # Não deve lançar excecão — deve capturar e publicar falha
        uc.executar(socio_id, correlation_id="cid-saga-falha-2")

        assert len(repo.listar_por_socio(socio_id)) == 0
        tipo, payload, cid = eventos.eventos_publicados[0]
        assert tipo == "plano_inicial.falhou"
        assert "validacao_indisponivel" in payload["motivo"]

    def test_correlation_id_propagado_em_todos_os_eventos(self):
        """Observabilidade distribuída: o correlationId original deve
        chegar inalterado ao evento publicado pela Saga."""
        repo = FakePlanoTreinoRepository()
        validacao = FakeSocioValidationClient(existe=True, ativo=True)
        eventos = FakeEventPublisher()
        uc = CriarPlanoInicialUseCase(repo, validacao, eventos)

        meu_cid = "correlation-id-distribuido-xyz"
        uc.executar(uuid4(), correlation_id=meu_cid)

        _, _, cid_no_evento = eventos.eventos_publicados[0]
        assert cid_no_evento == meu_cid
