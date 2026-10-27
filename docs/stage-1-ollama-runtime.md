# Go 81: Local Ollama Runtime Guide & Verification (Stage 1)

## 1. Overview
Go 81 is a strictly local-first personal AI agent. All reasoning, intent classification, task planning, memory consolidation, and embedding operations execute on the user's hardware via **Ollama**. No conversational prompts, memories, or tokens are ever transmitted to third-party cloud AI providers.

---

## 2. Installation & Prerequisites
- **Ollama**: Download and install Ollama from [https://ollama.com](https://ollama.com).
  - Windows: Download `OllamaSetup.exe` and complete the installer.
  - macOS: Download the `.dmg` or install via `brew install ollama`.
  - Linux: Run `curl -fsSL https://ollama.com/install.sh | sh`.
- **Python**: 3.12+ (managed with `requirements.txt`).

---

## 3. Starting the Local Ollama Daemon
Start the service over the local loopback interface:
```bash
ollama serve
```
By default, the daemon binds to `http://127.0.0.1:11434`.

---

## 4. Hardware-Aware Model Selection Guide

Do not automatically pull the largest model. Choose based on available hardware:

| Machine Specs | Recommended Chat Model | Recommended Embedding Model | Estimated RAM / VRAM | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **8 GB RAM (CPU only)** | `llama3.2:1b` or `llama3.2:3b` | `nomic-embed-text` | ~2.5 GB RAM | Lightweight, responsive, low memory footprint |
| **16 GB RAM (CPU / Integrated GPU)** | `llama3.2:3b` | `nomic-embed-text` | ~4.0 GB RAM | Balanced reasoning, fast local responses |
| **16 GB+ RAM / Dedicated GPU (6GB+ VRAM)** | `qwen2.5:7b` or `llama3.1:8b` | `nomic-embed-text` | ~6.5 GB VRAM | High-accuracy structured outputs & complex planning |

To pull the default recommended models:
```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

To inspect installed models:
```bash
ollama list
```

---

## 5. Configuration & Environment Variables
Configure the agent using environment variables or a `.env` file copied from `.env.example`:

```bash
# Standard local runtime variables
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=llama3.2:3b
OLLAMA_EMBED_MODEL=nomic-embed-text
```

The runtime enforces **NFR1**: any external or cloud hostname configured in `OLLAMA_BASE_URL` will immediately raise an `OllamaLocalPolicyViolation`.

---

## 6. Verifying Local Chat & Embedding Inferences

### Verification via Python Client
```python
from backend.ollama_client import OllamaClient, OllamaConfig

client = OllamaClient()

# 1. Verify reachability & model discovery
print("Reachable:", client.is_reachable())
print("Installed models:", client.get_installed_model_names())

# 2. Verify local chat inference
chat_resp = client.chat(
    messages=[{"role": "user", "content": "Hello Go 81, are you local?"}],
    options={"temperature": 0.0, "num_predict": 20},
)
print("Chat Response:", chat_resp.content)
print("Inference Latency:", chat_resp.total_duration_ms, "ms")

# 3. Verify local embedding generation
embed_resp = client.embed("User preference: dark mode with SQLite WAL")
print("Vector Dimensions:", embed_resp.dimensions)
print("Embedding Duration:", embed_resp.total_duration_ms, "ms")
```

### Verification via HTTP CLI (curl)
```bash
# Chat verification
curl -X POST http://127.0.0.1:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3.2:3b", "messages": [{"role": "user", "content": "ping"}], "stream": false}'

# Embedding verification
curl -X POST http://127.0.0.1:11434/api/embed \
  -H "Content-Type: application/json" \
  -d '{"model": "nomic-embed-text", "input": "test embedding"}'
```

---

## 7. Common Diagnostics & Troubleshooting

| Error | Root Cause | Actionable Resolution |
| :--- | :--- | :--- |
| `OllamaConnectionError: Cannot connect to Ollama daemon` | Daemon is stopped or port is blocked | Run `ollama serve` in a terminal window. Verify port `11434` is listening. |
| `OllamaModelNotFoundError: Model 'llama3.2:3b' not found` | The model has not been downloaded locally | Run `ollama pull llama3.2:3b`. |
| `OllamaTimeoutError: Chat inference timed out` | Model loading or generation exceeded deadline | Check system CPU/RAM load; consider using a smaller quantized model (e.g. `llama3.2:1b`). |
| `OllamaLocalPolicyViolation: Sovereignty Violation` | An external cloud URL was supplied | Ensure `OLLAMA_BASE_URL` points to `http://127.0.0.1:11434` or `http://localhost:11434`. |

---

## 8. Running the Stage 1 Test Suite
Execute the focused Stage 1 suite:
```bash
python -m pytest tests/test_ollama_runtime_stage1.py -v
```

Execute the full project test suite:
```bash
python -m pytest tests/
```
