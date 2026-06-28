"""
Adaptador de entrada: Servidor gRPC do Sócios-Service.

Expõe SocioValidationService na porta 9001. É chamado pelo Treinos-Service
antes de criar um plano de treino, para garantir que o sócio existe e está
ativo — uma validação síncrona de baixa latência entre dois serviços.

Porquê gRPC e não REST aqui?
Esta chamada acontece em todos os pedidos de criação de plano — é tráfego
interno e frequente. O protobuf é mais compacto e rápido a (des)serializar
que JSON, e o contrato fortemente tipado evita erros de integração.
REST continua a ser usado para tudo o que é exposto a clientes externos.
"""
import logging
from concurrent import futures

import grpc

from infrastructure.grpc import socio_validation_pb2 as pb2
from infrastructure.grpc import socio_validation_pb2_grpc as pb2_grpc
from application.ports.output_ports import ISocioRepository

logger = logging.getLogger(__name__)


class SocioValidationServicer(pb2_grpc.SocioValidationServiceServicer):

    def __init__(self, socio_repo: ISocioRepository):
        self._repo = socio_repo

    def ValidarSocio(self, request, context):
        from uuid import UUID
        cid = request.correlation_id or "-"
        logger.info(
            "📡 [gRPC] ValidarSocio recebido | socio_id=%s | correlation_id=%s",
            request.socio_id, cid,
        )
        try:
            socio = self._repo.obter_por_id(UUID(request.socio_id))
        except ValueError:
            return pb2.ValidarSocioResponse(
                existe=False, ativo=False, nome="", estado="",
                mensagem=f"socio_id inválido: '{request.socio_id}'",
            )

        if not socio:
            logger.warning(
                "📡 [gRPC] Sócio não encontrado | socio_id=%s | correlation_id=%s",
                request.socio_id, cid,
            )
            return pb2.ValidarSocioResponse(
                existe=False, ativo=False, nome="", estado="",
                mensagem="Sócio não encontrado.",
            )

        ativo = socio.estado.name == "ATIVO"
        logger.info(
            "📡 [gRPC] Sócio validado | socio_id=%s | ativo=%s | correlation_id=%s",
            request.socio_id, ativo, cid,
        )
        return pb2.ValidarSocioResponse(
            existe=True,
            ativo=ativo,
            nome=socio.nome,
            estado=socio.estado.name,
            mensagem="OK" if ativo else f"Sócio está {socio.estado.name}, não pode criar plano.",
        )


def criar_servidor_grpc(socio_repo: ISocioRepository, porta: int = 9001) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_SocioValidationServiceServicer_to_server(
        SocioValidationServicer(socio_repo), server
    )
    server.add_insecure_port(f"[::]:{porta}")
    return server
