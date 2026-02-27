#!/usr/bin/env bash
###############################################################################
# homelab-ai-stack — Model Puller
#
# Downloads recommended LLM models into Ollama, ordered by usefulness.
###############################################################################
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

echo "========================================"
echo "  Pulling LLM Models into Ollama"
echo "  Host: $OLLAMA_HOST"
echo "========================================"

pull_model() {
    local model="$1"
    local size="$2"
    local desc="$3"
    echo ""
    echo "--- $model ($size) ---"
    echo "    $desc"
    curl -s "$OLLAMA_HOST/api/pull" -d "{\"name\": \"$model\"}" | while read -r line; do
        status=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
        [ -n "$status" ] && printf "\r    %s" "$status"
    done
    echo ""
    echo "    Done."
}

# General chat (start here)
pull_model "llama3.1:8b"           "4.7 GB"  "Best general-purpose model for 8GB+ RAM"
pull_model "mistral:7b"            "4.1 GB"  "Fast and capable, great for quick tasks"

# Embeddings (required for RAG)
pull_model "nomic-embed-text"      "274 MB"  "Text embeddings for RAG and search"

# Code
pull_model "qwen2.5-coder:7b"     "4.7 GB"  "Code generation and analysis"

# Small/fast
pull_model "phi3:mini"             "2.3 GB"  "Tiny but smart — classification and extraction"

echo ""
echo "========================================"
echo "  All models pulled successfully!"
echo ""
echo "  Verify with: curl $OLLAMA_HOST/api/tags"
echo "========================================"
