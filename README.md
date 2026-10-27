# ⚡ Go 81
### Sovereign, Always-On Personal AI Agent
*Architecting Privacy-Preserving Autonomous Workflows with Persistent Memory on a Fully Local, Ollama-Based Stack.*

---

## 🏛️ System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Go 81 COMMAND CENTER                            │
│     Next.js 16 (App Router) • TypeScript • Restrained Dark Theme       │
├────────────────────────────────────────────────────────────────────────┤
│  [ Command Center ]  [ Task Timeline ]  [ Memory Vault ]  [ Skills ]   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / JSON
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 FASTAPI ORCHESTRATOR (:8000)                           │
│  - Task Graph Planner (FR3.1)       - Gjallarhorn Approval Gate (FR4.3)│
│  - Mimir Memory Vector Store (FR1)  - Dwarves' Forge Sandboxing (FR2)  │
│  - Heimdall Sentinel Daemons (FR4)  - Norns Forgetting Engine (FR1.3)  │
└───────────────────┬──────────────────────────────────┬─────────────────┘
                    │                                  │
                    ▼                                  ▼
      ┌───────────────────────────┐      ┌───────────────────────────┐
      │   LOCAL OLLAMA INFERENCE  │      │  ENCRYPTED RUNES AT REST  │
      │      (127.0.0.1:11434)    │      │  (AES-256-GCM / SQLCipher)│
      │   • llama3.2:3b           │      │  • Episodic Saga Logs     │
      │   • nomic-embed-text      │      │  • Semantic Facts & Rules │
      └───────────────────────────┘      └───────────────────────────┘
```

---

## 🚀 Quick Start (Frontend)

### Prerequisites
- Node.js 20+
- npm 10+

### Launching Frontend
```bash
cd frontend
npm install
npm run dev
```

The command center will be available at [`http://localhost:3000`](http://localhost:3000).

### Offline Staging Preview
If the FastAPI backend at `http://127.0.0.1:8000` is offline or still starting up, the frontend automatically falls back to isolated demonstration fixtures with an honest, prominent status banner. You can inspect all screens, audit memory runes, and interact with the approval gates without crashes.

---

## 📂 Repository Structure

- `frontend/` — Next.js 16 App Router application
  - `src/app/` — Pages: Command Center (`/`), Task Timeline (`/tasks`), Memory Vault (`/memory`), Skills Forge (`/skills`), Privacy & Settings (`/settings`)
  - `src/components/shell/` — Persistent `AppSidebar` and `AppHeader`
  - `src/components/tasks/` — `TaskTimelineCard` and `ApprovalModal`
  - `src/components/ui/` — Accessible Badges, Buttons, Cards, Modals, and OfflineBanner
  - `src/lib/api/` — Typed API client boundary (`client.ts`), domain contracts (`types.ts`), and isolated staging fixtures (`fixtures.ts`)
- `CONTRACT.md` — Integration contract and API schema for Engineers 1 & 2 developing the FastAPI backend
- `backend/` — Reserved workspace for Python teammates

---

## 🛡️ Sovereign Invariants (NFR1 - NFR4)

- **Local Inference**: 100% of LLM tokens generated on localhost via Ollama.
- **Zero Cloud Leak**: 0 KB outbound telemetry. No external API keys.
- **Encrypted Memory**: AES-256 sealed memory store with user control and forgetting capabilities.
- **Human Approval Gates**: Granular RBAC ensuring high-risk actions cannot proceed without user consent.
