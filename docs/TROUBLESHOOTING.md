# Troubleshooting

## Common Issues

### Ollama: Model fails to load (OOM)
**Symptom:** `out of memory` error when loading a model.
**Fix:** Reduce `OLLAMA_MAX_LOADED_MODELS` to 1 in `.env`, or use a smaller model.

### LiteLLM: Connection refused
**Symptom:** Gateway returns 502 when proxying to LiteLLM.
**Fix:** Wait 30s after startup for LiteLLM to initialize. Check `docker logs hai-litellm`.

### Open WebUI: Blank page or 500
**Symptom:** Web UI shows error or blank page.
**Fix:** Ensure `OPENWEBUI_SECRET_KEY` is set in `.env`. Run `docker compose restart open-webui`.

### Gateway: Redis connection error
**Symptom:** Gateway fails to start with Redis error.
**Fix:** Ensure Redis is running: `docker compose up -d redis`. Check `REDIS_PASSWORD` matches in `.env`.

### GPU not detected by Ollama
**Symptom:** Ollama runs on CPU despite having a GPU.
**Fix:**
1. Install nvidia-container-toolkit: `apt install nvidia-container-toolkit`
2. Uncomment GPU section in `docker-compose.yml`
3. Verify: `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`

### Port conflicts
**Symptom:** Container fails to start due to port binding.
**Fix:** Change conflicting ports in `.env` (e.g., `OPENWEBUI_HOST_PORT=3001`).

## Useful Commands

```bash
# View logs for a service
docker compose logs -f ollama
docker compose logs -f gateway

# Restart a single service
docker compose restart litellm

# Check resource usage
docker stats

# Enter a container shell
docker exec -it hai-ollama bash

# Full reset (WARNING: deletes all data)
docker compose down -v
./scripts/setup.sh
```
