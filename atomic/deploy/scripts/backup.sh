#!/usr/bin/env bash
# Backup diário do MongoDB e dos uploads. Agende no cron da VPS:
#   15 3 * * * /opt/atomic-chat/atomic/deploy/scripts/backup.sh >> /var/log/atomic-backup.log 2>&1
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/atomic-chat}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y-%m-%d_%H%M)"

mkdir -p "$BACKUP_DIR"
cd "$DEPLOY_DIR"

docker compose exec -T mongodb mongodump --archive --gzip --db rocketchat > "$BACKUP_DIR/mongo_$STAMP.archive.gz"
docker compose exec -T rocketchat tar czf - -C /app uploads > "$BACKUP_DIR/uploads_$STAMP.tar.gz"
tar czf "$BACKUP_DIR/hermes_$STAMP.tar.gz" -C "$DEPLOY_DIR/data" hermes

find "$BACKUP_DIR" -type f -mtime +"$KEEP_DAYS" -delete
echo "$(date -Is) backup ok → $BACKUP_DIR"
# Recomendado: copiar $BACKUP_DIR para fora da VPS (rclone para Google Drive/S3).
