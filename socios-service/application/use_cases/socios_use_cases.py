"""
Casos de Uso: Gestão de Sócios.

Nota sobre a Saga "Inscrição Completa":
  InscreverSocioUseCase publica o evento `socio.inscrito` via IEventPublisher.
  O Treinos-Service subscreve este evento e cria um plano de treino inicial.
  Se essa criação falhar, o Treinos-Service publica `plano_inicial.falhou`,
  que este serviço escuta (ver consumer dedicado) para aplicar uma ação de
  compensação (ex: marcar o sócio para acompanhamento manual).
  Não existe transação distribuída — cada serviço gere a sua própria
  consistência local e reage a eventos (Saga coreografada).
"""
import logging
from uuid import UUID
from typing import List

from domain.entities.socio import Socio
from domain.value_objects.plano_mensalidade import PlanoMensalidade
from domain.exceptions.dominio_exceptions import (
    SocioNaoEncontradoException,
    SocioJaExisteException,
)
from application.ports.output_ports import ISocioRepository, IEventPublisher
from application.dtos.dtos import InscreverSocioDTO, SocioResponseDTO

logger = logging.getLogger(__name__)


def _socio_para_dto(socio: Socio) -> SocioResponseDTO:
    return SocioResponseDTO(
        id=socio.id,
        nome=socio.nome,
        email=socio.email,
        plano=socio.plano.name,
        estado=socio.estado.name,
        idade=socio.idade,
        mensalidade=socio.calcular_mensalidade(),
        data_inscricao=socio.data_inscricao,
    )


class InscreverSocioUseCase:
    """
    Regista um novo sócio e publica o evento socio.inscrito.
    Este evento desencadeia a Saga de "Inscrição Completa" no Treinos-Service.
    """

    def __init__(self, socio_repo: ISocioRepository, event_publisher: IEventPublisher):
        self._repo = socio_repo
        self._eventos = event_publisher

    def executar(self, dto: InscreverSocioDTO, correlation_id: str) -> SocioResponseDTO:
        existente = self._repo.obter_por_email(dto.email)
        if existente:
            raise SocioJaExisteException(dto.email)

        plano = PlanoMensalidade[dto.plano.upper()]
        socio = Socio(
            nome=dto.nome,
            email=dto.email,
            data_nascimento=dto.data_nascimento,
            plano=plano,
        )

        self._repo.guardar(socio)

        # Publicar evento — desencadeia a Saga no Treinos-Service
        self._eventos.publicar(
            tipo_evento="socio.inscrito",
            payload={
                "socio_id": str(socio.id),
                "nome": socio.nome,
                "email": socio.email,
            },
            correlation_id=correlation_id,
        )

        logger.info(
            "Sócio inscrito: id=%s, email=%s | correlation_id=%s",
            socio.id, socio.email, correlation_id,
        )
        return _socio_para_dto(socio)


class ObterSocioUseCase:
    def __init__(self, socio_repo: ISocioRepository):
        self._repo = socio_repo

    def executar(self, socio_id: UUID) -> SocioResponseDTO:
        socio = self._repo.obter_por_id(socio_id)
        if not socio:
            raise SocioNaoEncontradoException(socio_id)
        return _socio_para_dto(socio)


class ListarSociosUseCase:
    def __init__(self, socio_repo: ISocioRepository):
        self._repo = socio_repo

    def executar(self) -> List[SocioResponseDTO]:
        return [_socio_para_dto(s) for s in self._repo.listar_todos()]


class AtualizarPlanoSocioUseCase:
    def __init__(self, socio_repo: ISocioRepository):
        self._repo = socio_repo

    def executar(self, socio_id: UUID, novo_plano: str) -> SocioResponseDTO:
        socio = self._repo.obter_por_id(socio_id)
        if not socio:
            raise SocioNaoEncontradoException(socio_id)
        socio.atualizar_plano(PlanoMensalidade[novo_plano.upper()])
        self._repo.guardar(socio)
        logger.info("Plano atualizado: id=%s, novo_plano=%s", socio_id, novo_plano)
        return _socio_para_dto(socio)


class SuspenderSocioUseCase:
    def __init__(self, socio_repo: ISocioRepository):
        self._repo = socio_repo

    def executar(self, socio_id: UUID) -> SocioResponseDTO:
        socio = self._repo.obter_por_id(socio_id)
        if not socio:
            raise SocioNaoEncontradoException(socio_id)
        socio.suspender()
        self._repo.guardar(socio)
        logger.info("Sócio suspenso: id=%s", socio_id)
        return _socio_para_dto(socio)


class MarcarParaAcompanhamentoUseCase:
    """
    Ação de compensação da Saga.
    Chamado quando o Treinos-Service não conseguiu criar o plano de treino
    inicial. Não desfaz a inscrição (seria um rollback distribuído clássico
    e frágil) — em vez disso, marca o sócio para acompanhamento manual por
    um funcionário do ginásio. Esta é a essência de uma Saga coreografada:
    cada serviço decide a sua própria forma de reagir à falha do outro.
    """

    def __init__(self, socio_repo: ISocioRepository):
        self._repo = socio_repo
        self._marcados: set = set()  # simplificação em memória para a POC

    def executar(self, socio_id: UUID, motivo: str, correlation_id: str) -> None:
        socio = self._repo.obter_por_id(socio_id)
        if not socio:
            logger.warning(
                "Compensação ignorada — sócio %s não encontrado | correlation_id=%s",
                socio_id, correlation_id,
            )
            return
        self._marcados.add(str(socio_id))
        logger.warning(
            "🔧 [SAGA-COMPENSACAO] Sócio %s marcado para acompanhamento manual | "
            "motivo=%s | correlation_id=%s",
            socio_id, motivo, correlation_id,
        )

    def esta_marcado(self, socio_id: UUID) -> bool:
        return str(socio_id) in self._marcados
