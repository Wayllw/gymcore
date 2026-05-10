"""
Repositórios com persistência em ficheiros JSON.

Substituem os repositórios em memória sem tocar no Core.
Implementam exactamente as mesmas interfaces (ISocioRepository, IPlanoTreinoRepository)
— o container.py é o único sítio que precisa de ser alterado.

Ficheiros gerados:
  dados/socios.json
  dados/planos.json
"""
import json
import threading
from pathlib import Path
from uuid import UUID
from typing import List, Optional
from datetime import date

from application.ports.output_ports import ISocioRepository, IPlanoTreinoRepository
from domain.entities.socio import Socio
from domain.entities.plano_treino import PlanoTreino, Exercicio
from domain.value_objects.plano_mensalidade import PlanoMensalidade
from domain.value_objects.estado_socio import EstadoSocio
from domain.value_objects.nivel_treino import NivelTreino
from domain.value_objects.tipo_exercicio import TipoExercicio


# ─── JsonSocioRepository ──────────────────────────────────────────────────────

class JsonSocioRepository(ISocioRepository):
    """
    Repositório de Sócios com persistência em ficheiro JSON.

    Cada operação lê e escreve o ficheiro completo — simples e correcto
    para o volume de dados do enunciado. Para volumes maiores usaria-se
    uma base de dados (Fase 3).

    Thread-safe via threading.Lock (mesmo comportamento do InMemoryRepo).
    """

    def __init__(self, caminho: str = "dados/socios.json"):
        self._caminho = Path(caminho)
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Criar ficheiro vazio se não existir
        if not self._caminho.exists():
            self._caminho.write_text("[]", encoding="utf-8")

    # ── Serialização ──────────────────────────────────────────────────────────

    def _socio_para_dict(self, socio: Socio) -> dict:
        return {
            "id": str(socio.id),
            "nome": socio.nome,
            "email": socio.email,
            "data_nascimento": socio.data_nascimento.isoformat(),
            "plano": socio.plano.name,
            "estado": socio.estado.name,
            "data_inscricao": socio.data_inscricao.isoformat(),
        }

    def _dict_para_socio(self, d: dict) -> Socio:
        socio = Socio(
            nome=d["nome"],
            email=d["email"],
            data_nascimento=date.fromisoformat(d["data_nascimento"]),
            plano=PlanoMensalidade[d["plano"]],
        )
        # Repor campos gerados automaticamente com os valores guardados
        socio.id = UUID(d["id"])
        socio.estado = EstadoSocio[d["estado"]]
        socio.data_inscricao = date.fromisoformat(d["data_inscricao"])
        return socio

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _ler(self) -> List[dict]:
        """Lê todos os registos do ficheiro JSON."""
        return json.loads(self._caminho.read_text(encoding="utf-8"))

    def _escrever(self, registos: List[dict]) -> None:
        """Escreve todos os registos no ficheiro JSON (substituição atómica)."""
        self._caminho.write_text(
            json.dumps(registos, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Interface ISocioRepository ────────────────────────────────────────────

    def guardar(self, socio: Socio) -> None:
        """Cria ou actualiza um sócio (upsert por id)."""
        with self._lock:
            registos = self._ler()
            # Remove entrada antiga se existir (update)
            registos = [r for r in registos if r["id"] != str(socio.id)]
            registos.append(self._socio_para_dict(socio))
            self._escrever(registos)

    def obter_por_id(self, socio_id: UUID) -> Optional[Socio]:
        with self._lock:
            for r in self._ler():
                if r["id"] == str(socio_id):
                    return self._dict_para_socio(r)
        return None

    def obter_por_email(self, email: str) -> Optional[Socio]:
        with self._lock:
            for r in self._ler():
                if r["email"] == email:
                    return self._dict_para_socio(r)
        return None

    def listar_todos(self) -> List[Socio]:
        with self._lock:
            return [self._dict_para_socio(r) for r in self._ler()]

    def eliminar(self, socio_id: UUID) -> None:
        with self._lock:
            registos = self._ler()
            registos = [r for r in registos if r["id"] != str(socio_id)]
            self._escrever(registos)


# ─── JsonPlanoTreinoRepository ────────────────────────────────────────────────

class JsonPlanoTreinoRepository(IPlanoTreinoRepository):
    """
    Repositório de Planos de Treino com persistência em ficheiro JSON.

    Serializa a entidade PlanoTreino completa, incluindo a lista de
    Exercicios com todos os seus campos e value objects (NivelTreino,
    TipoExercicio).

    Thread-safe via threading.Lock.
    """

    def __init__(self, caminho: str = "dados/planos.json"):
        self._caminho = Path(caminho)
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self._caminho.exists():
            self._caminho.write_text("[]", encoding="utf-8")

    # ── Serialização ──────────────────────────────────────────────────────────

    def _exercicio_para_dict(self, exercicio: Exercicio) -> dict:
        return {
            "nome": exercicio.nome,
            "series": exercicio.series,
            "repeticoes": exercicio.repeticoes,
            "descanso_segundos": exercicio.descanso_segundos,
            "tipo": exercicio.tipo.name,
        }

    def _dict_para_exercicio(self, d: dict) -> Exercicio:
        return Exercicio(
            nome=d["nome"],
            series=d["series"],
            repeticoes=d["repeticoes"],
            descanso_segundos=d["descanso_segundos"],
            tipo=TipoExercicio[d["tipo"]],
        )

    def _plano_para_dict(self, plano: PlanoTreino) -> dict:
        return {
            "id": str(plano.id),
            "nome": plano.nome,
            "nivel": plano.nivel.name,
            "socio_id": str(plano.socio_id),
            "data_criacao": plano.data_criacao.isoformat(),
            "ativo": plano.ativo,
            "exercicios": [self._exercicio_para_dict(e) for e in plano.exercicios],
        }

    def _dict_para_plano(self, d: dict) -> PlanoTreino:
        exercicios = [self._dict_para_exercicio(e) for e in d.get("exercicios", [])]
        plano = PlanoTreino(
            nome=d["nome"],
            nivel=NivelTreino[d["nivel"]],
            socio_id=UUID(d["socio_id"]),
            exercicios=exercicios,
        )
        # Repor campos gerados automaticamente com os valores guardados
        plano.id = UUID(d["id"])
        plano.data_criacao = date.fromisoformat(d["data_criacao"])
        plano.ativo = d["ativo"]
        return plano

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _ler(self) -> List[dict]:
        return json.loads(self._caminho.read_text(encoding="utf-8"))

    def _escrever(self, registos: List[dict]) -> None:
        self._caminho.write_text(
            json.dumps(registos, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Interface IPlanoTreinoRepository ──────────────────────────────────────

    def guardar(self, plano: PlanoTreino) -> None:
        """Cria ou actualiza um plano de treino (upsert por id)."""
        with self._lock:
            registos = self._ler()
            registos = [r for r in registos if r["id"] != str(plano.id)]
            registos.append(self._plano_para_dict(plano))
            self._escrever(registos)

    def obter_por_id(self, plano_id: UUID) -> Optional[PlanoTreino]:
        with self._lock:
            for r in self._ler():
                if r["id"] == str(plano_id):
                    return self._dict_para_plano(r)
        return None

    def listar_por_socio(self, socio_id: UUID) -> List[PlanoTreino]:
        with self._lock:
            return [
                self._dict_para_plano(r)
                for r in self._ler()
                if r["socio_id"] == str(socio_id)
            ]

    def eliminar(self, plano_id: UUID) -> None:
        with self._lock:
            registos = self._ler()
            registos = [r for r in registos if r["id"] != str(plano_id)]
            self._escrever(registos)