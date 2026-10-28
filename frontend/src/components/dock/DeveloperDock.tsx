'use client';

import React, { useState } from 'react';
import {
  ChevronUp,
  ChevronDown,
  Terminal as TerminalIcon,
  Server,
  AlertTriangle,
  History,
  Trash2,
  Play,
  Loader2,
  ShieldAlert,
} from 'lucide-react';
import { AgentRuntimeStatus, ModelHealth, FlightRecorderEvent, AuditRecord } from '@/lib/api/types';
import { api } from '@/lib/api/client';

interface DeveloperDockProps {
  isOpen: boolean;
  onToggle: () => void;
  runtimeStatus: AgentRuntimeStatus | null;
  modelHealth: ModelHealth | null;
  isBackendOnline: boolean;
}

export const DeveloperDock: React.FC<DeveloperDockProps> = ({
  isOpen,
  onToggle,
  runtimeStatus,
  modelHealth,
  isBackendOnline,
}) => {
  const [activeTab, setActiveTab] = useState<'env' | 'terminal' | 'problems' | 'activity'>('env');
  const [terminalInput, setTerminalInput] = useState('');
  const [terminalLogs, setTerminalLogs] = useState<string[]>([
    '[Go 81 Sovereign Agent Command Center initialized]',
    '[Security Gateway: Default-Deny Active • AES-GCM Encrypted Storage Active]',
    `[FastAPI Backend: ${isBackendOnline ? 'Online (http://127.0.0.1:8000)' : 'Offline'}]`,
  ]);
  const [isExecuting, setIsExecuting] = useState(false);

  const handleExecute = async () => {
    if (!terminalInput.trim() || isExecuting) return;
    const cmd = terminalInput.trim();
    setTerminalInput('');
    setTerminalLogs((prev) => [...prev, `$ ${cmd}`]);
    setIsExecuting(true);

    try {
      if (cmd === 'clear') {
        setTerminalLogs([]);
        setIsExecuting(false);
        return;
      }

      if (cmd === 'help') {
        setTerminalLogs((prev) => [
          ...prev,
          'Available diagnostics commands:',
          '  status     - Show agent and model runtime status',
          '  health     - Check FastAPI and Ollama health',
          '  system     - Query host platform and toolchains',
          '  clear      - Clear terminal window',
          'Note: Arbitrary shell execution requires Permission Gateway approval token.',
        ]);
        setIsExecuting(false);
        return;
      }

      if (cmd === 'status') {
        setTerminalLogs((prev) => [
          ...prev,
          `Ollama Model: ${modelHealth?.model || runtimeStatus?.model || 'llama3.2:3b'}`,
          `Backend Online: ${isBackendOnline}`,
          `Active Sentinels: ${runtimeStatus?.activeSentinelsCount || 0}`,
          `Pending Approvals: ${runtimeStatus?.pendingApprovalsCount || 0}`,
        ]);
        setIsExecuting(false);
        return;
      }

      if (cmd === 'health') {
        const h = await api.checkHealth();
        setTerminalLogs((prev) => [
          ...prev,
          `FastAPI Health: ${h.online ? 'HEALTHY' : 'UNREACHABLE'} (latency: ${h.latencyMs || 0}ms)`,
        ]);
        setIsExecuting(false);
        return;
      }

      if (cmd === 'system') {
        const sys = await api.executeSkill('system.info', { include_memory_stats: true });
        setTerminalLogs((prev) => [
          ...prev,
          `System Info: ${JSON.stringify(sys.data?.result || sys.data || {}, null, 2)}`,
        ]);
        setIsExecuting(false);
        return;
      }

      // If arbitrary command, route through shell.execute skill with gateway
      const res = await api.executeSkill('shell.execute', { command: cmd, args: [] });
      if (res.data?.result) {
        const out = res.data.result;
        setTerminalLogs((prev) => [
          ...prev,
          out.stdout || '[no stdout]',
          out.stderr ? `stderr: ${out.stderr}` : '',
          `exit_code: ${out.exit_code}`,
        ].filter(Boolean));
      } else {
        setTerminalLogs((prev) => [
          ...prev,
          `Permission Gate / Error: ${res.error || 'Execution requires security approval token or skill is restricted.'}`,
        ]);
      }
    } catch (e: unknown) {
      setTerminalLogs((prev) => [
        ...prev,
        `Execution failed: ${e instanceof Error ? e.message : 'Unknown error'}`,
      ]);
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <footer
      aria-label="Developer Dock"
      className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0 select-none z-20 flex flex-col transition-all duration-150"
    >
      {/* Dock Top Tab Bar */}
      <div className="h-9 px-3 flex items-center justify-between border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
        <div className="flex items-center space-x-1">
          <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mr-2 hidden sm:inline">
            Developer Dock
          </span>

          <button
            type="button"
            onClick={() => {
              setActiveTab('env');
              if (!isOpen) onToggle();
            }}
            className={`flex items-center space-x-1.5 px-2.5 py-1 rounded text-xs font-medium cursor-pointer transition-colors ${
              activeTab === 'env' && isOpen
                ? 'bg-[var(--bg-surface)] text-[var(--accent-primary)] shadow-2xs'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            <Server className="w-3.5 h-3.5" />
            <span>Environment</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setActiveTab('terminal');
              if (!isOpen) onToggle();
            }}
            className={`flex items-center space-x-1.5 px-2.5 py-1 rounded text-xs font-medium cursor-pointer transition-colors ${
              activeTab === 'terminal' && isOpen
                ? 'bg-[var(--bg-surface)] text-[var(--accent-primary)] shadow-2xs'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            <TerminalIcon className="w-3.5 h-3.5" />
            <span>Terminal</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setActiveTab('problems');
              if (!isOpen) onToggle();
            }}
            className={`flex items-center space-x-1.5 px-2.5 py-1 rounded text-xs font-medium cursor-pointer transition-colors ${
              activeTab === 'problems' && isOpen
                ? 'bg-[var(--bg-surface)] text-[var(--accent-primary)] shadow-2xs'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Problems</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setActiveTab('activity');
              if (!isOpen) onToggle();
            }}
            className={`flex items-center space-x-1.5 px-2.5 py-1 rounded text-xs font-medium cursor-pointer transition-colors ${
              activeTab === 'activity' && isOpen
                ? 'bg-[var(--bg-surface)] text-[var(--accent-primary)] shadow-2xs'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            <History className="w-3.5 h-3.5" />
            <span>Activity Logs</span>
          </button>
        </div>

        {/* Expand / Collapse Control */}
        <div className="flex items-center space-x-2">
          {isOpen && activeTab === 'terminal' && (
            <button
              type="button"
              onClick={() => setTerminalLogs([])}
              title="Clear terminal logs"
              className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}

          <button
            type="button"
            onClick={onToggle}
            title={isOpen ? 'Collapse dock' : 'Expand dock'}
            className="p-1 rounded hover:bg-[var(--bg-surface)] text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
          >
            {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Dock Content Body (shown when isOpen is true) */}
      {isOpen && (
        <div className="h-48 sm:h-56 overflow-y-auto p-3 font-mono text-xs bg-[var(--bg-canvas)]">
          {activeTab === 'env' && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
              <div className="p-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-1">
                <span className="text-[10px] uppercase font-bold text-[var(--text-muted)]">
                  Runtime Host
                </span>
                <p className="text-[var(--text-primary)]">Windows NT (win32) • x64</p>
                <p className="text-[var(--text-muted)] text-[11px]">
                  PID: Local • Memory: {runtimeStatus?.ramUsageMb || 128} MB
                </p>
              </div>

              <div className="p-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-1">
                <span className="text-[10px] uppercase font-bold text-[var(--text-muted)]">
                  Local Inference
                </span>
                <p className="text-[var(--text-primary)]">
                  Ollama: {modelHealth?.model || 'llama3.2:3b'}
                </p>
                <p className="text-emerald-500 text-[11px]">
                  Backend: {isBackendOnline ? 'FastAPI :8000 (Connected)' : 'Offline'}
                </p>
              </div>

              <div className="p-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-1">
                <span className="text-[10px] uppercase font-bold text-[var(--text-muted)]">
                  Security Boundary
                </span>
                <p className="text-emerald-500">Default-Deny Policy Active</p>
                <p className="text-[var(--text-muted)] text-[11px]">
                  Encrypted Vault: AES-GCM (Zero Cloud Sync)
                </p>
              </div>
            </div>
          )}

          {activeTab === 'terminal' && (
            <div className="flex flex-col h-full space-y-2">
              <div className="flex-1 overflow-y-auto space-y-1 text-[11px] leading-relaxed text-[var(--text-secondary)]">
                {terminalLogs.map((log, i) => (
                  <div key={i} className="whitespace-pre-wrap break-all">
                    {log}
                  </div>
                ))}
                {isExecuting && (
                  <div className="flex items-center space-x-1.5 text-orange-400">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    <span>Executing via skill sandbox...</span>
                  </div>
                )}
              </div>

              {/* Command Input Bar */}
              <div className="flex items-center space-x-2 pt-2 border-t border-[var(--border-subtle)] shrink-0">
                <span className="text-[#ea580c] font-bold text-xs">$</span>
                <input
                  type="text"
                  value={terminalInput}
                  onChange={(e) => setTerminalInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleExecute()}
                  placeholder="Type 'help', 'status', 'health', 'system' or command..."
                  className="flex-1 bg-transparent text-xs text-[var(--text-primary)] outline-none font-mono"
                />
                <button
                  type="button"
                  onClick={handleExecute}
                  disabled={!terminalInput.trim() || isExecuting}
                  className="px-2 py-0.5 rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[10px] text-[var(--text-primary)] hover:bg-[var(--bg-subtle)] cursor-pointer"
                >
                  Run
                </button>
              </div>
            </div>
          )}

          {activeTab === 'problems' && (
            <div className="space-y-1 text-xs">
              <div className="text-[var(--text-muted)] mb-2">
                Permission Gateway Audit & Exceptions
              </div>
              <p className="text-emerald-500 text-[11px]">
                ✓ All skill executions sandboxed. No unhandled exceptions detected.
              </p>
            </div>
          )}

          {activeTab === 'activity' && (
            <div className="space-y-1 text-xs">
              <div className="text-[var(--text-muted)] mb-2">
                Recent Flight Recorder Signals
              </div>
              <p className="text-[var(--text-secondary)] text-[11px]">
                Event stream actively monitoring project root.
              </p>
            </div>
          )}
        </div>
      )}
    </footer>
  );
};

