"""
DTOs (Data Transfer Objects) — estruturas simples de dados para
comunicação entre a camada de aplicação e o exterior.
Sem lógica de negócio; apenas transporte de dados.
"""
from dataclasses import dataclass
from datetime import date
from uuid import UUID
from typing import List, Optional


# ─── Sócio ────────────────────────────────────────────────────────────────────

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


# ─── Plano de Treino ──────────────────────────────────────────────────────────

@dataclass
class ExercicioDTO:
    nome: str
    series: int
    repeticoes: int
    descanso_segundos: int
    tipo: str  # "FORCA" | "CARDIO" | "FLEXIBILIDADE" | "FUNCIONAL"


@dataclass
class CriarPlanoTreinoDTO:
    socio_id: UUID
    nome: str
    nivel: str  # "INICIANTE" | "INTERMEDIO" | "AVANCADO"
    exercicios: List[ExercicioDTO]


@dataclass
class PlanoTreinoResponseDTO:
    id: UUID
    nome: str
    nivel: str
    socio_id: UUID
    exercicios: List[ExercicioDTO]
    duracao_estimada_minutos: int
    data_criacao: date
    ativo: bool
