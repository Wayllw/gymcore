"""
Worker Assíncrono para Geração de Relatórios — Web-Queue-Worker pattern.

Este worker corre numa thread de background, consumindo mensagens da fila
e processando a geração de relatórios de forma assíncrona.

Por que isto resolve o problema da Fase 1:
- Na Fase 1: POST /relatorio → bloqueava 2s → resposta HTTP
- Na Fase 2: POST /relatorio → publica na fila → resposta imediata (< 10ms)
             Worker consome fila em background → processa sem bloquear pedidos HTTP

Demonstração de falha:
  Injetar SIMULAR_FALHA=True num worker para demonstrar:
  - Retry automático com backoff
  - Rastreio via correlationId nos logs
  - Dead Letter Queue após esgotar tentativas
"""
import logging
import threading
import time
import os
from uuid import UUID
from typing import Optional

from infrastructure.messaging.queue import FilaMensagens, Mensagem
from infrastructure.events.event_bus import BusEventos, Evento, TipoEvento

logger = logging.getLogger(__name__)


class RelatorioWorker:
    """
    Worker que processa mensagens de geração de relatório em background.
    
    Implementa:
    - Consumo contínuo da fila (loop infinito em thread separada)
    - Retry com backoff exponencial
    - Publicação de eventos de conclusão/falha
    - Rastreio completo via correlationId
    - Injeção de falha controlada para demonstração
    """

    def __init__(
        self,
        fila: FilaMensagens,
        bus_eventos: BusEventos,
        simular_falha: bool = False,
        falhas_consecutivas: int = 2,
    ):
        self._fila = fila
        self._bus = bus_eventos
        self._simular_falha = simular_falha
        self._falhas_consecutivas = falhas_consecutivas  # quantas falhas antes de sucesso
        self._falhas_injetadas = 0
        self._ativo = False
        self._thread: Optional[threading.Thread] = None

    def iniciar(self) -> None:
        """Inicia o worker em background thread."""
        self._ativo = True
        self._thread = threading.Thread(
            target=self._loop_consumo,
            name="RelatorioWorker",
            daemon=True  # thread termina quando o processo principal termina
        )
        self._thread.start()
        logger.info("🚀 [WORKER] RelatorioWorker iniciado | simular_falha=%s", self._simular_falha)

    def parar(self) -> None:
        """Para o worker de forma graciosa."""
        self._ativo = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("🛑 [WORKER] RelatorioWorker parado.")

    def _loop_consumo(self) -> None:
        """
        Loop principal do worker.
        Consome mensagens da fila continuamente até ser parado.
        """
        logger.info("🔄 [WORKER] A escutar fila de relatórios...")
        while self._ativo:
            mensagem = self._fila.consumir(timeout=1.0)
            if mensagem is None:
                continue  # timeout, sem mensagem — voltar ao início

            logger.info(
                "📥 [WORKER] Mensagem recebida | tipo=%s | correlation_id=%s | tentativa=%d",
                mensagem.tipo, mensagem.correlation_id, mensagem.tentativas + 1
            )

            try:
                self._processar(mensagem)
                self._fila.confirmar()
            except Exception as e:
                logger.error(
                    "❌ [WORKER] Falha ao processar | correlation_id=%s | erro=%s | tentativa=%d",
                    mensagem.correlation_id, str(e), mensagem.tentativas + 1
                )
                # Backoff exponencial antes de rejeitar (simula retry inteligente)
                backoff = min(2 ** mensagem.tentativas, 8)
                logger.info(
                    "⏳ [WORKER] Backoff %ds antes de retry | correlation_id=%s",
                    backoff, mensagem.correlation_id
                )
                time.sleep(backoff)
                self._fila.rejeitar(mensagem)

                # Publicar evento de falha
                self._bus.publicar(
                    Evento(
                        tipo=TipoEvento.RELATORIO_FALHOU,
                        payload={
                            "socio_id": mensagem.payload.get("socio_id"),
                            "erro": str(e),
                            "tentativa": mensagem.tentativas,
                        },
                        origem="RelatorioWorker",
                    ),
                    correlation_id=mensagem.correlation_id
                )

    def _processar(self, mensagem: Mensagem) -> None:
        """
        Processa uma mensagem de geração de relatório.
        
        Se SIMULAR_FALHA estiver ativo, lança exceção nas primeiras N tentativas
        para demonstrar o mecanismo de retry e rastreio via correlationId.
        """
        socio_id = mensagem.payload.get("socio_id")
        correlation_id = mensagem.correlation_id

        # ── Injeção de falha controlada (para demonstração) ──────────────
        if self._simular_falha and self._falhas_injetadas < self._falhas_consecutivas:
            self._falhas_injetadas += 1
            logger.error(
                "💥 [WORKER] FALHA INJETADA #%d | correlation_id=%s | "
                "Verificar logs com este correlation_id para rastrear o fluxo completo.",
                self._falhas_injetadas, correlation_id
            )
            raise RuntimeError(
                f"[FALHA SIMULADA #{self._falhas_injetadas}] Serviço de relatórios indisponível. "
                f"correlation_id={correlation_id}"
            )

        # ── Processamento real (simulado) ─────────────────────────────────
        logger.info(
            "⚙️  [WORKER] A processar relatório | socio_id=%s | correlation_id=%s",
            socio_id, correlation_id
        )

        # Simula trabalho pesado (em prod: gerar PDF, calcular métricas, etc.)
        time.sleep(2)

        caminho = f"relatorios/socio_{socio_id}.pdf"
        logger.info(
            "✅ [WORKER] Relatório gerado com sucesso | caminho=%s | correlation_id=%s",
            caminho, correlation_id
        )

        # Publicar evento de conclusão
        self._bus.publicar(
            Evento(
                tipo=TipoEvento.RELATORIO_CONCLUIDO,
                payload={
                    "socio_id": socio_id,
                    "caminho": caminho,
                },
                origem="RelatorioWorker",
            ),
            correlation_id=correlation_id
        )
