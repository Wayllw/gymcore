"""
Exceções de domínio — pertencem ao Core, não à infraestrutura.
A camada de infraestrutura pode capturá-las mas nunca as define.
"""
from uuid import UUID


class GymCoreException(Exception):
    """Base para todas as exceções de domínio."""
    pass


class SocioNaoEncontradoException(GymCoreException):
    def __init__(self, socio_id: UUID):
        super().__init__(f"Sócio com ID '{socio_id}' não encontrado.")
        self.socio_id = socio_id


class SocioJaExisteException(GymCoreException):
    def __init__(self, email: str):
        super().__init__(f"Já existe um sócio com o email '{email}'.")
        self.email = email

class SocioEmailBrokenException(GymCoreException):
    def __init__(self, email: str):
        super().__init__(f"Email '{email}' é inválido.")
        self.email = email


class SocioInativoException(GymCoreException):
    def __init__(self, socio_id: UUID):
        super().__init__(f"Sócio '{socio_id}' está inativo e não pode ser modificado.")
        self.socio_id = socio_id


class PlanoInvalidoException(GymCoreException):
    def __init__(self, plano):
        super().__init__(f"Plano inválido: '{plano}'.")


class PlanoTreinoNaoEncontradoException(GymCoreException):
    def __init__(self, plano_id: UUID):
        super().__init__(f"Plano de treino com ID '{plano_id}' não encontrado.")
        self.plano_id = plano_id


class PlanoTreinoInvalidoException(GymCoreException):
    def __init__(self, motivo: str):
        super().__init__(f"Plano de treino inválido: {motivo}")
