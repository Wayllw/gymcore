"""
Testes da Fase 2 — Assincronismo, Event-Driven, Observabilidade.

Cobre:
  - FilaMensagens: publicar, consumir, retry, dead-letter
  - BusEventos: subscrever, publicar, múltiplos consumidores, isolamento de falhas
  - RelatorioWorker: processamento assíncrono, retry com backoff, injeção de falha
  - correlationId: propagação de ponta-a-ponta
  - QueueRelatorioService: resposta imediata vs Fase 1 (2s)
"""
import time
import threading
import pytest
from unittest.mock import MagicMock, call
from uuid import uuid4

# Importar módulos de Fase 2
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from infrastructure.messaging.queue import FilaMensagens, Mensagem
from infrastructure.events.event_bus import BusEventos, Evento, TipoEvento
from infrastructure.events.consumers import AuditoriaConsumer, EstatisticasConsumer, AlertaConsumer
from infrastructure.workers.relatorio_worker import RelatorioWorker
from infrastructure.adapters.outbound.async_services import QueueRelatorioService


# ─── Testes: FilaMensagens ────────────────────────────────────────────────────

class TestFilaMensagens:

    def test_publicar_e_consumir_mensagem(self):
        fila = FilaMensagens("test")
        msg = Mensagem(tipo="teste", payload={"chave": "valor"})
        fila.publicar(msg)
        recebida = fila.consumir(timeout=0.5)
        assert recebida is not None
        assert recebida.tipo == "teste"
        assert recebida.payload["chave"] == "valor"

    def test_correlation_id_gerado_automaticamente(self):
        msg = Mensagem(tipo="teste", payload={})
        assert msg.correlation_id is not None
        assert len(msg.correlation_id) == 36  # UUID format

    def test_correlation_id_preservado_na_fila(self):
        fila = FilaMensagens("test2")
        cid = str(uuid4())
        msg = Mensagem(tipo="teste", payload={}, correlation_id=cid)
        fila.publicar(msg)
        recebida = fila.consumir(timeout=0.5)
        assert recebida.correlation_id == cid

    def test_consumir_timeout_retorna_none(self):
        fila = FilaMensagens("vazia")
        resultado = fila.consumir(timeout=0.1)
        assert resultado is None

    def test_retry_incrementa_tentativas(self):
        fila = FilaMensagens("retry_test")
        msg = Mensagem(tipo="teste", payload={}, max_tentativas=3)
        fila.publicar(msg)
        
        recebida = fila.consumir(timeout=0.5)
        assert recebida.tentativas == 0
        assert recebida.pode_retentar()
        
        fila.rejeitar(recebida)
        
        # Mensagem deve estar de volta na fila com tentativas=1
        reenfileirada = fila.consumir(timeout=0.5)
        assert reenfileirada is not None
        assert reenfileirada.tentativas == 1

    def test_dead_letter_queue_apos_max_tentativas(self):
        fila = FilaMensagens("dlq_test")
        msg = Mensagem(tipo="teste", payload={}, max_tentativas=1)
        fila.publicar(msg)
        
        recebida = fila.consumir(timeout=0.5)
        fila.rejeitar(recebida)  # tentativas = 1, pode retentar
        
        reenfileirada = fila.consumir(timeout=0.5)
        fila.rejeitar(reenfileirada)  # tentativas = 2 > max_tentativas=1 → DLQ
        
        # Fila principal deve estar vazia
        assert fila.consumir(timeout=0.1) is None
        stats = fila.estatisticas()
        assert stats["total_erros"] == 1

    def test_estatisticas_corretas(self):
        fila = FilaMensagens("stats_test")
        for i in range(3):
            fila.publicar(Mensagem(tipo="teste", payload={"i": i}))
        
        stats = fila.estatisticas()
        assert stats["total_publicadas"] == 3
        assert stats["pendentes"] == 3


# ─── Testes: BusEventos ──────────────────────────────────────────────────────

class TestBusEventos:

    def test_handler_chamado_ao_publicar_evento(self):
        bus = BusEventos()
        handler = MagicMock()
        bus.subscrever("teste.evento", handler)
        
        evento = Evento(tipo="teste.evento", payload={"dados": "abc"})
        bus.publicar(evento)
        
        handler.assert_called_once()
        args = handler.call_args[0][0]
        assert args.tipo == "teste.evento"

    def test_multiplos_handlers_para_mesmo_evento(self):
        bus = BusEventos()
        h1 = MagicMock(name="handler1")
        h2 = MagicMock(name="handler2")
        h3 = MagicMock(name="handler3")
        
        bus.subscrever("socio.inscrito", h1)
        bus.subscrever("socio.inscrito", h2)
        bus.subscrever("socio.inscrito", h3)
        
        bus.publicar(Evento(tipo="socio.inscrito", payload={}))
        
        h1.assert_called_once()
        h2.assert_called_once()
        h3.assert_called_once()

    def test_falha_num_handler_nao_afeta_outros(self):
        """Isolamento: handler com erro não deve bloquear os outros."""
        bus = BusEventos()
        
        h_falha = MagicMock(side_effect=RuntimeError("Handler com erro!"))
        h_ok = MagicMock()
        
        bus.subscrever("evento.teste", h_falha)
        bus.subscrever("evento.teste", h_ok)
        
        # Não deve lançar exceção
        bus.publicar(Evento(tipo="evento.teste", payload={}))
        
        h_falha.assert_called_once()
        h_ok.assert_called_once()  # continua a ser chamado apesar da falha do anterior

    def test_correlation_id_propagado(self):
        bus = BusEventos()
        cid_recebido = []
        
        def capturar_cid(evento):
            cid_recebido.append(evento.correlation_id)
        
        bus.subscrever("teste.cid", capturar_cid)
        
        meu_cid = "meu-correlation-id-123"
        evento = Evento(tipo="teste.cid", payload={})
        bus.publicar(evento, correlation_id=meu_cid)
        
        assert cid_recebido[0] == meu_cid

    def test_historico_guarda_eventos(self):
        bus = BusEventos()
        bus.publicar(Evento(tipo="a.b", payload={}))
        bus.publicar(Evento(tipo="a.b", payload={}))
        bus.publicar(Evento(tipo="c.d", payload={}))
        
        todos = bus.historico()
        assert len(todos) == 3
        
        filtrado = bus.historico(tipo="a.b")
        assert len(filtrado) == 2

    def test_sem_handlers_nao_lanca_excecao(self):
        bus = BusEventos()
        # Não deve lançar exceção mesmo sem handlers
        bus.publicar(Evento(tipo="evento.sem.handler", payload={}))


# ─── Testes: Consumidores ────────────────────────────────────────────────────

class TestConsumidores:

    def test_estatisticas_consumer_contabiliza_eventos(self):
        consumer = EstatisticasConsumer()
        
        consumer.on_socio_inscrito(Evento(tipo=TipoEvento.SOCIO_INSCRITO, payload={}))
        consumer.on_socio_inscrito(Evento(tipo=TipoEvento.SOCIO_INSCRITO, payload={}))
        consumer.on_plano_criado(Evento(tipo=TipoEvento.PLANO_CRIADO, payload={}))
        consumer.on_relatorio_concluido(Evento(tipo=TipoEvento.RELATORIO_CONCLUIDO, payload={}))
        
        stats = consumer.estatisticas()
        assert stats["socios_inscritos"] == 2
        assert stats["planos_criados"] == 1
        assert stats["relatorios_gerados"] == 1

    def test_auditoria_consumer_nao_lanca_excecao(self):
        consumer = AuditoriaConsumer()
        # Não deve lançar exceção com payload mínimo
        consumer.on_socio_inscrito(Evento(tipo=TipoEvento.SOCIO_INSCRITO, payload={}))
        consumer.on_socio_suspenso(Evento(tipo=TipoEvento.SOCIO_SUSPENSO, payload={}))
        consumer.on_relatorio_concluido(Evento(tipo=TipoEvento.RELATORIO_CONCLUIDO, payload={}))
        consumer.on_relatorio_falhou(Evento(tipo=TipoEvento.RELATORIO_FALHOU, payload={}))


# ─── Testes: Worker Assíncrono ───────────────────────────────────────────────

class TestRelatorioWorker:

    def test_worker_processa_mensagem_em_background(self):
        fila = FilaMensagens("worker_test")
        bus = BusEventos()
        eventos_recebidos = []
        
        bus.subscrever(TipoEvento.RELATORIO_CONCLUIDO, lambda e: eventos_recebidos.append(e))
        
        worker = RelatorioWorker(fila, bus, simular_falha=False)
        worker.iniciar()
        
        msg = Mensagem(
            tipo="gerar_relatorio",
            payload={"socio_id": str(uuid4()), "job_id": str(uuid4())}
        )
        fila.publicar(msg)
        
        # Aguardar processamento (worker é assíncrono)
        time.sleep(3.5)
        worker.parar()
        
        assert len(eventos_recebidos) == 1
        assert eventos_recebidos[0].tipo == TipoEvento.RELATORIO_CONCLUIDO

    def test_worker_falha_injeta_e_faz_retry(self):
        """Demonstração: worker falha 2x, sucesso na 3ª tentativa."""
        fila = FilaMensagens("falha_test")
        bus = BusEventos()
        eventos_falha = []
        eventos_sucesso = []
        
        bus.subscrever(TipoEvento.RELATORIO_FALHOU, lambda e: eventos_falha.append(e))
        bus.subscrever(TipoEvento.RELATORIO_CONCLUIDO, lambda e: eventos_sucesso.append(e))
        
        worker = RelatorioWorker(fila, bus, simular_falha=True, falhas_consecutivas=2)
        worker.iniciar()
        
        cid = str(uuid4())
        msg = Mensagem(
            tipo="gerar_relatorio",
            payload={"socio_id": str(uuid4()), "job_id": str(uuid4())},
            correlation_id=cid,
            max_tentativas=3,
        )
        fila.publicar(msg)
        
        # Aguardar: 2 falhas (backoff 1s+2s) + processamento (2s) = ~7s
        time.sleep(10)
        worker.parar()
        
        assert len(eventos_falha) == 2, f"Esperado 2 falhas, obteve {len(eventos_falha)}"
        assert len(eventos_sucesso) == 1, f"Esperado 1 sucesso, obteve {len(eventos_sucesso)}"
        
        # correlation_id deve ser o mesmo em todos os eventos
        for e in eventos_falha:
            assert e.correlation_id == cid
        assert eventos_sucesso[0].correlation_id == cid

    def test_correlation_id_propagado_do_pedido_ao_evento(self):
        """O correlationId do pedido HTTP deve aparecer nos eventos do worker."""
        fila = FilaMensagens("cid_test")
        bus = BusEventos()
        cids_recebidos = []
        
        bus.subscrever(TipoEvento.RELATORIO_CONCLUIDO, lambda e: cids_recebidos.append(e.correlation_id))
        
        worker = RelatorioWorker(fila, bus, simular_falha=False)
        worker.iniciar()
        
        meu_cid = "correlation-id-do-pedido-http-original"
        msg = Mensagem(
            tipo="gerar_relatorio",
            payload={"socio_id": str(uuid4())},
            correlation_id=meu_cid,
        )
        fila.publicar(msg)
        time.sleep(3.5)
        worker.parar()
        
        assert len(cids_recebidos) == 1
        assert cids_recebidos[0] == meu_cid


# ─── Testes: QueueRelatorioService ───────────────────────────────────────────

class TestQueueRelatorioService:

    def test_resposta_imediata_vs_fase1(self):
        """
        RNF-3: O endpoint de relatório na Fase 2 deve responder em < 100ms.
        Na Fase 1 bloqueava 2000ms.
        """
        fila = FilaMensagens("timing_test")
        bus = BusEventos()
        service = QueueRelatorioService(fila, bus)
        
        inicio = time.time()
        job_id = service.gerar_relatorio_socio(uuid4())
        duracao_ms = (time.time() - inicio) * 1000
        
        assert duracao_ms < 100, f"Resposta demorou {duracao_ms:.1f}ms — devia ser < 100ms"
        assert job_id is not None
        assert fila.estatisticas()["pendentes"] == 1

    def test_publicar_evento_relatorio_solicitado(self):
        fila = FilaMensagens("event_test")
        bus = BusEventos()
        eventos = []
        bus.subscrever(TipoEvento.RELATORIO_SOLICITADO, lambda e: eventos.append(e))
        
        service = QueueRelatorioService(fila, bus)
        service.gerar_relatorio_socio(uuid4())
        
        assert len(eventos) == 1
        assert eventos[0].tipo == TipoEvento.RELATORIO_SOLICITADO

    def test_correlation_id_propagado_para_mensagem(self):
        fila = FilaMensagens("cid_service_test")
        bus = BusEventos()
        service = QueueRelatorioService(fila, bus)
        
        meu_cid = "cid-do-pedido-http"
        service.gerar_relatorio_socio(uuid4(), correlation_id=meu_cid)
        
        msg = fila.consumir(timeout=0.5)
        assert msg.correlation_id == meu_cid
