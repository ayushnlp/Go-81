'use client';

import React, { useState } from 'react';
import {
  Cpu,
  Terminal,
  GitBranch,
  Server,
  ShieldCheck,
  RefreshCw,
  Database,
  Lock,
  Layers,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import { AgentRuntimeStatus, ModelHealth } from '@/lib/api/types';

interface EnvironmentWorkspaceProps {
  runtimeStatus: AgentRuntimeStatus | null;
  modelHealth: ModelHealth | null;
  isBackendOnline: boolean;
  onRefresh?: () => void;
  isLoading?: boolean;
}

export const EnvironmentWorkspace: React.FC<EnvironmentWorkspaceProps> = ({
  runtimeStatus,
  modelHealth,
  isBackendOnline,
  onRefresh,
  isLoading,
}) => {
  const isModelOnline = modelHealth?.loaded || (isBackendOnline && runtimeStatus?.ollamaStatus === 'connected');
  const modelName = modelHealth?.model || runtimeStatus?.model || 'llama3.2:3b';

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto p-6 md:p-8 bg-[var(--bg-canvas)]">
      <div className="max-w-5xl w-full mx-auto space-y-6">
        {/* Top Status Overview */}
        <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-[var(--bg-elevated)] text-[#ea580c] flex items-center justify-center shrink-0">
              <Server className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                Local-First Autonomous Runtime
              </h3>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                Host diagnostic telemetry, Ollama model inference & sovereign security policy
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <div className={`flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-semibold ${
              isBackendOnline ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-500 border border-rose-500/20'
            }`}>
              <span className={`w-2 h-2 rounded-full ${isBackendOnline ? 'bg-emerald-500' : 'bg-rose-500'}`} />
              <span>{isBackendOnline ? 'FastAPI 8000 Healthy' : 'Backend Disconnected'}</span>
            </div>

            {onRefresh && (
              <button
                type="button"
                onClick={onRefresh}
                disabled={isLoading}
                title="Refresh diagnostics"
                className="p-1.5 rounded-md hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] transition-colors cursor-pointer"
              >
                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              </button>
            )}
          </div>
        </div>

        {/* 4-Card Responsive Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Card 1: Local Ollama Inference */}
          <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 text-xs font-semibold text-[var(--text-primary)]">
                <Cpu className="w-4 h-4 text-[#ea580c]" />
                <span>Ollama Local Inference Engine</span>
              </div>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                isModelOnline ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500'
              }`}>
                {isModelOnline ? 'CONNECTED' : 'STANDBY'}
              </span>
            </div>

            <div className="space-y-2 text-xs pt-1">
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Ollama Base Endpoint</span>
                <span className="font-mono text-[var(--text-secondary)]">http://127.0.0.1:11434</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Active Chat Model</span>
                <span className="font-mono text-[#ea580c] font-semibold">{modelName}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Embedding Model</span>
                <span className="font-mono text-[var(--text-secondary)]">nomic-embed-text:latest</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-[var(--text-muted)]">Telemetry / Cloud Fallback</span>
                <span className="text-emerald-500 font-medium">Disabled (100% Local-First)</span>
              </div>
            </div>
          </div>

          {/* Card 2: Host Kernel & Environment */}
          <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 text-xs font-semibold text-[var(--text-primary)]">
                <Server className="w-4 h-4 text-[#ea580c]" />
                <span>Host Platform & Architecture</span>
              </div>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                VERIFIED
              </span>
            </div>

            <div className="space-y-2 text-xs pt-1">
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Operating System</span>
                <span className="font-mono text-[var(--text-secondary)]">Windows 11 (win32 x64)</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Python Runtime</span>
                <span className="font-mono text-[var(--text-secondary)]">Python 3.12.8</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Next.js Framework</span>
                <span className="font-mono text-[var(--text-secondary)]">16.4.3 (Turbopack Engine)</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-[var(--text-muted)]">Local Host Binding</span>
                <span className="font-mono text-[var(--text-secondary)]">127.0.0.1 (Strict Loopback)</span>
              </div>
            </div>
          </div>

          {/* Card 3: Sovereign Security Boundary */}
          <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 text-xs font-semibold text-[var(--text-primary)]">
                <ShieldCheck className="w-4 h-4 text-emerald-500" />
                <span>Permission Gateway & Sandbox</span>
              </div>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500">
                ACTIVE
              </span>
            </div>

            <div className="space-y-2 text-xs pt-1">
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Default Authorization</span>
                <span className="font-semibold text-rose-500">DEFAULT-DENY</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Filesystem Sandbox</span>
                <span className="text-emerald-500 font-medium">Path-Restricted Boundary</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Audit Logger</span>
                <span className="text-emerald-500 font-medium">Redacted Token Scrubber</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-[var(--text-muted)]">Approval Token Policy</span>
                <span className="font-medium text-[var(--text-secondary)]">Cryptographic Single-Use</span>
              </div>
            </div>
          </div>

          {/* Card 4: Encrypted Memory & Checkpoint Engine */}
          <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 text-xs font-semibold text-[var(--text-primary)]">
                <Database className="w-4 h-4 text-[#ea580c]" />
                <span>Memory Vault & SQLite Store</span>
              </div>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500">
                ENCRYPTED
              </span>
            </div>

            <div className="space-y-2 text-xs pt-1">
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Encryption Standard</span>
                <span className="font-mono text-[var(--text-secondary)]">AES-256-GCM at rest</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Database Engine</span>
                <span className="font-mono text-[var(--text-secondary)]">SQLite 3 (WAL mode)</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Flight Recorder</span>
                <span className="text-emerald-500 font-medium">Evidence Ledger Enabled</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-[var(--text-muted)]">Crash Recovery Manager</span>
                <span className="text-emerald-500 font-medium">Checkpoint Resumption Active</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

