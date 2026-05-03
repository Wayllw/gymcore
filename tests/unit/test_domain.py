"""
Testes Unitários: Entidades de Domínio

DEMONSTRAÇÃO DO DIP/TESTABILIDADE:
Estes testes correm SEM Flask, SEM base de dados, SEM qualquer infraestrutura.
O Core é testável de forma completamente isolada — é exatamente isto que o DIP permite.
"""
import pytest
from datetime import date, timedelta
from uuid import uuid4

from domain.entities.socio import Socio
from domain.entities.plano_treino import PlanoTreino, Exercicio
from domain.value_objects.plano_mensalidade import PlanoMensalidade
from domain.value_objects.estado_socio import EstadoSocio
from domain.value_objects.nivel_treino import NivelTreino
from domain.value_objects.tipo_exercicio import TipoExercicio
from domain.exceptions.dominio_exceptions import (
    SocioInativoException,
    PlanoTreinoInvalidoException,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def make_socio(nome="Ana Silva", email="ana@gym.pt", plano=PlanoMensalidade.STANDARD, anos=30):
    return Socio(
        nome=nome,
        email=email,
        data_nascimento=date.today().replace(year=date.today().year - anos),
        plano=plano,
    )


def make_exercicio(nome="Supino", tipo=TipoExercicio.FORCA):
    return Exercicio(nome=nome, series=3, repeticoes=10, descanso_segundos=60, tipo=tipo)


# ─── Testes: Sócio ────────────────────────────────────────────────────────────

class TestSocio:

    def test_criar_socio_valido(self):
        socio = make_socio()
        assert socio.nome == "Ana Silva"
        assert socio.estado == EstadoSocio.ATIVO
        assert socio.id is not None

    def test_email_invalido_levanta_excecao(self):
        with pytest.raises(ValueError, match="Email inválido"):
            make_socio(email="sem-arroba")

    def test_nome_vazio_levanta_excecao(self):
        with pytest.raises(ValueError, match="nome"):
            make_socio(nome="   ")

    def test_data_nascimento_futura_levanta_excecao(self):
        with pytest.raises(ValueError, match="Data de nascimento"):
            Socio(
                nome="Test",
                email="t@t.pt",
                data_nascimento=date.today() + timedelta(days=1),
                plano=PlanoMensalidade.BASICO,
            )

    def test_calcular_mensalidade_standard(self):
        socio = make_socio(plano=PlanoMensalidade.STANDARD, anos=30)
        assert socio.calcular_mensalidade() == 40.00

    def test_calcular_mensalidade_desconto_senior(self):
        """Sócios com 65+ anos têm 20% de desconto."""
        socio = make_socio(plano=PlanoMensalidade.PREMIUM, anos=65)
        esperado = round(60.00 * 0.80, 2)
        assert socio.calcular_mensalidade() == esperado

    def test_mensalidade_basico_sem_desconto(self):
        socio = make_socio(plano=PlanoMensalidade.BASICO, anos=40)
        assert socio.calcular_mensalidade() == 25.00

    def test_suspender_socio_ativo(self):
        socio = make_socio()
        socio.suspender()
        assert socio.estado == EstadoSocio.SUSPENSO

    def test_suspender_socio_inativo_levanta_excecao(self):
        socio = make_socio()
        socio.estado = EstadoSocio.INATIVO
        with pytest.raises(SocioInativoException):
            socio.suspender()

    def test_reativar_socio_suspenso(self):
        socio = make_socio()
        socio.suspender()
        socio.reativar()
        assert socio.estado == EstadoSocio.ATIVO

    def test_atualizar_plano_com_sucesso(self):
        socio = make_socio(plano=PlanoMensalidade.BASICO)
        socio.atualizar_plano(PlanoMensalidade.PREMIUM)
        assert socio.plano == PlanoMensalidade.PREMIUM

    def test_atualizar_plano_socio_inativo_levanta_excecao(self):
        socio = make_socio()
        socio.estado = EstadoSocio.INATIVO
        with pytest.raises(SocioInativoException):
            socio.atualizar_plano(PlanoMensalidade.PREMIUM)

    def test_idade_calculada_corretamente(self):
        socio = make_socio(anos=25)
        assert socio.idade == 25

    def test_ids_socios_distintos(self):
        s1 = make_socio(email="a@gym.pt")
        s2 = make_socio(email="b@gym.pt")
        assert s1.id != s2.id


# ─── Testes: Exercício ────────────────────────────────────────────────────────

class TestExercicio:

    def test_criar_exercicio_valido(self):
        ex = make_exercicio()
        assert ex.nome == "Supino"
        assert ex.volume_total == 30  # 3 × 10

    def test_series_zero_levanta_excecao(self):
        with pytest.raises(ValueError):
            Exercicio("X", series=0, repeticoes=10, descanso_segundos=60, tipo=TipoExercicio.FORCA)

    def test_volume_calculado_corretamente(self):
        ex = Exercicio("Agachamento", series=4, repeticoes=12, descanso_segundos=90, tipo=TipoExercicio.FORCA)
        assert ex.volume_total == 48


# ─── Testes: Plano de Treino ──────────────────────────────────────────────────

class TestPlanoTreino:

    def test_criar_plano_valido(self):
        plano = PlanoTreino(
            nome="Plano A",
            nivel=NivelTreino.INICIANTE,
            socio_id=uuid4(),
        )
        assert plano.nome == "Plano A"
        assert plano.ativo is True
        assert len(plano.exercicios) == 0

    def test_adicionar_exercicio(self):
        plano = PlanoTreino("P", NivelTreino.INTERMEDIO, uuid4())
        plano.adicionar_exercicio(make_exercicio())
        assert len(plano.exercicios) == 1

    def test_limite_20_exercicios(self):
        plano = PlanoTreino("P", NivelTreino.AVANCADO, uuid4())
        for i in range(20):
            plano.adicionar_exercicio(Exercicio(
                f"Ex{i}", 3, 10, 60, TipoExercicio.FORCA
            ))
        with pytest.raises(PlanoTreinoInvalidoException, match="20"):
            plano.adicionar_exercicio(make_exercicio("Extra"))

    def test_remover_exercicio_existente(self):
        plano = PlanoTreino("P", NivelTreino.INICIANTE, uuid4())
        plano.adicionar_exercicio(make_exercicio("Supino"))
        plano.remover_exercicio("Supino")
        assert len(plano.exercicios) == 0

    def test_remover_exercicio_inexistente_levanta_excecao(self):
        plano = PlanoTreino("P", NivelTreino.INICIANTE, uuid4())
        with pytest.raises(PlanoTreinoInvalidoException):
            plano.remover_exercicio("NaoExiste")

    def test_duracao_estimada_plano_vazio(self):
        plano = PlanoTreino("P", NivelTreino.INICIANTE, uuid4())
        assert plano.calcular_duracao_estimada_minutos() == 0

    def test_duracao_estimada_com_exercicios(self):
        """3 séries × (45s exec + 60s descanso) = 315s → 5 min"""
        plano = PlanoTreino("P", NivelTreino.INICIANTE, uuid4())
        plano.adicionar_exercicio(Exercicio("Ex", 3, 10, 60, TipoExercicio.FORCA))
        duracao = plano.calcular_duracao_estimada_minutos()
        assert duracao == 5

    def test_desativar_plano(self):
        plano = PlanoTreino("P", NivelTreino.INICIANTE, uuid4())
        plano.desativar()
        assert plano.ativo is False

    def test_nome_vazio_levanta_excecao(self):
        with pytest.raises(ValueError):
            PlanoTreino("", NivelTreino.INICIANTE, uuid4())
