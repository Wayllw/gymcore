"""
Caso de Uso: Geração de Relatório de Sócio.

NOTA ARQUITETURAL IMPORTANTE:
Este é o processo "pesado" do sistema — na Fase 1 é simulado (apenas log).
Na Fase 2, este use case vai invocar um Worker assíncrono via fila de mensagens.
A interface IRelatorioService garante que o Core não precisa mudar nada — 
apenas a implementação da infraestrutura é substituída (DIP em ação).
"""
import logging
from uuid import UUID

from domain.exceptions.dominio_exceptions import SocioNaoEncontradoException
from application.ports.output_ports import ISocioRepository, IRelatorioService

logger = logging.getLogger(__name__)


class GerarRelatorioSocioUseCase:
    """
    Gera um relatório completo de um sócio.
    Fase 1: simulado — execução síncrona e lenta (simula 2s).
    Fase 2: será delegado a um Worker assíncrono via fila.
    """

    def __init__(
        self,
        socio_repo: ISocioRepository,
        relatorio_service: IRelatorioService,
    ):
        self._repo = socio_repo
        self._relatorio = relatorio_service

    def executar(self, socio_id: UUID) -> str:
        socio = self._repo.obter_por_id(socio_id)
        if not socio:
            raise SocioNaoEncontradoException(socio_id)

        logger.info(
            "A iniciar geração de relatório para sócio: id=%s — "
            "[FASE 1: síncrono | FASE 2: será assíncrono via Worker]",
            socio_id,
        )
        resultado = self._relatorio.gerar_relatorio_socio(socio_id)
        logger.info("Relatório gerado: %s", resultado)
        return resultado
