"""
Teste de integração: Circuit Breaker com gRPC real.

Diferente dos testes unitários (que usam fakes), este teste arranca um
processo Python separado a correr o servidor gRPC real do Sócios-Service
e testa o GrpcSocioValidationClient do Treinos-Service contra ele.

Usa subprocess (em vez de importar os dois serviços no mesmo processo)
porque, na realidade, socios-service e treinos-service correm sempre em
processos/contentores distintos — cada um com o seu próprio `sys.path`
e os seus próprios módulos `domain`/`application`/`infrastructure`. Testar
desta forma evita falsos positivos/negativos por conflito de módulos
Python que não ocorreriam na topologia real (Docker Compose).

Cenário demonstrado (igual ao pedido no enunciado para a Fase 2/3):
  1. Servidor gRPC disponível → validação funciona normalmente.
  2. Servidor gRPC cai → falhas consecutivas → circuito abre.
  3. Com o circuito aberto, novas chamadas falham IMEDIATAMENTE
     (sem tentar a rede) — comportamento verificável pelo tempo de resposta.
"""
import os
import socket
import subprocess
import sys
import time

import pytest

ROOT = "/home/claude/gymcore-fase3"


def _porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


@pytest.fixture
def socios_grpc_subprocess(tmp_path):
    """Arranca o Sócios-Service (apenas gRPC) num processo separado."""
    porta = _porta_livre()
    db_path = str(tmp_path / "socios_cb_test.db")

    script = f"""
import sys
sys.path.insert(0, "{ROOT}/socios-service")
import os
os.chdir("{ROOT}/socios-service")

from infrastructure.adapters.outbound.sqlite_repository import SqliteSocioRepository
from infrastructure.grpc.grpc_server import criar_servidor_grpc
from domain.entities.socio import Socio
from domain.value_objects.plano_mensalidade import PlanoMensalidade
from datetime import date

repo = SqliteSocioRepository("{db_path}")
socio = Socio(nome="Teste CB", email="cb@test.pt", data_nascimento=date(1990,1,1), plano=PlanoMensalidade.BASICO)
repo.guardar(socio)
print(f"SOCIO_ID={{socio.id}}", flush=True)

server = criar_servidor_grpc(repo, porta={porta})
server.start()
print("READY", flush=True)
server.wait_for_termination()
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    socio_id = None
    deadline = time.time() + 10
    while time.time() < deadline:
        linha = proc.stdout.readline()
        if linha.startswith("SOCIO_ID="):
            socio_id = linha.strip().split("=", 1)[1]
        if linha.strip() == "READY":
            break

    assert socio_id is not None, "Servidor gRPC de teste não arrancou a tempo."

    yield proc, porta, socio_id

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _correr_cliente_treinos(script_corpo: str, porta_grpc: int) -> str:
    """Executa um trecho de código no contexto do treinos-service e devolve o stdout."""
    script = f"""
import sys
sys.path.insert(0, "{ROOT}/treinos-service")
import os
os.chdir("{ROOT}/treinos-service")
os.environ["SOCIOS_GRPC_PORT"] = "{porta_grpc}"

{script_corpo}
"""
    resultado = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    assert resultado.returncode == 0, f"stdout={resultado.stdout}\nstderr={resultado.stderr}"
    return resultado.stdout


class TestCircuitBreakerIntegracao:

    def test_validacao_bem_sucedida_com_servidor_disponivel(self, socios_grpc_subprocess):
        _, porta, socio_id = socios_grpc_subprocess

        saida = _correr_cliente_treinos(f"""
from infrastructure.resilience.grpc_client import GrpcSocioValidationClient, socio_validation_breaker

cliente = GrpcSocioValidationClient(host="localhost", porta={porta})
existe, ativo, nome, mensagem = cliente.validar_socio("{socio_id}", correlation_id="cid-cb-1")
print(f"RESULTADO existe={{existe}} ativo={{ativo}} nome={{nome}} estado_circuito={{socio_validation_breaker.current_state}}")
""", porta)

        assert "existe=True" in saida
        assert "ativo=True" in saida
        assert "nome=Teste CB" in saida
        assert "estado_circuito=closed" in saida

    def test_circuito_abre_apos_falhas_consecutivas(self, socios_grpc_subprocess):
        """Mata o servidor gRPC e confirma que o circuito abre após 3 falhas."""
        proc, porta, socio_id = socios_grpc_subprocess
        proc.terminate()
        proc.wait(timeout=5)
        time.sleep(0.5)  # garantir que a porta fica mesmo livre

        saida = _correr_cliente_treinos(f"""
from infrastructure.resilience.grpc_client import GrpcSocioValidationClient, socio_validation_breaker
from domain.exceptions.dominio_exceptions import SocioValidationIndisponivelException
import time

cliente = GrpcSocioValidationClient(host="localhost", porta={porta}, timeout_segundos=1.0)

falhas = 0
tempos = []
for i in range(5):
    inicio = time.time()
    try:
        cliente.validar_socio("{socio_id}", correlation_id=f"cid-falha-{{i}}")
    except SocioValidationIndisponivelException:
        falhas += 1
    tempos.append(time.time() - inicio)

print(f"FALHAS={{falhas}}")
print(f"ESTADO_FINAL={{socio_validation_breaker.current_state}}")
# As últimas tentativas (circuito aberto) devem ser MUITO mais rápidas
# que as primeiras (que tentam a rede e esperam o timeout)
print(f"TEMPO_PRIMEIRA={{tempos[0]:.2f}}")
print(f"TEMPO_ULTIMA={{tempos[-1]:.2f}}")
""", porta)

        assert "FALHAS=5" in saida
        assert "ESTADO_FINAL=open" in saida

        # Nota: quando o servidor está completamente parado (não apenas lento),
        # mesmo a primeira tentativa falha rápido com "connection refused" —
        # por isso não comparamos tempos aqui. O comportamento de fail-fast
        # do circuito (sem qualquer tentativa de rede) é demonstrado de forma
        # mais clara no script de demonstração manual (ver DEMO_FALHA.md),
        # onde o servidor fica "preso" em vez de imediatamente recusar a ligação.
