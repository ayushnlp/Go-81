# Go 81 — Stage 1 Repository Audit & Requirements Gap Analysis

## 1. Executive Summary & Stack Identification
- **Project Identity**: Go 81 (independent local-first sovereign AI agent).
- **Primary Backend Stack**: Python 3.12, FastAPI (`>=0.110.0`), Pydantic v2 (`>=2.6.0`), SQLite with WAL mode & Fernet AES-256 encryption (`cryptography>=42.0.0`), Uvicorn.
- **Frontend Stack**: Next.js 16 (App Router), TypeScript, Tailwind CSS, Lucide React, located in `frontend/`.
- **Existing Storage**: SQLite database file (`go81_memory.db`) with modular persistence in `app/memory/`.
- **Test Runner**: Pytest (`pytest>=8.0.0`, `pytest-asyncio>=0.23.0`).

---

## 2. Existing AI & Inference Architecture Audit
1. **Ad-Hoc Ollama Direct Calls**:
   - Direct HTTP calls were scattered across multiple backend files:
     - `backend/health.py`: calls `GET /api/tags` and `POST /api/generate`.
     - `backend/planner.py`: calls `POST /api/generate`.
     - `backend/main.py`: calls `POST /api/generate` in conversational chat routing.
   - **Gaps Identified**:
     - No centralized Ollama client or reusable service layer.
     - Legacy endpoint `/api/generate` was used instead of the official chat endpoint `POST /api/chat`.
     - Zero embedding inference client existed (no calls to `POST /api/embed`).
     - Configuration was split between `OLLAMA_ENDPOINT` and `OLLAMA_MODEL` without standard support for `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, and `OLLAMA_EMBED_MODEL`.
     - Model capability detection (e.g. structured output, tool support) was missing.

2. **Cloud AI & Outbound Telemetry Audit**:
   - Grep analysis for cloud endpoints (`openai`, `anthropic`, `gemini.api`, `groq`, `cohere`, `together.ai`) confirmed **zero remote cloud LLM calls**.
   - The only occurrence of cloud provider names was in `app/memory/flight_recorder.py`, used exclusively as regex patterns for redacting API keys from log strings.
   - **Local AI Invariant holds**: 100% local inference architecture is preserved.

3. **Configuration & Secrets**:
   - Environment variables used: `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`, `GO81_DB_PATH`, `GO81_ENCRYPTION_KEY`.
   - Unified `OllamaConfig` standardizes base URL, chat model, and embedding model.
   - No plaintext secrets or API keys are committed.

4. **Model Health Probing**:
   - `backend/health.py` provided a `probe_model_health()` function returning `ModelHealthReport` with four probe dimensions (reachable, present, inference, memory).
   - Exposing health via `GET /health` and `GET /api/agent/status` is already wired into `backend/main.py` and consumed by the Next.js frontend.

---

## 3. Existing vs Missing Functionality Matrix (Stage 1 Scope)

| Capability | Current State | Required State in Stage 1 | Action |
| :--- | :--- | :--- | :--- |
| **Central Ollama Client** | Missing (ad-hoc `httpx` in 3 files) | Unified, robust client class with timeouts, retries, and typed methods | Create `backend/ollama_client.py` |
| **Chat Inference** | Uses `/api/generate` string prompt | Uses official `POST /api/chat` with structured messages | Implement `OllamaClient.chat()` |
| **Embedding Inference** | Missing | Uses official `POST /api/embed` with vector validation | Implement `OllamaClient.embed()` |
| **Model Discovery & Show** | Only `/api/tags` inspected for names | Inspect `/api/tags` and `/api/show` for capabilities | Implement `list_models()`, `show_model()`, `check_model_capabilities()` |
| **Config Standard** | Scattered environment settings | Support `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL` | Implement unified `OllamaConfig` |
| **Local Policy Enforcement** | Implicit | Explicit validation rejecting non-local endpoints | Implement `enforce_local_policy()` |
| **Secret & Prompt Redaction** | Present in flight recorder | Client logging must redact prompts & tokens | Integrated sanitized logging |
| **Model Capability Diagnostics**| Missing | Structured JSON test & tool calling inspection | Implement capability smoke checks |

---

## 4. Test Suite Baseline Audit
- Initial test run executed **115 tests**:
  - 113 passed.
  - 1 test failure in `tests/test_planner_handshake.py` due to `"project"` being included in stop words in `app/memory/service.py`.
  - 1 test failure in `tests/test_task_runtime_fixes.py` related to task state filtering in `/api/tasks/incomplete`.
  - 1 Windows tempfile permission error during SQLite teardown in `tests/test_api_endpoints.py`.
- Remediation of these existing baseline issues will be performed alongside Stage 1 integration to guarantee a clean test suite.
