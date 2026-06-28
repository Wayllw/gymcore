"""
Entidade Plano de Treino — coração do domínio do Treinos-Service.
Sem dependências de frameworks externos. Pura lógica de negócio.

Bounded Context: Gestão de Planos de Treino e Exercícios.
Este serviço é o único que pode escrever dados de PlanoTreino (Database-per-Service).
Mantém apenas socio_id como referência (chave fraca) ao Sócios-Service —
nunca acede diretamente à BD de Sócios.
"""
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID, uuid4
from typing import List
from domain.value_objects.nivel_treino import NivelTreino
from domain.value_objects.tipo_exercicio import TipoExercicio
from domain.exceptions.dominio_exceptions import PlanoTreinoInvalidoException


@dataclass
class Exercicio:
    nome: str
    series: int
    repeticoes: int
    descanso_segundos: int
    tipo: TipoExercicio

    def __post_init__(self):
        if self.series <= 0 or self.repeticoes <= 0:
            raise ValueError("Séries e repetições devem ser positivos.")
        if self.descanso_segundos < 0:
            raise ValueError("Tempo de descanso não pode ser negativo.")

    @property
    def volume_total(self) -> int:
        return self.series * self.repeticoes


@dataclass
class PlanoTreino:
    nome: str
    nivel: NivelTreino
    socio_id: UUID  # referência fraca — nunca um JOIN, apenas um ID
    exercicios: List[Exercicio] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    data_criacao: date = field(default_factory=date.today)
    ativo: bool = True

    def __post_init__(self):
        if not self.nome or not self.nome.strip():
            raise ValueError("O nome do plano não pode estar vazio.")

    def adicionar_exercicio(self, exercicio: Exercicio) -> None:
        if len(self.exercicios) >= 20:
            raise PlanoTreinoInvalidoException("Um plano não pode ter mais de 20 exercícios.")
        self.exercicios.append(exercicio)

    def remover_exercicio(self, nome_exercicio: str) -> None:
        original = len(self.exercicios)
        self.exercicios = [e for e in self.exercicios if e.nome != nome_exercicio]
        if len(self.exercicios) == original:
            raise PlanoTreinoInvalidoException(f"Exercício '{nome_exercicio}' não encontrado.")

    def calcular_duracao_estimada_minutos(self) -> int:
        if not self.exercicios:
            return 0
        total_segundos = sum(
            (e.series * 45) + (e.series * e.descanso_segundos)
            for e in self.exercicios
        )
        return total_segundos // 60

    def desativar(self) -> None:
        self.ativo = False

    def __repr__(self):
        return (
            f"PlanoTreino(id={self.id}, nome='{self.nome}', "
            f"nivel={self.nivel.name}, exercicios={len(self.exercicios)})"
        )
