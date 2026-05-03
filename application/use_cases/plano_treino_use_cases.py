"""
Casos de Uso: Gestão de Planos de Treino
"""
import logging
from uuid import UUID
from typing import List

from domain.entities.plano_treino import PlanoTreino, Exercicio
from domain.value_objects.nivel_treino import NivelTreino
from domain.value_objects.tipo_exercicio import TipoExercicio
from domain.exceptions.dominio_exceptions import (
    SocioNaoEncontradoException,
    PlanoTreinoNaoEncontradoException,
)
from application.ports.output_ports import (
    IPlanoTreinoRepository,
    ISocioRepository,
    INotificacaoService,
)
from application.dtos.dtos import (
    CriarPlanoTreinoDTO,
    PlanoTreinoResponseDTO,
    ExercicioDTO,
)

logger = logging.getLogger(__name__)


def _exercicio_para_dto(e: Exercicio) -> ExercicioDTO:
    return ExercicioDTO(
        nome=e.nome,
        series=e.series,
        repeticoes=e.repeticoes,
        descanso_segundos=e.descanso_segundos,
        tipo=e.tipo.name,
    )


def _plano_para_dto(plano: PlanoTreino) -> PlanoTreinoResponseDTO:
    return PlanoTreinoResponseDTO(
        id=plano.id,
        nome=plano.nome,
        nivel=plano.nivel.name,
        socio_id=plano.socio_id,
        exercicios=[_exercicio_para_dto(e) for e in plano.exercicios],
        duracao_estimada_minutos=plano.calcular_duracao_estimada_minutos(),
        data_criacao=plano.data_criacao,
        ativo=plano.ativo,
    )


class CriarPlanoTreinoUseCase:
    def __init__(
        self,
        plano_repo: IPlanoTreinoRepository,
        socio_repo: ISocioRepository,
        notificacao_service: INotificacaoService,
    ):
        self._plano_repo = plano_repo
        self._socio_repo = socio_repo
        self._notificacao = notificacao_service

    def executar(self, dto: CriarPlanoTreinoDTO) -> PlanoTreinoResponseDTO:
        socio = self._socio_repo.obter_por_id(dto.socio_id)
        if not socio:
            raise SocioNaoEncontradoException(dto.socio_id)

        plano = PlanoTreino(
            nome=dto.nome,
            nivel=NivelTreino[dto.nivel.upper()],
            socio_id=dto.socio_id,
        )

        for ex_dto in dto.exercicios:
            exercicio = Exercicio(
                nome=ex_dto.nome,
                series=ex_dto.series,
                repeticoes=ex_dto.repeticoes,
                descanso_segundos=ex_dto.descanso_segundos,
                tipo=TipoExercicio[ex_dto.tipo.upper()],
            )
            plano.adicionar_exercicio(exercicio)

        self._plano_repo.guardar(plano)
        self._notificacao.notificar_plano_criado(socio.email, plano.nome)

        logger.info(
            "Plano criado: id=%s, socio_id=%s, exercicios=%d",
            plano.id, dto.socio_id, len(plano.exercicios),
        )
        return _plano_para_dto(plano)


class ListarPlanosPorSocioUseCase:
    def __init__(self, plano_repo: IPlanoTreinoRepository):
        self._repo = plano_repo

    def executar(self, socio_id: UUID) -> List[PlanoTreinoResponseDTO]:
        return [_plano_para_dto(p) for p in self._repo.listar_por_socio(socio_id)]


class ObterPlanoTreinoUseCase:
    def __init__(self, plano_repo: IPlanoTreinoRepository):
        self._repo = plano_repo

    def executar(self, plano_id: UUID) -> PlanoTreinoResponseDTO:
        plano = self._repo.obter_por_id(plano_id)
        if not plano:
            raise PlanoTreinoNaoEncontradoException(plano_id)
        return _plano_para_dto(plano)
