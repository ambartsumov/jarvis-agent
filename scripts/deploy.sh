#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# PDS-Ultimate — Deploy Script
# ═══════════════════════════════════════════════════════════════════════════════
# Использование:
#   ./scripts/deploy.sh          — билд + запуск
#   ./scripts/deploy.sh build    — только билд
#   ./scripts/deploy.sh start    — только запуск
#   ./scripts/deploy.sh stop     — остановка
#   ./scripts/deploy.sh restart  — перезапуск
#   ./scripts/deploy.sh logs     — логи
#   ./scripts/deploy.sh status   — статус
#   ./scripts/deploy.sh test     — прогон тестов
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/pds_ultimate/.env"

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ─── Проверки ────────────────────────────────────────────────────────────────

check_prerequisites() {
    log_info "Проверка зависимостей..."

    if ! command -v docker &>/dev/null; then
        log_error "Docker не установлен. https://docs.docker.com/get-docker/"
        exit 1
    fi

    if ! docker compose version &>/dev/null; then
        log_error "Docker Compose v2 не найден."
        exit 1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env файл не найден: $ENV_FILE"
        log_info "Скопируйте: cp pds_ultimate/.env.example pds_ultimate/.env"
        exit 1
    fi

    # Проверяем обязательные переменные
    local missing=0
    for var in TG_BOT_TOKEN TG_OWNER_ID DEEPSEEK_API_KEY; do
        val=$(grep "^${var}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
        if [ -z "$val" ]; then
            log_error "Переменная $var не задана в .env"
            missing=1
        fi
    done

    if [ $missing -eq 1 ]; then
        log_error "Заполните обязательные переменные в $ENV_FILE"
        exit 1
    fi

    log_ok "Все зависимости в порядке"
}

# ─── Команды ─────────────────────────────────────────────────────────────────

do_build() {
    log_info "Сборка Docker образа..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" build
    log_ok "Образ собран"
}

do_start() {
    log_info "Запуск PDS-Ultimate..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" up -d
    log_ok "PDS-Ultimate запущен"
    echo ""
    do_status
}

do_stop() {
    log_info "Остановка PDS-Ultimate..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" down
    log_ok "PDS-Ultimate остановлен"
}

do_restart() {
    log_info "Перезапуск PDS-Ultimate..."
    do_stop
    do_start
}

do_logs() {
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100 pds
}

do_status() {
    cd "$PROJECT_DIR"
    echo -e "${BLUE}═══════════════════════════════════════${NC}"
    echo -e "${BLUE}  PDS-Ultimate — Статус${NC}"
    echo -e "${BLUE}═══════════════════════════════════════${NC}"

    if docker compose -f "$COMPOSE_FILE" ps --format json 2>/dev/null | grep -q "running"; then
        log_ok "Контейнер: RUNNING"
    else
        log_warn "Контейнер: STOPPED"
    fi

    # Volumes
    echo ""
    log_info "Volumes:"
    docker volume ls --filter name=pds 2>/dev/null | tail -n +2 || true
}

do_test() {
    log_info "Запуск тестов..."
    cd "$PROJECT_DIR"
    if [ -d ".venv" ]; then
        source .venv/bin/activate 2>/dev/null || true
    fi
    PYTHONPATH=. pytest pds_ultimate/tests/ -v --tb=short
    log_ok "Тесты пройдены"
}

do_deploy() {
    check_prerequisites
    do_build
    do_start
}

# ─── Main ────────────────────────────────────────────────────────────────────

echo -e "${BLUE}"
echo "  ╔═══════════════════════════════════════╗"
echo "  ║  🤖 PDS-Ultimate Deploy Tool          ║"
echo "  ╚═══════════════════════════════════════╝"
echo -e "${NC}"

ACTION="${1:-deploy}"

case "$ACTION" in
    build)   check_prerequisites; do_build ;;
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    logs)    do_logs ;;
    status)  do_status ;;
    test)    do_test ;;
    deploy)  do_deploy ;;
    *)
        echo "Использование: $0 {deploy|build|start|stop|restart|logs|status|test}"
        exit 1
        ;;
esac
