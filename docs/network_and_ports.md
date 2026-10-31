# Go 81 Network Architecture & Port Specification

This document details the canonical network ports, communication topology, and proxy bridging configuration for the Go 81 Sovereign Agent system.

---

## 1. Canonical Network Architecture

The standard Go 81 deployment operates on three dedicated local ports:

| Service | Canonical Host & Port | Description |
| :--- | :--- | :--- |
| **Frontend Web UI** | `http://localhost:3000` | Next.js 15 App Router production/development client |
| **Backend Orchestrator** | `http://127.0.0.1:8000` | Python FastAPI Sovereign Agent API & Execution Engine |
| **Local LLM & Embeddings** | `http://127.0.0.1:11434` | Ollama Daemon (`llama3.2:3b` chat, `nomic-embed-text` vectors) |

### Key Architectural Invariants:
1. **Local-First & Sovereign**: All network traffic remains strictly on local loopback interfaces (`127.0.0.1` / `localhost`). Zero external or cloud API calls are made.
2. **Canonical Frontend Port**: Port `3000` is the single canonical port for the Go 81 User Interface.
3. **Canonical Backend Port**: Port `8000` is the single canonical port for the FastAPI backend.
4. **FastAPI CORS**: The backend accepts requests from `http://localhost:3000`, `http://localhost:3001`, `http://localhost:5173`, and local origin variants.

---

## 2. Optional Compatibility Proxy (`scripts/proxy_3001.js`)

To accommodate operator environments, legacy bookmarks, or multi-port test harnesses that reference port 3001, Go 81 includes an optional, zero-dependency Node.js reverse proxy.

### Purpose
- Transparently routes incoming HTTP traffic from `http://127.0.0.1:3001` to canonical `http://127.0.0.1:3000`.
- Ensures headers, paths, methods, and payloads are preserved.
- **Port 3001 is strictly an optional convenience proxy and is NOT an application requirement or dependency.** Go 81 is fully operable directly on port 3000.

### Starting the Compatibility Proxy
```bash
node scripts/proxy_3001.js
```
Console confirmation:
```
Proxy listening on http://127.0.0.1:3001 -> http://127.0.0.1:3000
```

### Stopping the Compatibility Proxy
- In an interactive terminal: Press `Ctrl + C`.
- In PowerShell background / script:
  ```powershell
  Get-Process -Name node | Where-Object { $_.CommandLine -like "*proxy_3001*" } | Stop-Process -Force
  ```

---

## 3. Connection Status Indicator & Diagnostics

The Go 81 Top Navigation Bar features an active connection indicator dot:
- **Pulsing Emerald Green (`bg-emerald-500`)**: Backend online, model healthy, inference active (`Backend Connected`).
- **Amber Yellow (`bg-amber-400`)**: Backend reachable, but model inference degraded or loading (`Service Degraded`).
- **Solid Orange (`bg-[#ea580c]`)**: Backend unreachable at `http://127.0.0.1:8000` (`Backend Disconnected`).

### Troubleshooting Connectivity:
1. **Verify Backend Status**:
   ```bash
   curl http://127.0.0.1:8000/health
   # Expected response: {"status":"healthy"}
   ```
2. **Verify Frontend Status**:
   ```bash
   curl http://localhost:3000
   ```
3. **Browser Refresh**:
   If the backend was restarted while a browser tab was open, perform a hard refresh (`Ctrl + Shift + R` or `Ctrl + F5`) in Microsoft Edge / Chrome / Firefox to clear cached disconnect state and re-probe health.

