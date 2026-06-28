"""
Adaptador de saída: Repositório SQLite para Sócios.

Database-per-Service: este é o ÚNICO ponto de acesso aos dados de Sócios
em todo o sistema. Nenhum outro serviço acede a este ficheiro directamente —
o Treinos-Service só pode obter dados de um sócio via gRPC (ValidarSocio)
ou subscrevendo eventos publicados por este serviço.

Implementa ISocioRepository — o Core (domain/application) não sabe que
existe SQLite, poderia ser PostgreSQL ou outra coisa qualquer sem alterar
uma linha de use case.
"""
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional
from uuid import UUID
from datetime import date

from application.ports.output_ports import ISocioRepository
from domain.entities.socio import Socio
from domain.value_objects.plano_mensalidade import PlanoMensalidade
from domain.value_objects.estado_socio import EstadoSocio


class SqliteSocioRepository(ISocioRepository):

    def __init__(self, caminho_bd: str = "dados/socios.db"):
        self._caminho = Path(caminho_bd)
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._criar_schema()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._caminho), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _criar_schema(self) -> None:
        with self._lock, self._conectar() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS socios (
                    id TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    data_nascimento TEXT NOT NULL,
                    plano TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    data_inscricao TEXT NOT NULL
                )
            """)
            conn.commit()

    def _row_para_socio(self, row: sqlite3.Row) -> Socio:
        socio = Socio(
            nome=row["nome"],
            email=row["email"],
            data_nascimento=date.fromisoformat(row["data_nascimento"]),
            plano=PlanoMensalidade[row["plano"]],
        )
        socio.id = UUID(row["id"])
        socio.estado = EstadoSocio[row["estado"]]
        socio.data_inscricao = date.fromisoformat(row["data_inscricao"])
        return socio

    def guardar(self, socio: Socio) -> None:
        with self._lock, self._conectar() as conn:
            conn.execute("""
                INSERT INTO socios (id, nome, email, data_nascimento, plano, estado, data_inscricao)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    nome=excluded.nome, email=excluded.email,
                    data_nascimento=excluded.data_nascimento,
                    plano=excluded.plano, estado=excluded.estado,
                    data_inscricao=excluded.data_inscricao
            """, (
                str(socio.id), socio.nome, socio.email,
                socio.data_nascimento.isoformat(), socio.plano.name,
                socio.estado.name, socio.data_inscricao.isoformat(),
            ))
            conn.commit()

    def obter_por_id(self, socio_id: UUID) -> Optional[Socio]:
        with self._lock, self._conectar() as conn:
            row = conn.execute(
                "SELECT * FROM socios WHERE id = ?", (str(socio_id),)
            ).fetchone()
            return self._row_para_socio(row) if row else None

    def obter_por_email(self, email: str) -> Optional[Socio]:
        with self._lock, self._conectar() as conn:
            row = conn.execute(
                "SELECT * FROM socios WHERE email = ?", (email,)
            ).fetchone()
            return self._row_para_socio(row) if row else None

    def listar_todos(self) -> List[Socio]:
        with self._lock, self._conectar() as conn:
            rows = conn.execute("SELECT * FROM socios").fetchall()
            return [self._row_para_socio(r) for r in rows]

    def eliminar(self, socio_id: UUID) -> None:
        with self._lock, self._conectar() as conn:
            conn.execute("DELETE FROM socios WHERE id = ?", (str(socio_id),))
            conn.commit()
