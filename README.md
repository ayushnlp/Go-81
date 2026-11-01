# ⚡ Go 81
### Sovereign, Local-First Autonomous AI Agent
*Architecting Privacy-Preserving Autonomous Workflows, Iterative Task Loops, and Secure Web Automation on a Fully Local, Ollama-Based Stack.*

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Next.js 16](https://img.shields.io/badge/next.js-16.4.3-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/playwright-1.64.1-green.svg)](https://playwright.dev/)
[![Tests Passing](https://img.shields.io/badge/tests-287%20passed-brightgreen.svg)]()
[![Zero Cloud Telemetry](https://img.shields.io/badge/telemetry-0%20KB-success.svg)]()

---

## 🏛️ System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Go 81 COMMAND CENTER                            │
│     Next.js 16 (App Router) • TypeScript • Tailwind CSS Dark Theme     │
├────────────────────────────────────────────────────────────────────────┤
│  [ Command Center ]  [ Task Timeline ]  [ Memory Vault ]  [ Skills ]   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / JSON / SSE (:3000 / :3001)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 FASTAPI BACKEND ORCHESTRATOR (:8000)                   │
│  • Autonomous Agent Loop (Stage 6)   • Checkpoint Recovery (Stage 7)   │
│  • DAG Task Planner & Orchestrator   • Permission Gateway & Approvals  │
│  • Playwright Browser Engine (St. 8) • Skill Execution Sandbox         │
│  • Conversational Engine (Stage 5)   • Two-Phase Execution Journal     │
└──────────────┬────────────────────┬────────────────────┬───────────────┘
               │                    │                    │
               ▼                    ▼                    ▼
 ┌──────────────────────────┐ ┌───────────────────┐ ┌───────────────────┐
 │   LOCAL OLLAMA ENGINE    │ │  ENCRYPTED MEMORY │ │ HEADLESS CHROMIUM │
 │    (127.0.0.1:11434)     │ │   (AES-256-GCM)   │ │  (PLAYWRIGHT St.8)│
 │ • llama3.2:3b (Inference)│ │ • Episodic Sagas  │ │ • Ephemeral Ctx   │
 │ • nomic-embed-text (Vec) │ │ • Semantic Memory │ │ • SSRF Validator  │
 │ • 100% Local Inference   │ │ • Two-Phase Jrnl  │ │ • Click Defense   │
 └──────────────────────────┘ └───────────────────┘ └───────────────────┘
```

---

## 🌟 Core Capabilities & Stages

Go 81 is developed under strict, verifiable milestone stages:

### 🧠 Stage 1 & 2: Local AI Inference & Encrypted Memory Vault
- **Zero Cloud Telemetry:** 100% local model execution via Ollama (`llama3.2:3b` for planning & reasoning, `nomic-embed-text` for embeddings).
- **Encrypted Persistence at Rest:** SQLite database secured with AES-256-GCM encryption.
- **Three-Tier Memory Subsystem:**
  - *Episodic Memory:* Timestamped task histories and conversational interactions.
  - *Semantic Memory:* Vector-embedded persistent facts, user preferences, and system knowledge with decay scoring.
  - *Procedural Memory:* Reusable execution plans and tool interaction routines.

### 🛡️ Stage 3 & 4: Skill Sandbox, Permission Gateway & DAG Orchestrator
- **Deterministic Permission Gateway:** Strict default-deny capability enforcement with risk tiers (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- **Cryptographic Action Tokens:** Tamper-evident, single-use approval tokens bound to canonical parameter hashes.
- **DAG Task Planner & Orchestrator:** Decomposes complex user goals into directed acyclic graphs (DAGs), resolving step dependencies with topological sorting and real-time SSE streaming.
- **Flight Recorder:** Durable audit trail capturing execution events, inputs, outputs, and authorization decisions.

### 💬 Stage 5 & 5.1: Conversational Intelligence Engine
- **Context-Aware Dialogue:** Multi-turn conversational engine synthesizing user preferences and relevant semantic memories.
- **Deterministic Math Engine:** Built-in safe AST calculator resolving arithmetic expressions without hallucination.
- **Modern Command Center UI:** Unified search, dark/light themes, live status indicators, and responsive command center navigation.

### 🔄 Stage 6: Autonomous Agent Loop & Iterative Execution
- **Closed-Loop Autonomous Lifecycle:**
  $$\text{GOAL} \longrightarrow \text{PLAN} \longrightarrow \text{VALIDATE} \longrightarrow \text{EXECUTE} \longrightarrow \text{OBSERVE} \longrightarrow \text{EVALUATE} \longrightarrow \text{REPLAN} / \text{COMPLETE}$$
- **Truthful Observation Layer:** Gathers real step outcomes (`StepObservation`), distinguishes between intended plans and actual execution evidence.
- **Goal Evaluator & Idempotency Engine:** Classifies skills into `READ_ONLY`, `IDEMPOTENT`, `NON_IDEMPOTENT`, and `IRREVERSIBLE_HIGH_RISK`. Protects non-idempotent actions from unsafe automatic retries.
- **Bounded Replanning:** Preserves successfully completed steps while formulating surgical replacement subgraphs for failed steps without side-effect duplication.

### 💾 Stage 7: Checkpoint Recovery & Crash Consistency
- **Two-Phase Execution Journal:** Records two-phase transactional intents (`DISPATCHING` $\rightarrow$ `SUCCEEDED` / `FAILED`) to reconcile interrupted steps upon backend reboot.
- **OS Subprocess Tracking & Reattachment:** Tracks active OS child processes via PID, start time, and exit status, distinguishing between still-running and terminated processes across restarts.
- **Anti-Replay Ledger:** Prevents replay of consumed approval tokens or duplicate execution of irreversible steps.

### 🌐 Stage 8 & 8.1: Autonomous Browser & Web Automation Subsystem
- **Headless Chromium Engine:** Reusable Playwright runtime (`playwright.async_api`) providing 9 autonomous browser skills:
  - `browser.navigate` (SSRF-protected navigation)
  - `browser.inspect` (DOM text extraction with invisible element stripping)
  - `browser.click` (Consequential click protected)
  - `browser.fill` (Credential-redacted input)
  - `browser.select` (Dropdown/checkbox selection)
  - `browser.screenshot` (Password-masked viewport captures)
  - `browser.download` (Bounded 10MB file download verification)
  - `browser.upload` (Traversal-safe file uploads; gated)
  - `browser.submit` (Form submissions; approval-gated)
- **Consequential Click Protection:** Inspects target element roles, accessible names, text, and form context on the live DOM. High-risk operations (submit, purchase, payment, registration, application, deletion, messaging) strictly require explicit single-use approval tokens bound to the domain, URL, selector, and element identity. Ambiguous actions fail closed.
- **Advanced SSRF Defense:** Enforced at both URL resolution and context route interception (`context.route("**/*")`). Blocks IPv4/IPv6 loopback, RFC 1918 private subnets, cloud metadata (`169.254.169.254`), alternative IP encodings (dword, hex, octal), 6to4 (`2002::/16`), Teredo (`2001::/32`), and prohibited schemes. Service workers are blocked (`service_workers="block"`) to prevent interception bypasses.
- **Multilingual Prompt Injection Defense:** Detects and neutralizes prompt-override patterns across English, Russian, Chinese, Spanish, French, and German; strips zero-width spaces; collapses spaced character evasions; and enforces deterministic `PermissionGateway` boundaries.
- **Full Credential Redaction:** Passwords, tokens, OTPs, CVVs, and credit card numbers are scrubbed across nested JSON, URL parameters, logs, and headers. Password inputs are masked (`••••••••`) before viewport screenshot captures.

---

## 🚀 Getting Started

### Prerequisites
- **Python**: 3.12+
- **Node.js**: 20+
- **Ollama**: Installed and running locally
- **Playwright Chromium**: Installed locally

### 1. Ollama Model Setup
Ensure Ollama is running and pull the verified models:
```bash
ollama serve
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### 2. Backend Setup
```bash
# Clone the repository
git clone https://github.com/ayushnlp/Go-81.git
cd "Go 81"

# Create virtual environment & activate
python -m venv .venv
.venv\Scripts\activate   # Windows PowerShell / CMD
# source .venv/bin/activate  # Linux / macOS

# Install backend dependencies
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium

# Launch the FastAPI backend (Port 8000)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Frontend Setup
```bash
cd frontend

# Install frontend dependencies
npm install

# Start Next.js development server (Port 3000)
npm run dev
# OR build and run optimized production server:
# npm run build && npm start
```

### 4. Optional Port 3001 Compatibility Proxy
If using tools or integrations targeting port 3001:
```bash
node scripts/proxy_3001.js
```

---

## 🧪 Comprehensive Verification & Test Suite

Go 81 features exhaustive, deterministic automated test coverage across all subsystems:

```bash
# Run Full Project Regression (287 passed, 2 skipped, 0 failed)
python -m pytest tests/ -v

# Run Autonomous Browser & Security Suite (Stage 8 & 8.1 - 24 tests)
python -m pytest tests/test_stage8_browser_automation.py -v

# Run Autonomous Agent Loop & Recovery Suites (Stages 6 & 7 - 29 tests)
python -m pytest tests/test_stage6_autonomous_agent_loop.py tests/test_stage7_checkpoint_recovery.py -v

# Run Independent Real Chromium Smoke Test (8/8 verified)
python tests/verify_real_chromium.py

# Run Frontend Typecheck & Build
cd frontend && npx tsc --noEmit && npm run build
```

---

## 🌐 Network Architecture & Ports

| Port | Service | Protocol | Access Policy |
|---|---|---|---|
| `8000` | FastAPI Backend | HTTP / REST / SSE | Localhost only (`127.0.0.1`) |
| `3000` | Next.js Frontend | HTTP / Web | Localhost only (`127.0.0.1`) |
| `3001` | Reverse Proxy | HTTP | Forwards to `3000` |
| `11434` | Ollama LLM Daemon | HTTP | Localhost only (`127.0.0.1`) |

*All internal ports are blocked from browser automation navigation via `SSRFValidator` to prevent loopback port abuse.*

---

## 🛡️ Sovereign Invariants (Non-Functional Requirements)

- **100% Local Inference:** All reasoning, planning, and embeddings execute strictly on localhost.
- **Zero Cloud Leak:** 0 KB outbound telemetry. No third-party API keys required.
- **Data Integrity & Crash Consistency:** Checkpoints, journal transactions, and process states survive unexpected terminations.
- **Human-in-the-Loop Authority:** Irreversible, high-risk, and consequential browser actions require explicit human approval before execution.

---

## 📄 License

Sovereign Local-First Open Source — Project Go 81.
