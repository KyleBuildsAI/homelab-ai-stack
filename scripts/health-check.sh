#!/usr/bin/env bash
###############################################################################
# homelab-ai-stack — Health Check
#
# Checks all services and reports their status.
###############################################################################

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_service() {
    local name="$1"
    local url="$2"
    local status
    status=$(curl -sf -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")

    if [ "$status" = "200" ]; then
        echo -e "  ${GREEN}[OK]${NC}  $name ($url)"
    elif [ "$status" = "000" ]; then
        echo -e "  ${RED}[DOWN]${NC} $name ($url) — not reachable"
    else
        echo -e "  ${YELLOW}[WARN]${NC} $name ($url) — HTTP $status"
    fi
}

echo ""
echo "========================================"
echo "  homelab-ai-stack Health Check"
echo "========================================"
echo ""

check_service "Ollama"      "http://localhost:11434/api/tags"
check_service "LiteLLM"     "http://localhost:4000/health"
check_service "Open WebUI"  "http://localhost:3000/health"
check_service "ChromaDB"    "http://localhost:8100/api/v1/heartbeat"
check_service "Gateway"     "http://localhost:8080/health"
check_service "Netdata"     "http://localhost:19999/api/v1/info"

# Redis
if docker exec hai-redis redis-cli ping 2>/dev/null | grep -q PONG; then
    echo -e "  ${GREEN}[OK]${NC}  Redis (redis-cli ping)"
else
    echo -e "  ${RED}[DOWN]${NC} Redis — not responding"
fi

# Docker containers
echo ""
echo "  Container Status:"
docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || docker compose ps

echo ""
echo "========================================"
