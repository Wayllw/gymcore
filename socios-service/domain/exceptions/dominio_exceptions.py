"""
Exceções de domínio do Sócios-Service — pertencem ao Core, não à infraestrutura.
"""
from uuid import UUID


class SociosServiceException(Exception):
    """Base para todas as exceções de domínio deste serviço."""
    pass


class SocioNaoEncontradoException(SociosServiceException):
    def __init__(self, socio_id):
        super().__init__(f"Sócio com ID '{socio_id}' não encontrado.")
        self.socio_id = socio_id


class SocioJaExisteException(SociosServiceException):
    def __init__(self, email: str):
        super().__init__(f"Já existe um sócio com o email '{email}'.")
        self.email = email


class SocioInativoException(SociosServiceException):
    def __init__(self, socio_id):
        super().__init__(f"Sócio '{socio_id}' está inativo e não pode ser modificado.")
        self.socio_id = socio_id


class PlanoInvalidoException(SociosServiceException):
    def __init__(self, plano):
        super().__init__(f"Plano inválido: '{plano}'.")
