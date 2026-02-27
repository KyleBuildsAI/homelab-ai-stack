# Hardware Recommendations

## Tier Overview

| Tier | Budget | CPU | RAM | GPU | Best For |
|------|--------|-----|-----|-----|----------|
| **Budget** | ~$300 | 4-core i5/Ryzen 5 | 16 GB | None (CPU only) | 7B models, light usage |
| **Mid-Range** | ~$800 | 6-core i5/Ryzen 5 | 32 GB | GTX 1080 / RTX 3060 (8GB) | 13B models, daily use |
| **High-End** | ~$2000+ | 8-core i7/Ryzen 7 | 64 GB | RTX 3090 / 4090 (24GB) | 70B models, multi-user |

## CPU

LLM inference is primarily memory-bandwidth bound, not compute bound. Any modern quad-core CPU is sufficient. Prioritize RAM and GPU budget over CPU.

- **Minimum:** Intel i5-6500 / AMD Ryzen 5 2600
- **Recommended:** Intel i5-12400 / AMD Ryzen 5 5600X
- **Overkill:** You don't need a Threadripper for inference

## RAM

Ollama loads models into RAM (or VRAM). Each model needs roughly 0.5-1x its file size in memory.

| Model Size | Min RAM | Recommended |
|------------|---------|-------------|
| 7B (4-bit) | 8 GB | 16 GB |
| 13B (4-bit) | 16 GB | 32 GB |
| 70B (4-bit) | 48 GB | 64 GB |

**Important:** Add 4-8 GB overhead for the OS, Docker, and other services.

## GPU

A GPU is optional but dramatically improves inference speed (5-20x faster than CPU-only).

| GPU | VRAM | Can Run | Tokens/sec (est.) |
|-----|------|---------|--------------------|
| No GPU (CPU only) | — | 7B | 2-5 t/s |
| GTX 1080 Ti | 11 GB | 7B-13B | 15-30 t/s |
| RTX 3060 | 12 GB | 7B-13B | 20-40 t/s |
| RTX 3090 | 24 GB | 7B-34B | 30-60 t/s |
| RTX 4090 | 24 GB | 7B-34B | 50-100 t/s |
| 2x RTX 3090 | 48 GB | 70B | 20-40 t/s |

## Storage

- **Boot + OS:** 50 GB SSD minimum
- **Models:** 5-50 GB per model (7B = ~4 GB, 70B = ~40 GB)
- **Data:** 10-50 GB for ChromaDB, logs, usage data
- **Recommended:** 500 GB NVMe SSD

## Network

1 Gbps Ethernet is sufficient. The bottleneck is inference speed, not network bandwidth.
