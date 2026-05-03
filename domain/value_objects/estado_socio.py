"""Value Object: EstadoSocio"""
from enum import Enum


class EstadoSocio(Enum):
    ATIVO = "ATIVO"
    SUSPENSO = "SUSPENSO"
    INATIVO = "INATIVO"
