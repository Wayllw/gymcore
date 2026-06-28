"""
Casos de Uso: Gestão de Planos de Treino.

Nota sobre comunicação síncrona (gRPC):
  CriarPlanoTreinoUseCase chama ISocioValidationClient antes de persistir
  qualquer plano. Esta é a validação síncrona que justifica o uso de gRPC
  entre Treinos-Service e Sócios-Service — é preciso ter a certeza, no
  momento do pedido, que o sócio existe e está ativo.

Nota sobre a Saga "Inscrição Completa":
  CriarPlanoInicialUseCase é acionado pelo consumer de eventos do
  Sócios-Service (evento socio.inscrito), não pela API REST. Tenta criar
  um plano de treino padrão (nível INICIANTE) automaticamente. Se a
  validação gRPC falhar (ex: circuito aberto, sócio entretanto suspenso),
  publica plano_inicial.falhou — o Sócios-Service decide então a sua
  própria compensação. Não há transação distribuída: cada serviço reage
  de forma autónoma ao que sabe.
"""
import logging
from uuid import UUID
from typing import List

from domain.entities.plano_treino import PlanoTreino, Exercicio
from domain.value_objects.nivel_treino import NivelTreino
from domain.value_objects.tipo_exercicio import TipoExercicio
from domain.exceptions.dominio_exceptions import (
    PlanoTreinoNaoEncontradoException,
    SocioInvalidoException,
    SocioValidationIndisponivelException,
)
from application.ports.output_ports import (
    IPlanoTreinoRepository,
    ISocioValidationClient,
    IEventPublisher,
)
from application.dtos.dtos import CriarPlanoTreinoDTO, PlanoTreinoResponseDTO, ExercicioDTO

logger = logging.getLogger(__name__)


def _exercicio_para_dto(e: Exercicio) -> ExercicioDTO:
    return ExercicioDTO(
        nome=e.nome, series=e.series, repeticoes=e.repeticoes,
        descanso_segundos=e.descanso_segundos, tipo=e.tipo.name,
    )


def _plano_para_dto(plano: PlanoTreino) -> PlanoTreinoResponseDTO:
    return PlanoTreinoResponseDTO(
        id=plano.id, nome=plano.nome, nivel=plano.nivel.name,
        socio_id=plano.socio_id,
        exercicios=[_exercicio_para_dto(e) for e in plano.exercicios],
        duracao_estimada_minutos=plano.calcular_duracao_estimada_minutos(),
        data_criacao=plano.data_criacao, ativo=plano.ativo,
    )


class CriarPlanoTreinoUseCase:
    """
    Caso de uso exposto via API REST.
    Valida o sócio via gRPC (com circuit breaker) antes de persistir.
    """

    def __init__(
        self,
        plano_repo: IPlanoTreinoRepository,
        socio_validation: ISocioValidationClient,
    ):
        self._plano_repo = plano_repo
        self._validacao = socio_validation

    def executar(self, dto: CriarPlanoTreinoDTO, correlation_id: str) -> PlanoTreinoResponseDTO:
        existe, ativo, nome, mensagem = self._validacao.validar_socio(
            dto.socio_id, correlation_id
        )
        if not existe or not ativo:
            raise SocioInvalidoException(dto.socio_id, mensagem)

        plano = PlanoTreino(nome=dto.nome, nivel=NivelTreino[dto.nivel.upper()], socio_id=dto.socio_id)
        for ex_dto in dto.exercicios:
            plano.adicionar_exercicio(Exercicio(
                nome=ex_dto.nome, series=ex_dto.series, repeticoes=ex_dto.repeticoes,
                descanso_segundos=ex_dto.descanso_segundos, tipo=TipoExercicio[ex_dto.tipo.upper()],
            ))

        self._plano_repo.guardar(plano)
        logger.info(
            "Plano criado: id=%s, socio_id=%s, exercicios=%d | correlation_id=%s",
            plano.id, dto.socio_id, len(plano.exercicios), correlation_id,
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


class CriarPlanoInicialUseCase:
    """
    Participante da Saga "Inscrição Completa".

    Acionado pelo consumer de eventos (socio.inscrito), não pela API REST.
    Tenta criar um plano de treino padrão. Em caso de falha na validação
    gRPC (sócio inexistente, suspenso, ou circuito aberto), publica o
    evento de compensação plano_inicial.falhou.
    """

    PLANO_PADRAO_NOME = "Plano Inicial de Adaptação"
    EXERCICIOS_PADRAO = [
        {"nome": "Caminhada na passadeira", "series": 1, "repeticoes": 1,
         "descanso_segundos": 0, "tipo": "CARDIO"},
        {"nome": "Leg press", "series": 3, "repeticoes": 12,
         "descanso_segundos": 60, "tipo": "FORCA"},
        {"nome": "Alongamento geral", "series": 1, "repeticoes": 1,
         "descanso_segundos": 0, "tipo": "FLEXIBILIDADE"},
    ]

    def __init__(
        self,
        plano_repo: IPlanoTreinoRepository,
        socio_validation: ISocioValidationClient,
        event_publisher: IEventPublisher,
    ):
        self._plano_repo = plano_repo
        self._validacao = socio_validation
        self._eventos = event_publisher

    def executar(self, socio_id: UUID, correlation_id: str) -> None:
        try:
            existe, ativo, nome, mensagem = self._validacao.validar_socio(socio_id, correlation_id)
        except SocioValidationIndisponivelException as e:
            logger.error(
                "🔴 [SAGA] Validação indisponível (circuito aberto?) | socio_id=%s | "
                "erro=%s | correlation_id=%s",
                socio_id, str(e), correlation_id,
            )
            self._publicar_falha(socio_id, f"validacao_indisponivel: {e}", correlation_id)
            return

        if not existe or not ativo:
            logger.warning(
                "🟡 [SAGA] Sócio inválido para plano inicial | socio_id=%s | "
                "motivo=%s | correlation_id=%s",
                socio_id, mensagem, correlation_id,
            )
            self._publicar_falha(socio_id, mensagem, correlation_id)
            return

        plano = PlanoTreino(
            nome=self.PLANO_PADRAO_NOME,
            nivel=NivelTreino.INICIANTE,
            socio_id=socio_id,
        )
        for ex in self.EXERCICIOS_PADRAO:
            plano.adicionar_exercicio(Exercicio(
                nome=ex["nome"], series=ex["series"], repeticoes=ex["repeticoes"],
                descanso_segundos=ex["descanso_segundos"], tipo=TipoExercicio[ex["tipo"]],
            ))

        self._plano_repo.guardar(plano)
        logger.info(
            "✅ [SAGA] Plano inicial criado | plano_id=%s | socio_id=%s | correlation_id=%s",
            plano.id, socio_id, correlation_id,
        )
        self._eventos.publicar(
            tipo_evento="plano_inicial.criado",
            payload={"socio_id": str(socio_id), "plano_id": str(plano.id)},
            correlation_id=correlation_id,
        )

    def _publicar_falha(self, socio_id: UUID, motivo: str, correlation_id: str) -> None:
        self._eventos.publicar(
            tipo_evento="plano_inicial.falhou",
            payload={"socio_id": str(socio_id), "motivo": motivo},
            correlation_id=correlation_id,
        )
