"""Value Object: TipoExercicio"""
from enum import Enum


class TipoExercicio(Enum):
    FORCA = "FORCA"
    CARDIO = "CARDIO"
    FLEXIBILIDADE = "FLEXIBILIDADE"
    FUNCIONAL = "FUNCIONAL"
