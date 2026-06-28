"""
Testes unitários do Core do Sócios-Service — SEM infraestrutura real.

Usa fakes em memória para ISocioRepository e IEventPublisher,
demonstrando que o domínio e os use cases são totalmente testáveis
isoladamente — requisito explícito do enunciado em todas as fases.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import date
from uuid import UUID
import pytest

from domain.entities.socio import Socio
from domain.value_objects.plano_mensalidade import PlanoMensalidade
from domain.value_objects.estado_socio import EstadoSocio
from domain.exceptions.dominio_exceptions import (
    SocioJaExisteException,
    SocioNaoEncontradoException,
    SocioInativoException,
)
from application.ports.output_ports import ISocioRepository, IEventPublisher
from application.dtos.dtos import InscreverSocioDTO
from application.use_cases.socios_use_cases import (
    InscreverSocioUseCase,
    ObterSocioUseCase,
    SuspenderSocioUseCase,
    MarcarParaAcompanhamentoUseCase,
)


class FakeSocioRepository(ISocioRepository):
    """Fake em memória — não usa SQLite nem qualquer infraestrutura real."""

    def __init__(self):
        self._dados = {}

    def guardar(self, socio):
        self._dados[socio.id] = socio

    def obter_por_id(self, socio_id):
        return self._dados.get(socio_id)

    def obter_por_email(self, email):
        return next((s for s in self._dados.values() if s.email == email), None)

    def listar_todos(self):
        return list(self._dados.values())

    def eliminar(self, socio_id):
        self._dados.pop(socio_id, None)


class FakeEventPublisher(IEventPublisher):
    """Fake — não usa Redis. Apenas regista os eventos publicados para inspeção."""

    def __init__(self):
        self.eventos_publicados = []

    def publicar(self, tipo_evento, payload, correlation_id):
        self.eventos_publicados.append((tipo_evento, payload, correlation_id))


class TestInscreverSocioUseCase:

    def test_inscreve_socio_com_sucesso(self):
        repo = FakeSocioRepository()
        eventos = FakeEventPublisher()
        uc = InscreverSocioUseCase(repo, eventos)

        dto = InscreverSocioDTO(
            nome="Ana Silva", email="ana@gym.pt",
            data_nascimento=date(1990, 5, 15), plano="STANDARD",
        )
        resultado = uc.executar(dto, correlation_id="cid-1")

        assert resultado.nome == "Ana Silva"
        assert resultado.plano == "STANDARD"
        assert resultado.estado == "ATIVO"
        assert len(repo.listar_todos()) == 1

    def test_publica_evento_socio_inscrito(self):
        """A Saga depende deste evento ser publicado corretamente."""
        repo = FakeSocioRepository()
        eventos = FakeEventPublisher()
        uc = InscreverSocioUseCase(repo, eventos)

        dto = InscreverSocioDTO(
            nome="Bruno Costa", email="bruno@gym.pt",
            data_nascimento=date(1988, 1, 1), plano="BASICO",
        )
        resultado = uc.executar(dto, correlation_id="cid-saga-test")

        assert len(eventos.eventos_publicados) == 1
        tipo, payload, cid = eventos.eventos_publicados[0]
        assert tipo == "socio.inscrito"
        assert payload["socio_id"] == str(resultado.id)
        assert cid == "cid-saga-test"

    def test_rejeita_email_duplicado(self):
        repo = FakeSocioRepository()
        eventos = FakeEventPublisher()
        uc = InscreverSocioUseCase(repo, eventos)

        dto = InscreverSocioDTO(
            nome="Carla Dias", email="carla@gym.pt",
            data_nascimento=date(1995, 3, 3), plano="PREMIUM",
        )
        uc.executar(dto, correlation_id="cid-1")

        with pytest.raises(SocioJaExisteException):
            uc.executar(dto, correlation_id="cid-2")

    def test_calcula_mensalidade_com_desconto_idoso(self):
        repo = FakeSocioRepository()
        eventos = FakeEventPublisher()
        uc = InscreverSocioUseCase(repo, eventos)

        dto = InscreverSocioDTO(
            nome="Idoso Teste", email="idoso@gym.pt",
            data_nascimento=date(1950, 1, 1), plano="STANDARD",
        )
        resultado = uc.executar(dto, correlation_id="cid-1")
        # 40.00 * 0.80 = 32.00
        assert resultado.mensalidade == 32.00


class TestObterSocioUseCase:

    def test_obtem_socio_existente(self):
        repo = FakeSocioRepository()
        socio = Socio(nome="Teste", email="t@t.pt", data_nascimento=date(1990, 1, 1),
                       plano=PlanoMensalidade.BASICO)
        repo.guardar(socio)

        uc = ObterSocioUseCase(repo)
        resultado = uc.executar(socio.id)
        assert resultado.id == socio.id

    def test_lanca_excecao_se_nao_encontrado(self):
        repo = FakeSocioRepository()
        uc = ObterSocioUseCase(repo)
        with pytest.raises(SocioNaoEncontradoException):
            uc.executar(UUID("00000000-0000-0000-0000-000000000000"))


class TestSuspenderSocioUseCase:

    def test_suspende_socio_ativo(self):
        repo = FakeSocioRepository()
        socio = Socio(nome="Teste", email="t2@t.pt", data_nascimento=date(1990, 1, 1),
                       plano=PlanoMensalidade.BASICO)
        repo.guardar(socio)

        uc = SuspenderSocioUseCase(repo)
        resultado = uc.executar(socio.id)
        assert resultado.estado == "SUSPENSO"


class TestMarcarParaAcompanhamentoUseCase:
    """Testa a ação de compensação da Saga isoladamente."""

    def test_marca_socio_existente(self):
        repo = FakeSocioRepository()
        socio = Socio(nome="Saga Teste", email="saga@t.pt", data_nascimento=date(1990, 1, 1),
                       plano=PlanoMensalidade.BASICO)
        repo.guardar(socio)

        uc = MarcarParaAcompanhamentoUseCase(repo)
        uc.executar(socio.id, motivo="teste de falha", correlation_id="cid-comp-1")

        assert uc.esta_marcado(socio.id) is True

    def test_ignora_socio_inexistente_sem_lancar_excecao(self):
        repo = FakeSocioRepository()
        uc = MarcarParaAcompanhamentoUseCase(repo)
        # Não deve lançar excecão — apenas regista e ignora
        uc.executar(UUID("00000000-0000-0000-0000-000000000000"), motivo="x", correlation_id="cid-1")
