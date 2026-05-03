"""
Casos de Uso: Gestão de Sócios
Orquestra as entidades de domínio usando os portos definidos.
Não conhece Flask, ficheiros, nem qualquer detalhe de infraestrutura.
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
from application.ports.output_ports import ISocioRepository, INotificacaoService
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
    Regista um novo sócio no sistema.
    Depende de ISocioRepository e INotificacaoService (abstrações, não implementações).
    """

    def __init__(
        self,
        socio_repo: ISocioRepository,
        notificacao_service: INotificacaoService,
    ):
        self._repo = socio_repo
        self._notificacao = notificacao_service

    def executar(self, dto: InscreverSocioDTO) -> SocioResponseDTO:
        # Verificar duplicado
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
        self._notificacao.enviar_boas_vindas(socio.email, socio.nome)

        logger.info("Sócio inscrito: id=%s, email=%s", socio.id, socio.email)
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
