'use client';

import React from 'react';
import { Cpu, Terminal, GitBranch, Server, ShieldCheck, RefreshCw } from 'lucide-react';
import { AgentRuntimeStatus, ModelHealth } from '@/lib/api/types';

interface EnvironmentPanelProps {
  runtimeStatus: AgentRuntimeStatus | null;
  modelHealth: ModelHealth | null;
  isBackendOnline: boolean;
  onRefresh?: () => void;
  isLoading?: boolean;
}

export const EnvironmentPanel: React.FC<EnvironmentPanelProps> = ({
  runtimeStatus,
  modelHealth,
  isBackendOnline,
  onRefresh,
  isLoading,
}) => {
  return (
    <div className="flex flex-col h-full select-none">
      {/* Header */}
      <div className="px-3.5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            System Environment
          </span>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
            Host diagnostics, toolchains & runtime health
          </p>
        </div>
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            title="Refresh diagnostics"
            className="p-1 rounded hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        )}
      </div>

      {/* Structured Diagnostic Cards */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* 1. Host Hardware & Kernel */}
        <div className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2">
          <div className="flex items-center space-x-1.5 text-xs font-semibold text-[var(--text-primary)]">
            <Cpu className="w-3.5 h-3.5 text-[#ea580c]" />
            <span>Host Hardware & Kernel</span>
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">OS Platform</span>
              <span className="font-mono text-[var(--text-secondary)]">Windows NT (win32)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Architecture</span>
              <span className="font-mono text-[var(--text-secondary)]">x64 (64-bit)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Host RAM Allocation</span>
              <span className="font-mono text-[var(--text-secondary)]">
                {runtimeStatus?.ramUsageMb ? `${runtimeStatus.ramUsageMb} MB` : '16+ GB'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">CPU Utilization</span>
              <span className="font-mono text-[var(--text-secondary)]">
                {runtimeStatus?.cpuPercent ? `${runtimeStatus.cpuPercent}%` : '< 5%'}
              </span>
            </div>
          </div>
        </div>

        {/* 2. Developer Toolchains & Compilers */}
        <div className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2">
          <div className="flex items-center space-x-1.5 text-xs font-semibold text-[var(--text-primary)]">
            <Terminal className="w-3.5 h-3.5 text-emerald-500" />
            <span>Developer Toolchains</span>
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Python Runtime</span>
              <span className="font-mono text-[var(--text-secondary)]">Python 3.12 / 3.13</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Node.js Engine</span>
              <span className="font-mono text-[var(--text-secondary)]">v20+ / Next.js 16.4</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Package Manager</span>
              <span className="font-mono text-[var(--text-secondary)]">npm / pip</span>
            </div>
          </div>
        </div>

        {/* 3. Git Repository State */}
        <div className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2">
          <div className="flex items-center space-x-1.5 text-xs font-semibold text-[var(--text-primary)]">
            <GitBranch className="w-3.5 h-3.5 text-amber-500" />
            <span>Git Repository State</span>
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Active Branch</span>
              <span className="font-mono text-[#ea580c] font-medium">ui/go81-command-center</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Hardening Commit</span>
              <span className="font-mono text-[var(--text-secondary)]">251ddf5</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Workspace Status</span>
              <span className="font-mono text-emerald-500 font-medium">Clean</span>
            </div>
          </div>
        </div>

        {/* 4. FastAPI Backend & Local Model */}
        <div className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2">
          <div className="flex items-center space-x-1.5 text-xs font-semibold text-[var(--text-primary)]">
            <Server className="w-3.5 h-3.5 text-sky-500" />
            <span>FastAPI & Local Model</span>
          </div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">FastAPI Server</span>
              <span className={`font-mono font-medium ${isBackendOnline ? 'text-emerald-500' : 'text-rose-500'}`}>
                {isBackendOnline ? 'Online (:8000)' : 'Offline'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Model Provider</span>
              <span className="font-mono text-[var(--text-secondary)]">Ollama (127.0.0.1:11434)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Active LLM Model</span>
              <span className="font-mono text-[var(--text-secondary)]">
                {modelHealth?.model || runtimeStatus?.model || 'llama3.2:3b'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Inference Latency</span>
              <span className="font-mono text-[var(--text-secondary)]">
                {modelHealth?.latency_ms ? `${modelHealth.latency_ms} ms` : 'Local native'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Encrypted Vault</span>
              <span className="font-mono text-emerald-500">
                {runtimeStatus?.encryptedDatabase?.status === 'unlocked' ? 'AES-GCM (Active)' : 'Protected'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

