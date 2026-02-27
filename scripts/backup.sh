#!/usr/bin/env bash
###############################################################################
# homelab-ai-stack — Backup Script
#
# Backs up all Docker volumes and configuration to a timestamped archive.
###############################################################################
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE="$BACKUP_DIR/hai-backup-$TIMESTAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "========================================"
echo "  homelab-ai-stack Backup"
echo "  Target: $ARCHIVE"
echo "========================================"

# Stop services for consistent backup
echo "Stopping services..."
docker compose stop

# Backup named volumes
VOLUMES=(
    hai-ollama-data
    hai-openwebui-data
    hai-chromadb-data
    hai-redis-data
    hai-gateway-data
)

TMPDIR=$(mktemp -d)
for vol in "${VOLUMES[@]}"; do
    echo "  Backing up volume: $vol"
    docker run --rm -v "$vol:/data" -v "$TMPDIR:/backup" \
        alpine tar czf "/backup/${vol}.tar.gz" -C /data . 2>/dev/null || \
        echo "    Warning: volume $vol not found, skipping."
done

# Backup config files
echo "  Backing up configuration..."
cp -r .env docker-compose.yml litellm-config.yml monitoring/ "$TMPDIR/" 2>/dev/null || true

# Create final archive
tar czf "$ARCHIVE" -C "$TMPDIR" .
rm -rf "$TMPDIR"

# Restart services
echo "Restarting services..."
docker compose up -d

SIZE=$(du -h "$ARCHIVE" | awk '{print $1}')
echo ""
echo "========================================"
echo "  Backup complete: $ARCHIVE ($SIZE)"
echo "========================================"
