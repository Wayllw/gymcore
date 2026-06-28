"""
Exceções de domínio do Treinos-Service — pertencem ao Core, não à infraestrutura.
"""
from uuid import UUID


class TreinosServiceException(Exception):
    """Base para todas as exceções de domínio deste serviço."""
    pass


class PlanoTreinoNaoEncontradoException(TreinosServiceException):
    def __init__(self, plano_id):
        super().__init__(f"Plano de treino com ID '{plano_id}' não encontrado.")
        self.plano_id = plano_id


class PlanoTreinoInvalidoException(TreinosServiceException):
    def __init__(self, motivo: str):
        super().__init__(f"Plano de treino inválido: {motivo}")


class SocioInvalidoException(TreinosServiceException):
    """
    Lançada quando a validação remota (gRPC) ao Sócios-Service indica
    que o sócio não existe ou não está ativo.
    """
    def __init__(self, socio_id, motivo: str):
        super().__init__(f"Sócio '{socio_id}' inválido para criação de plano: {motivo}")
        self.socio_id = socio_id


class SocioValidationIndisponivelException(TreinosServiceException):
    """
    Lançada quando o circuit breaker está aberto ou a chamada gRPC ao
    Sócios-Service falha (timeout, indisponibilidade, etc.).
    """
    def __init__(self, motivo: str):
        super().__init__(f"Validação de sócio indisponível: {motivo}")
