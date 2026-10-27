# Go 81: Frontend & Backend Integration Contract
**Author:** Engineer 3 (Frontend & Integration Lead)
**Target:** Python + FastAPI Backend Engineers (Engineers 1 & 2)
**Project:** Go 81: Sovereign Always-On Personal AI Agent
**Base URL:** `http://127.0.0.1:8000` (Localhost loopback only)

---

## 1. Architectural Invariants (Non-Negotiable)

1. **Zero Browser-to-Ollama Calls**: All LLM queries, tool analyses, and memory embeddings MUST route through the FastAPI backend. Browser code will never talk to port `11434` directly.
2. **Zero Outbound Telemetry**: No cloud LLM APIs, analytics pings, or foreign telemetry. All model weights must be served locally via Ollama (`127.0.0.1:11434`).
3. **Encrypted at Rest**: Persistent memory databases (SQLite / SQLCipher / DuckDB) must remain encrypted using user-held cryptographic keys.
4. **Approval Gatekeeper (Gjallarhorn)**: High-risk operations (writing files, executing shell commands, sending emails) cannot be autonomously completed without explicit just-in-time user authorization via `/api/approvals`.

---

## 2. API Endpoints Specification

### 2.1 System & Health Checks

#### `GET /health`
Returns quick health check for connection probing.

**Response `200 OK`**:
```json
{
  "status": "healthy",
  "version": "0.9.0",
  "ollama": {
    "status": "connected",
    "endpoint": "http://127.0.0.1:11434",
    "active_model": "llama3.2:3b-instruct-q8_0"
  }
}
```

#### `GET /api/agent/status`
Returns live system metrics and sovereign privacy statistics.

**Response `200 OK`**:
```json
{
  "online": true,
  "model": "llama3.2:3b-instruct-q8_0",
  "ollamaEndpoint": "http://127.0.0.1:11434",
  "ollamaStatus": "connected",
  "latencyMs": 142,
  "cpuPercent": 18.4,
  "ramUsageMb": 2480,
  "encryptedDatabase": {
    "status": "unlocked",
    "algorithm": "AES-256-GCM / SQLCipher",
    "totalRecords": 1428,
    "sizeKb": 8420
  },
  "telemetry": {
    "outboundBytes": 0,
    "sovereignGuarantee": true,
    "lastAuditTimestamp": "2026-10-25T12:00:00Z"
  },
  "activeSentinelsCount": 3,
  "pendingApprovalsCount": 1
}
```

---

### 2.2 Command Center & Chat

#### `POST /api/agent/chat`
Dispatches user prompt to sovereign agent.

**Request Body**:
```json
{
  "prompt": "Triage project emails and draft submission checklist",
  "mode": "chat" // "chat" | "task" | "memory"
}
```

**Response `200 OK`**:
```json
{
  "id": "msg-1730000000",
  "role": "agent",
  "content": "Queried local episodic saga and activated Heimdall email triage.",
  "timestamp": "12:15 PM",
  "thoughtTrace": "Step 1: Ingested mail headers.\nStep 2: Extracted 3 obligations.\nStep 3: Self-correction triggered.",
  "citedMemoryIds": ["mem-sem-01", "mem-epi-02"],
  "relatedTaskId": "task-go81-sync",
  "actionProposal": {
    "id": "appr-req-01",
    "toolName": "filesystem.write_file",
    "actionTitle": "Write Submission Checklist",
    "description": "Writes /go81/SUBMISSION_CHECKLIST.md and runs linters.",
    "riskLevel": "medium", // "low" | "medium" | "high" | "critical"
    "payload": { "path": "/go81/SUBMISSION_CHECKLIST.md" },
    "requiresApproval": true,
    "status": "pending"
  }
}
```

---

### 2.3 Task Workflow Orchestration (FR3)

#### `GET /api/tasks`
Lists all active and completed task execution graphs.

**Response `200 OK`**:
```json
[
  {
    "id": "task-01",
    "goal": "Audit Repository & Run Verification Checks",
    "status": "awaiting_approval", // "queued" | "running" | "awaiting_approval" | "completed" | "failed"
    "createdAt": "2026-10-25T11:45:00Z",
    "updatedAt": "2026-10-25T11:47:00Z",
    "priority": "high",
    "estimatedDurationMs": 45000,
    "steps": [
      {
        "id": "step-01",
        "stepNumber": 1,
        "title": "Query Local Episodic Saga",
        "skillName": "memory.recall_episodic",
        "status": "completed",
        "parameters": { "query": "Deliverables" },
        "output": "Retrieved 3 saga records.",
        "reflectionAttempt": 0
      },
      {
        "id": "step-02",
        "stepNumber": 2,
        "title": "Stage Local Submission Checklist",
        "skillName": "filesystem.write_file",
        "status": "awaiting_approval",
        "parameters": { "path": "SUBMISSION_CHECKLIST.md" },
        "reflectionAttempt": 0,
        "approvalRequestId": "appr-req-01"
      }
    ]
  }
]
```

#### `POST /api/tasks`
Creates and begins autonomous execution graph for an ambiguous user goal (FR3.1).

**Request Body**:
```json
{
  "goal": "Audit repository and run type checks",
  "priority": "normal"
}
```

---

### 2.4 Human Approval Gates (FR4.3)

#### `GET /api/approvals`
Lists pending approval requests.

#### `POST /api/approvals/{requestId}`
Submits user authorization or rejection.

**Request Body**:
```json
{
  "decision": "approved", // "approved" | "rejected"
  "notes": "Optional feedback for agent self-correction"
}
```

**Response `200 OK`**:
```json
{
  "success": true,
  "requestId": "appr-req-01",
  "status": "approved"
}
```

---

### 2.5 Memory Vault (FR1)

#### `GET /api/memories?type={episodic|semantic}`
Returns memory records.

#### `DELETE /api/memories/{id}`
Permanently prunes specific memory record ("Norn's cut").

#### `PATCH /api/memories/{id}`
Updates memory content/statement directly (NFR4.2 user control).

---

### 2.6 Registered Skills (FR2)

#### `GET /api/skills`
Returns list of registered skills with parameters and sandboxing boundaries.

#### `POST /api/skills/{id}/toggle`
Enables or disables skill execution.

---

### 2.7 Privacy & Settings

#### `GET /api/settings/privacy`
Returns current privacy and trigger parameters.

#### `PATCH /api/settings/privacy`
Updates configuration (model selection, prune threshold, CPU cap).
