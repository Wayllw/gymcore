"""
Portos de saída (Output Ports) — Interfaces que o Core define.
DIP: o domínio depende de abstrações, nunca de concretizações.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from uuid import UUID


class IPlanoTreinoRepository(ABC):
    """Porto de saída para persistência de Planos de Treino. Implementado com SQLite."""

    @abstractmethod
    def guardar(self, plano) -> None:
        ...

    @abstractmethod
    def obter_por_id(self, plano_id: UUID):
        ...

    @abstractmethod
    def listar_por_socio(self, socio_id: UUID) -> List:
        ...

    @abstractmethod
    def eliminar(self, plano_id: UUID) -> None:
        ...


class ISocioValidationClient(ABC):
    """
    Porto de saída para validação remota de Sócios.

    Implementado com um cliente gRPC envolvido num Circuit Breaker —
    mas o Core (use cases) não sabe disso. Apenas sabe que pode pedir
    "valida-me este sócio" e recebe uma resposta estruturada.
    """

    @abstractmethod
    def validar_socio(self, socio_id: UUID, correlation_id: str) -> Tuple[bool, bool, str, str]:
        """
        Retorna (existe, ativo, nome, mensagem).
        Pode levantar SocioValidationIndisponivelException se o circuito
        estiver aberto ou a chamada falhar de forma irrecuperável.
        """
        ...


class IEventPublisher(ABC):
    """Porto de saída para publicação de eventos de domínio via Redis Streams."""

    @abstractmethod
    def publicar(self, tipo_evento: str, payload: dict, correlation_id: str) -> None:
        ...
