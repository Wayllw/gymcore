"""
Portos de saída (Output Ports) — Interfaces que o Core define.
A infraestrutura IMPLEMENTA estas interfaces; o Core apenas as conhece.
Este é o coração do DIP: o domínio depende de abstrações, nunca de concretizações.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID


class ISocioRepository(ABC):
    """Porto de saída para persistência de Sócios."""

    @abstractmethod
    def guardar(self, socio) -> None:
        """Persiste um sócio (cria ou atualiza)."""
        ...

    @abstractmethod
    def obter_por_id(self, socio_id: UUID):
        """Devolve um Sócio pelo ID ou None se não existir."""
        ...

    @abstractmethod
    def obter_por_email(self, email: str):
        """Devolve um Sócio pelo email ou None se não existir."""
        ...

    @abstractmethod
    def listar_todos(self) -> List:
        """Devolve todos os sócios."""
        ...

    @abstractmethod
    def eliminar(self, socio_id: UUID) -> None:
        """Remove um sócio pelo ID."""
        ...


class IPlanoTreinoRepository(ABC):
    """Porto de saída para persistência de Planos de Treino."""

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


class INotificacaoService(ABC):
    """
    Porto de saída para notificações.
    Na Fase 1: simulado em memória.
    Na Fase 2: substituído por mensagens assíncronas (queue).
    Mudança transparente para o Core graças ao DIP.
    """

    @abstractmethod
    def enviar_boas_vindas(self, email: str, nome: str) -> None:
        ...

    @abstractmethod
    def notificar_plano_criado(self, email: str, nome_plano: str) -> None:
        ...


class IRelatorioService(ABC):
    """
    Porto de saída para geração de relatórios.
    Na Fase 1: simulado (apenas log).
    Na Fase 2: processamento assíncrono via Worker.
    """

    @abstractmethod
    def gerar_relatorio_socio(self, socio_id: UUID) -> str:
        """Devolve um identificador/path do relatório gerado."""
        ...
