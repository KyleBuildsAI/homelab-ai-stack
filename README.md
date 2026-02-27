# homelab-ai-stack

Complete self-hosted AI infrastructure for commodity hardware. One-command deploy of Ollama, LiteLLM, Open WebUI, ChromaDB, and a custom auth gateway with monitoring.

![Docker](https://img.shields.io/badge/docker-compose-blue)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Architecture

```
                         +------------------+
                         |   Open WebUI     |
                         |   :3000          |
                         +--------+---------+
                                  |
  Client -----> Gateway -----> LiteLLM -----> Ollama
                :8080          :4000          :11434
                (auth,         (routing,      (inference,
                 rate limit,    fallback,      GPU accel)
                 usage log)    caching)
                   |              |
                   v              v
                 Redis         ChromaDB
                 :6379         :8100
                 (cache,       (vectors,
                  sessions)     RAG)

                 Netdata :19999 (monitoring)
```

## Quick Start

```bash
git clone https://github.com/KyleBuildsAI/homelab-ai-stack.git
cd homelab-ai-stack
./scripts/setup.sh
```

That's it. The setup script will:
1. Check Docker and Docker Compose are installed
2. Generate secure random secrets for all services
3. Pull Docker images and build the gateway
4. Start the entire stack

Then pull some models:

```bash
./scripts/pull-models.sh
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| **Open WebUI** | 3000 | ChatGPT-like web interface |
| **Gateway** | 8080 | Auth, rate limiting, usage tracking |
| **LiteLLM** | 4000 | OpenAI-compatible API router |
| **Ollama** | 11434 | Local LLM inference engine |
| **ChromaDB** | 8100 | Vector database for RAG |
| **Redis** | 6379 | Caching and session storage |
| **Netdata** | 19999 | Real-time monitoring dashboard |

## Gateway API

The gateway provides OpenAI-compatible endpoints with authentication and rate limiting.

### Create an API Key

```bash
curl -X POST http://localhost:8080/admin/keys \
  -H "Authorization: Bearer $GATEWAY_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app", "rate_limit_rpm": 60}'
```

### Chat Completion

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer hai-your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.1:8b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Check Usage

```bash
curl http://localhost:8080/admin/usage \
  -H "Authorization: Bearer $GATEWAY_ADMIN_API_KEY"
```

## GPU Support

### NVIDIA

1. Install [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit)
2. Uncomment the NVIDIA GPU section in `docker-compose.yml`
3. Restart: `docker compose up -d`

### AMD ROCm

1. Install [ROCm Docker support](https://rocm.docs.amd.com/en/latest/deploy/docker.html)
2. Uncomment the AMD section in `docker-compose.yml`
3. Restart: `docker compose up -d`

## Hardware Requirements

| Tier | RAM | GPU VRAM | Models | Cost |
|------|-----|----------|--------|------|
| Budget | 16 GB | None | 7B (CPU) | ~$300 |
| Mid | 32 GB | 8-12 GB | 7B-13B | ~$800 |
| High | 64 GB | 24 GB | Up to 34B | ~$2000+ |

See [docs/HARDWARE.md](docs/HARDWARE.md) for detailed guidance.

## Configuration

All settings are in `.env`. Copy from the example:

```bash
cp .env.example .env
```

Key settings:
- `OLLAMA_MAX_LOADED_MODELS` — Models in memory simultaneously
- `GATEWAY_RATE_LIMIT_RPM` — Requests per minute per API key
- `OPENWEBUI_ENABLE_SIGNUP` — Allow new user registration

## Scripts

| Script | Description |
|--------|-------------|
| `scripts/setup.sh` | One-command bootstrap |
| `scripts/pull-models.sh` | Download recommended models |
| `scripts/backup.sh` | Backup all data and config |
| `scripts/health-check.sh` | Check all service status |

## Documentation

- [Hardware Recommendations](docs/HARDWARE.md)
- [Model Guide](docs/MODELS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## License

MIT
