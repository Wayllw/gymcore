"""
Entidade Sócio — coração do domínio do Sócios-Service.
Sem dependências de frameworks externos. Pura lógica de negócio.

Bounded Context: Gestão de Sócios e Mensalidades.
Este serviço é o único que pode escrever dados de Sócio (Database-per-Service).
"""
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID, uuid4
from domain.value_objects.plano_mensalidade import PlanoMensalidade
from domain.value_objects.estado_socio import EstadoSocio
from domain.exceptions.dominio_exceptions import SocioInativoException, PlanoInvalidoException


@dataclass
class Socio:
    nome: str
    email: str
    data_nascimento: date
    plano: PlanoMensalidade
    id: UUID = field(default_factory=uuid4)
    estado: EstadoSocio = EstadoSocio.ATIVO
    data_inscricao: date = field(default_factory=date.today)

    def __post_init__(self):
        if not self.nome or not self.nome.strip():
            raise ValueError("O nome do sócio não pode estar vazio.")
        if "@" not in self.email:
            raise ValueError(f"Email inválido: {self.email}")
        if self.data_nascimento >= date.today():
            raise ValueError("Data de nascimento inválida.")

    @property
    def idade(self) -> int:
        today = date.today()
        return today.year - self.data_nascimento.year - (
            (today.month, today.day) < (self.data_nascimento.month, self.data_nascimento.day)
        )

    def suspender(self) -> None:
        if self.estado == EstadoSocio.INATIVO:
            raise SocioInativoException(self.id)
        self.estado = EstadoSocio.SUSPENSO

    def reativar(self) -> None:
        self.estado = EstadoSocio.ATIVO

    def atualizar_plano(self, novo_plano: PlanoMensalidade) -> None:
        if self.estado == EstadoSocio.INATIVO:
            raise SocioInativoException(self.id)
        if novo_plano not in PlanoMensalidade:
            raise PlanoInvalidoException(novo_plano)
        self.plano = novo_plano

    def calcular_mensalidade(self) -> float:
        """Regra de negócio: Sócios com mais de 65 anos têm desconto de 20%."""
        preco_base = self.plano.preco
        if self.idade >= 65:
            return round(preco_base * 0.80, 2)
        return preco_base

    def __repr__(self):
        return f"Socio(id={self.id}, nome='{self.nome}', plano={self.plano.name}, estado={self.estado.name})"
