# Model Recommendations

## By Use Case

| Use Case | Recommended Model | Size | VRAM | Notes |
|----------|-------------------|------|------|-------|
| General chat | llama3.1:8b | 4.7 GB | 6 GB | Best all-around for size |
| Code generation | qwen2.5-coder:7b | 4.7 GB | 6 GB | Strong at code tasks |
| Code review | deepseek-coder-v2:16b | 9.1 GB | 12 GB | Needs more VRAM |
| Fast tasks | phi3:mini | 2.3 GB | 3 GB | Classification, extraction |
| Summarization | mistral:7b | 4.1 GB | 6 GB | Fast and concise |
| RAG embeddings | nomic-embed-text | 274 MB | 1 GB | Required for search/RAG |
| Advanced chat | llama3.1:70b | 40 GB | 48 GB | Needs high-end GPU |

## Pulling Models

```bash
# Pull via CLI
./scripts/pull-models.sh

# Pull manually
docker exec hai-ollama ollama pull llama3.1:8b
docker exec hai-ollama ollama pull mistral:7b

# List installed models
docker exec hai-ollama ollama list
```

## Custom Models via Modelfile

```dockerfile
FROM llama3.1:8b

PARAMETER temperature 0.7
PARAMETER num_ctx 4096

SYSTEM "You are a helpful coding assistant. Be concise."
```

```bash
docker exec hai-ollama ollama create my-coder -f /path/to/Modelfile
```

## Memory Planning

When running multiple models simultaneously (`OLLAMA_MAX_LOADED_MODELS`), each loaded model consumes its full memory allocation. Plan accordingly:

- **16 GB RAM, no GPU:** 1 model loaded (7B)
- **32 GB RAM, 12 GB VRAM:** 2 models loaded (7B + embeddings)
- **64 GB RAM, 24 GB VRAM:** 3+ models loaded
