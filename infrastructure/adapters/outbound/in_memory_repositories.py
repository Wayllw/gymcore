"""
Adaptadores de saída: Repositórios em Memória.

Implementam as interfaces definidas no Core (ISocioRepository, IPlanoTreinoRepository).
Na Fase 3 estes serão substituídos por adaptadores com bases de dados reais —
o Core não precisará de qualquer alteração (DIP).
"""
import threading
from typing import Dict, List, Optional
from uuid import UUID

from application.ports.output_ports import ISocioRepository, IPlanoTreinoRepository
from domain.entities.socio import Socio
from domain.entities.plano_treino import PlanoTreino


class InMemorySocioRepository(ISocioRepository):
    """
    Repositório em memória para Sócios.
    Thread-safe com lock para simular concorrência futura.
    """

    def __init__(self):
        self._store: Dict[UUID, Socio] = {}
        self._lock = threading.Lock()

    def guardar(self, socio: Socio) -> None:
        with self._lock:
            self._store[socio.id] = socio

    def obter_por_id(self, socio_id: UUID) -> Optional[Socio]:
        with self._lock:
            return self._store.get(socio_id)

    def obter_por_email(self, email: str) -> Optional[Socio]:
        with self._lock:
            return next(
                (s for s in self._store.values() if s.email == email),
                None,
            )

    def listar_todos(self) -> List[Socio]:
        with self._lock:
            return list(self._store.values())

    def eliminar(self, socio_id: UUID) -> None:
        with self._lock:
            self._store.pop(socio_id, None)

    def __len__(self):
        return len(self._store)


class InMemoryPlanoTreinoRepository(IPlanoTreinoRepository):
    """Repositório em memória para Planos de Treino."""

    def __init__(self):
        self._store: Dict[UUID, PlanoTreino] = {}
        self._lock = threading.Lock()

    def guardar(self, plano: PlanoTreino) -> None:
        with self._lock:
            self._store[plano.id] = plano

    def obter_por_id(self, plano_id: UUID) -> Optional[PlanoTreino]:
        with self._lock:
            return self._store.get(plano_id)

    def listar_por_socio(self, socio_id: UUID) -> List[PlanoTreino]:
        with self._lock:
            return [p for p in self._store.values() if p.socio_id == socio_id]

    def eliminar(self, plano_id: UUID) -> None:
        with self._lock:
            self._store.pop(plano_id, None)
