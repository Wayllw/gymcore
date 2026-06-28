"""
Portos de saída (Output Ports) — Interfaces que o Core define.
A infraestrutura IMPLEMENTA estas interfaces; o Core apenas as conhece.
DIP: o domínio depende de abstrações, nunca de concretizações.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID


class ISocioRepository(ABC):
    """Porto de saída para persistência de Sócios. Implementado com SQLite na Fase 3."""

    @abstractmethod
    def guardar(self, socio) -> None:
        ...

    @abstractmethod
    def obter_por_id(self, socio_id: UUID):
        ...

    @abstractmethod
    def obter_por_email(self, email: str):
        ...

    @abstractmethod
    def listar_todos(self) -> List:
        ...

    @abstractmethod
    def eliminar(self, socio_id: UUID) -> None:
        ...


class IEventPublisher(ABC):
    """
    Porto de saída para publicação de eventos de domínio.
    Implementado com Redis Streams — mas o Core não sabe disso.
    Permite comunicação assíncrona com outros serviços (ex: Treinos-Service)
    sem acoplamento direto.
    """

    @abstractmethod
    def publicar(self, tipo_evento: str, payload: dict, correlation_id: str) -> None:
        ...
