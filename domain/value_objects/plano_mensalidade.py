"""
Value Object: PlanoMensalidade
Encapsula preço e nome do plano — imutável por natureza (enum).
"""
from enum import Enum


class PlanoMensalidade(Enum):
    BASICO = "BASICO"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"

    @property
    def preco(self) -> float:
        precos = {
            PlanoMensalidade.BASICO: 25.00,
            PlanoMensalidade.STANDARD: 40.00,
            PlanoMensalidade.PREMIUM: 60.00,
        }
        return precos[self]

    @property
    def descricao(self) -> str:
        descricoes = {
            PlanoMensalidade.BASICO: "Acesso sala de musculação (08h-20h)",
            PlanoMensalidade.STANDARD: "Acesso total + 2 aulas de grupo/semana",
            PlanoMensalidade.PREMIUM: "Acesso total + aulas ilimitadas + PT mensal",
        }
        return descricoes[self]
