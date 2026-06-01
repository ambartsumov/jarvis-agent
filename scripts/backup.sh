#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# PDS-Ultimate — Backup Script
# ═══════════════════════════════════════════════════════════════════════════════
# Бэкап данных из Docker volume в локальную папку
#
# Использование:
#   ./scripts/backup.sh                  — бэкап в ./backups/
#   ./scripts/backup.sh /path/to/backup  — бэкап в указанную папку
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${1:-$PROJECT_DIR/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/pds_backup_${TIMESTAMP}.tar.gz"

echo "🔒 PDS-Ultimate Backup"
echo "═══════════════════════"

# Создаём папку бэкапов
mkdir -p "$BACKUP_DIR"

# Бэкап данных из контейнера
echo "📦 Бэкап данных..."

docker run --rm \
    -v pds-data:/data:ro \
    -v pds-logs:/logs:ro \
    -v "$BACKUP_DIR":/backup \
    alpine:3.19 \
    tar czf "/backup/pds_backup_${TIMESTAMP}.tar.gz" \
    -C / data logs

if [ -f "$BACKUP_FILE" ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "✅ Бэкап создан: $BACKUP_FILE ($SIZE)"
else
    echo "❌ Ошибка создания бэкапа"
    exit 1
fi

# Удаляем бэкапы старше 30 дней
OLD=$(find "$BACKUP_DIR" -name "pds_backup_*.tar.gz" -mtime +30 -print)
if [ -n "$OLD" ]; then
    echo "$OLD" | xargs rm -f
    echo "🗑️  Удалены старые бэкапы (>30 дней)"
fi

echo "═══════════════════════"
echo "✅ Готово"
