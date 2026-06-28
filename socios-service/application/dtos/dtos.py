"""
DTOs (Data Transfer Objects) — estruturas simples de dados para
comunicação entre a camada de aplicação e o exterior.
"""
from dataclasses import dataclass
from datetime import date
from uuid import UUID


@dataclass
class InscreverSocioDTO:
    nome: str
    email: str
    data_nascimento: date
    plano: str  # "BASICO" | "STANDARD" | "PREMIUM"


@dataclass
class SocioResponseDTO:
    id: UUID
    nome: str
    email: str
    plano: str
    estado: str
    idade: int
    mensalidade: float
    data_inscricao: date
