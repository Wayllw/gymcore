"""
Adaptador de saída: Cliente gRPC com Circuit Breaker — Treinos-Service.

Implementa ISocioValidationClient chamando o Sócios-Service via gRPC
(porta 9001), protegido por um Circuit Breaker (pybreaker).

Porquê Circuit Breaker aqui?
Se o Sócios-Service estiver indisponível ou lento, sem proteção cada
pedido de criação de plano ficaria bloqueado à espera de um timeout,
degradando também o Treinos-Service (falha em cascata). O Circuit
Breaker deteta falhas repetidas, "abre o circuito" e falha rapidamente
durante um período de arrefecimento, dando tempo ao Sócios-Service para
recuperar sem continuar a ser bombardeado com pedidos.

Estados do circuito (pybreaker):
  CLOSED   → tudo normal, pedidos passam.
  OPEN     → falhas excederam o limite; pedidos falham imediatamente
             (CircuitBreakerError) sem tentar a chamada gRPC.
  HALF_OPEN→ após o tempo de reset, deixa passar 1 pedido de teste;
             se for bem sucedido volta a CLOSED, senão volta a OPEN.
"""
import logging

import grpc
import pybreaker

from infrastructure.grpc import socio_validation_pb2 as pb2
from infrastructure.grpc import socio_validation_pb2_grpc as pb2_grpc
from application.ports.output_ports import ISocioValidationClient
from domain.exceptions.dominio_exceptions import SocioValidationIndisponivelException

logger = logging.getLogger(__name__)


class CircuitBreakerLogListener(pybreaker.CircuitBreakerListener):
    """Regista transições de estado do circuito nos logs estruturados."""

    def state_change(self, cb, old_state, new_state):
        logger.warning(
            "🔌 [CIRCUIT-BREAKER:%s] Transição de estado: %s → %s",
            cb.name, old_state.name, new_state.name,
        )

    def failure(self, cb, exc):
        logger.error(
            "🔌 [CIRCUIT-BREAKER:%s] Falha registada (%d/%d) | erro=%s",
            cb.name, cb.fail_counter, cb.fail_max, str(exc),
        )


# Circuit breaker partilhado para todas as chamadas de validação de sócio.
# fail_max=3: após 3 falhas consecutivas, abre o circuito.
# reset_timeout=10: aguarda 10s antes de tentar novamente (HALF_OPEN).
socio_validation_breaker = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=10,
    name="SocioValidationService",
    listeners=[CircuitBreakerLogListener()],
)


class GrpcSocioValidationClient(ISocioValidationClient):

    def __init__(self, host: str = "localhost", porta: int = 9001, timeout_segundos: float = 3.0):
        self._endereco = f"{host}:{porta}"
        self._timeout = timeout_segundos

    @socio_validation_breaker
    def _chamar_grpc(self, socio_id_str: str, correlation_id: str) -> pb2.ValidarSocioResponse:
        """
        Chamada real ao Sócios-Service. Decorada com o circuit breaker:
        cada exceção lançada aqui conta como falha para o pybreaker.
        Cria um canal novo por chamada — simples e robusto para uma POC;
        em produção usar-se-ia um canal persistente com pooling.
        """
        with grpc.insecure_channel(self._endereco) as channel:
            stub = pb2_grpc.SocioValidationServiceStub(channel)
            request = pb2.ValidarSocioRequest(
                socio_id=socio_id_str, correlation_id=correlation_id
            )
            return stub.ValidarSocio(request, timeout=self._timeout)

    def validar_socio(self, socio_id, correlation_id: str):
        socio_id_str = str(socio_id)
        try:
            resposta = self._chamar_grpc(socio_id_str, correlation_id)
            return (resposta.existe, resposta.ativo, resposta.nome, resposta.mensagem)
        except pybreaker.CircuitBreakerError as e:
            logger.error(
                "🔴 [gRPC-CLIENT] Circuito ABERTO — chamada rejeitada sem tentar a rede | "
                "socio_id=%s | correlation_id=%s",
                socio_id_str, correlation_id,
            )
            raise SocioValidationIndisponivelException(
                "circuito aberto — Sócios-Service temporariamente indisponível"
            ) from e
        except grpc.RpcError as e:
            logger.error(
                "🔴 [gRPC-CLIENT] Erro de comunicação | socio_id=%s | erro=%s | correlation_id=%s",
                socio_id_str, e.code() if hasattr(e, "code") else str(e), correlation_id,
            )
            raise SocioValidationIndisponivelException(f"erro gRPC: {e}") from e
