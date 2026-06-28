"""
Adaptador de saída: Repositório SQLite para Planos de Treino.

Database-per-Service: este é o ÚNICO ponto de acesso aos dados de Planos
de Treino em todo o sistema. Note-se que socio_id é guardado como simples
TEXT — não há FOREIGN KEY para a BD de Sócios porque essa BD pertence a
outro serviço e está fisicamente separada (princípio fundamental do
padrão Database-per-Service).
"""
import json
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional
from uuid import UUID
from datetime import date

from application.ports.output_ports import IPlanoTreinoRepository
from domain.entities.plano_treino import PlanoTreino, Exercicio
from domain.value_objects.nivel_treino import NivelTreino
from domain.value_objects.tipo_exercicio import TipoExercicio


class SqlitePlanoTreinoRepository(IPlanoTreinoRepository):

    def __init__(self, caminho_bd: str = "dados/treinos.db"):
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
                CREATE TABLE IF NOT EXISTS planos_treino (
                    id TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    nivel TEXT NOT NULL,
                    socio_id TEXT NOT NULL,
                    data_criacao TEXT NOT NULL,
                    ativo INTEGER NOT NULL,
                    exercicios_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_planos_socio_id ON planos_treino(socio_id)
            """)
            conn.commit()

    def _exercicio_para_dict(self, e: Exercicio) -> dict:
        return {
            "nome": e.nome, "series": e.series, "repeticoes": e.repeticoes,
            "descanso_segundos": e.descanso_segundos, "tipo": e.tipo.name,
        }

    def _dict_para_exercicio(self, d: dict) -> Exercicio:
        return Exercicio(
            nome=d["nome"], series=d["series"], repeticoes=d["repeticoes"],
            descanso_segundos=d["descanso_segundos"], tipo=TipoExercicio[d["tipo"]],
        )

    def _row_para_plano(self, row: sqlite3.Row) -> PlanoTreino:
        exercicios_data = json.loads(row["exercicios_json"])
        exercicios = [self._dict_para_exercicio(e) for e in exercicios_data]
        plano = PlanoTreino(
            nome=row["nome"],
            nivel=NivelTreino[row["nivel"]],
            socio_id=UUID(row["socio_id"]),
            exercicios=exercicios,
        )
        plano.id = UUID(row["id"])
        plano.data_criacao = date.fromisoformat(row["data_criacao"])
        plano.ativo = bool(row["ativo"])
        return plano

    def guardar(self, plano: PlanoTreino) -> None:
        exercicios_json = json.dumps([self._exercicio_para_dict(e) for e in plano.exercicios])
        with self._lock, self._conectar() as conn:
            conn.execute("""
                INSERT INTO planos_treino (id, nome, nivel, socio_id, data_criacao, ativo, exercicios_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    nome=excluded.nome, nivel=excluded.nivel,
                    socio_id=excluded.socio_id, data_criacao=excluded.data_criacao,
                    ativo=excluded.ativo, exercicios_json=excluded.exercicios_json
            """, (
                str(plano.id), plano.nome, plano.nivel.name, str(plano.socio_id),
                plano.data_criacao.isoformat(), int(plano.ativo), exercicios_json,
            ))
            conn.commit()

    def obter_por_id(self, plano_id: UUID) -> Optional[PlanoTreino]:
        with self._lock, self._conectar() as conn:
            row = conn.execute(
                "SELECT * FROM planos_treino WHERE id = ?", (str(plano_id),)
            ).fetchone()
            return self._row_para_plano(row) if row else None

    def listar_por_socio(self, socio_id: UUID) -> List[PlanoTreino]:
        with self._lock, self._conectar() as conn:
            rows = conn.execute(
                "SELECT * FROM planos_treino WHERE socio_id = ?", (str(socio_id),)
            ).fetchall()
            return [self._row_para_plano(r) for r in rows]

    def eliminar(self, plano_id: UUID) -> None:
        with self._lock, self._conectar() as conn:
            conn.execute("DELETE FROM planos_treino WHERE id = ?", (str(plano_id),))
            conn.commit()
