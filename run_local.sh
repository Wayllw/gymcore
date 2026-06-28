#!/usr/bin/env bash
#
# Script de arranque local — alternativa ao docker-compose para desenvolvimento.
# Requer: Redis a correr em localhost:6379 (ex: `redis-server` ou `docker run -p 6379:6379 redis`)
#
# Uso:
#   chmod +x run_local.sh
#   ./run_local.sh start   — arranca os 3 serviços em background
#   ./run_local.sh stop    — para todos os serviços
#   ./run_local.sh logs    — mostra os logs em tempo real
#
set -e

PIDS_FILE="/tmp/gymcore_pids.txt"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

start() {
    echo "A verificar Redis..."
    redis-cli ping > /dev/null 2>&1 || { echo "ERRO: Redis não está a correr em localhost:6379. Inicie com 'redis-server' primeiro."; exit 1; }

    echo "A arrancar Sócios-Service (REST :8001, gRPC :9001)..."
    cd "$ROOT_DIR/socios-service"
    SOCIOS_DB_PATH=./dados/socios.db \
        nohup python infrastructure/adapters/inbound/api.py > /tmp/gymcore_socios.log 2>&1 &
    echo $! >> "$PIDS_FILE"
    sleep 2

    echo "A arrancar Treinos-Service (REST :8002)..."
    cd "$ROOT_DIR/treinos-service"
    TREINOS_DB_PATH=./dados/treinos.db SOCIOS_GRPC_HOST=localhost SOCIOS_GRPC_PORT=9001 \
        nohup python infrastructure/adapters/inbound/api.py > /tmp/gymcore_treinos.log 2>&1 &
    echo $! >> "$PIDS_FILE"
    sleep 2

    echo "A arrancar API Gateway (REST :8000)..."
    cd "$ROOT_DIR/gateway"
    SOCIOS_SERVICE_URL=http://localhost:8001 TREINOS_SERVICE_URL=http://localhost:8002 \
        nohup python gateway.py > /tmp/gymcore_gateway.log 2>&1 &
    echo $! >> "$PIDS_FILE"
    sleep 1

    echo
    echo "Todos os serviços arrancados:"
    echo "  Gateway:         http://localhost:8000"
    echo "  Sócios-Service:  http://localhost:8001  (gRPC :9001)"
    echo "  Treinos-Service: http://localhost:8002"
    echo
    echo "Logs em: /tmp/gymcore_{socios,treinos,gateway}.log"
}

stop() {
    if [ -f "$PIDS_FILE" ]; then
        echo "A parar serviços..."
        while read -r pid; do
            kill "$pid" 2>/dev/null || true
        done < "$PIDS_FILE"
        rm -f "$PIDS_FILE"
        echo "Serviços parados."
    else
        echo "Nenhum serviço em execução (ficheiro de PIDs não encontrado)."
    fi
}

logs() {
    tail -f /tmp/gymcore_socios.log /tmp/gymcore_treinos.log /tmp/gymcore_gateway.log
}

case "$1" in
    start) start ;;
    stop) stop ;;
    logs) logs ;;
    *) echo "Uso: $0 {start|stop|logs}" ;;
esac
