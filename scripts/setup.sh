#!/usr/bin/env bash
###############################################################################
# homelab-ai-stack — One-Command Setup
#
# Checks prerequisites, generates secrets, pulls images, and starts the stack.
###############################################################################
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo ""
echo "=========================================="
echo "  homelab-ai-stack Setup"
echo "=========================================="
echo ""

# --- Check Docker ---
info "Checking Docker..."
command -v docker >/dev/null 2>&1 || error "Docker is not installed. Install it from https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || error "Docker daemon is not running."
info "Docker $(docker --version | awk '{print $3}') detected."

# --- Check Docker Compose ---
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
    info "Docker Compose v2 detected."
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
    info "Docker Compose v1 detected."
else
    error "Docker Compose is not installed."
fi

# --- Generate .env ---
if [ ! -f .env ]; then
    info "Generating .env from .env.example..."
    cp .env.example .env

    # Generate random secrets
    for key in LITELLM_MASTER_KEY OPENWEBUI_SECRET_KEY GATEWAY_ADMIN_API_KEY GATEWAY_JWT_SECRET; do
        secret=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|${key}=change-me-generate-with-openssl-rand-hex-32|${key}=${secret}|" .env
        else
            sed -i "s|${key}=change-me-generate-with-openssl-rand-hex-32|${key}=${secret}|" .env
        fi
    done
    info "Secrets generated and written to .env"
else
    info ".env already exists, skipping generation."
fi

# --- Create data directories ---
info "Creating data directories..."
mkdir -p gateway/data monitoring

# --- Check for NVIDIA GPU ---
if command -v nvidia-smi >/dev/null 2>&1; then
    info "NVIDIA GPU detected!"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
    warn "Uncomment the GPU section in docker-compose.yml to enable GPU passthrough."
else
    info "No NVIDIA GPU detected — running in CPU-only mode."
fi

# --- Pull images ---
info "Pulling Docker images (this may take a while)..."
$COMPOSE pull

# --- Build gateway ---
info "Building gateway service..."
$COMPOSE build gateway

# --- Start stack ---
info "Starting the stack..."
$COMPOSE up -d

echo ""
echo "=========================================="
info "Setup complete!"
echo ""
echo "  Open WebUI:   http://localhost:3000"
echo "  Gateway API:   http://localhost:8080/docs"
echo "  LiteLLM:       http://localhost:4000"
echo "  Monitoring:    http://localhost:19999"
echo ""
echo "  Next steps:"
echo "    1. Run  ./scripts/pull-models.sh  to download LLM models"
echo "    2. Visit http://localhost:3000 to set up your Open WebUI account"
echo "    3. Create a gateway API key:"
echo "       curl -X POST http://localhost:8080/admin/keys \\"
echo "         -H 'Authorization: Bearer <your-admin-key>' \\"
echo "         -H 'Content-Type: application/json' \\"
echo "         -d '{\"name\": \"my-key\"}'"
echo "=========================================="
