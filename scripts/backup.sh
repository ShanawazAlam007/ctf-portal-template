#!/usr/bin/env bash
# ============================================================
# CTF PORTAL TEMPLATE — DATABASE BACKUP UTILITY
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

BACKUP_DIR="${ROOT_DIR}/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/ctf_backup_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

# Source environment if present
if [ -f "${ROOT_DIR}/.env" ]; then
    # shellcheck disable=SC1091
    source "${ROOT_DIR}/.env"
fi

DB_USER="${POSTGRES_USER:-ctf_admin}"
DB_NAME="${POSTGRES_DB:-ctf_db}"
CONTAINER_NAME="ctf_postgres"

echo "[*] Creating database backup: $BACKUP_FILE..."

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_FILE"
    echo "[+] Database backup successfully exported via Docker!"
elif command -v pg_dump >/dev/null 2>&1; then
    PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_FILE"
    echo "[+] Database backup successfully exported via local pg_dump!"
else
    echo "[-] Error: Neither Docker container '${CONTAINER_NAME}' nor local pg_dump utility is available."
    exit 1
fi

# Retention policy: Prune backups older than 7 days
echo "[*] Cleaning up backups older than 7 days..."
find "$BACKUP_DIR" -type f -name "ctf_backup_*.sql.gz" -mtime +7 -delete

echo "[+] Backup process completed: $(du -h "$BACKUP_FILE" | cut -f1)"
