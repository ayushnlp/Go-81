'use client';

import React, { useState } from 'react';
import { GitBranch, GitCommit, Info, CheckCircle2, RefreshCw, FileText, ArrowRight, ShieldCheck } from 'lucide-react';

interface GitChangesWorkspaceProps {
  onReviewChangesPrompt?: () => void;
}

export const GitChangesWorkspace: React.FC<GitChangesWorkspaceProps> = ({ onReviewChangesPrompt }) => {
  const [isRefreshing, setIsRefreshing] = useState(false);

  const commits = [
    {
      hash: '47f1594',
      message: 'feat(agent): implement validated autonomous task orchestration',
      author: 'ayushnlp',
      date: 'Today, 17:37',
      isHead: true,
    },
    {
      hash: '92e5400',
      message: 'feat(ui): build Go 81 command center with integrated panels',
      author: 'ayushnlp',
      date: 'Approved UI Checkpoint',
      isHead: false,
    },
    {
      hash: '251ddf5',
      message: 'feat(security): complete Stage 3 security hardening and regression tests',
      author: 'ayushnlp',
      date: 'Stage 3 Hardening Baseline',
      isHead: false,
    },
    {
      hash: 'f5b7fae',
      message: 'feat(security): add skill registry, permission gateway, execution sandbox, and audit logging',
      author: 'ayushnlp',
      date: 'Stage 3 Foundation',
      isHead: false,
    },
    {
      hash: 'a89e329',
      message: 'feat(go81): initialize sovereign agent runtime with verified Stage 1 and Stage 2 memory',
      author: 'ayushnlp',
      date: 'Root Anchor',
      isHead: false,
    },
  ];

  const handleRefresh = () => {
    setIsRefreshing(true);
    setTimeout(() => setIsRefreshing(false), 500);
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto p-6 md:p-8 bg-[var(--bg-canvas)]">
      <div className="max-w-4xl w-full mx-auto space-y-6">
        {/* Status Card */}
        <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 rounded-xl bg-[var(--bg-elevated)] text-[#ea580c] flex items-center justify-center shrink-0">
                <GitBranch className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  Active Branch: <span className="font-mono text-[#ea580c]">stage4/autonomous-orchestration</span>
                </h3>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">
                  Remote: <span className="font-mono text-[var(--text-secondary)]">https://github.com/ayushnlp/Go-81.git</span>
                </p>
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-xs font-medium">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>Up to date with origin</span>
              </div>
              <button
                type="button"
                onClick={handleRefresh}
                title="Refresh git state"
                className="p-1.5 rounded-md hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] transition-colors cursor-pointer"
              >
                <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs">
            <div className="p-3 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)]">
              <span className="text-[var(--text-muted)] block">Published Head</span>
              <span className="font-mono text-[var(--text-primary)] font-semibold mt-1 block">47f1594</span>
            </div>
            <div className="p-3 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)]">
              <span className="text-[var(--text-muted)] block">Approved UI Base</span>
              <span className="font-mono text-[var(--text-primary)] font-semibold mt-1 block">92e5400</span>
            </div>
            <div className="p-3 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)]">
              <span className="text-[var(--text-muted)] block">Security Baseline</span>
              <span className="font-mono text-[var(--text-primary)] font-semibold mt-1 block">251ddf5</span>
            </div>
          </div>
        </div>

        {/* Security Sandbox Boundary Notice */}
        <div className="p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] shadow-2xs space-y-2">
          <div className="flex items-center space-x-2 text-[#ea580c] font-semibold text-xs">
            <ShieldCheck className="w-4 h-4 shrink-0" />
            <span>Sovereign Sandbox Boundary</span>
          </div>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
            Go 81 enforces strict default-deny git boundaries. Direct raw git push, remote fetch, and merge operations are restricted to verified operator actions to protect repository integrity.
          </p>
          {onReviewChangesPrompt && (
            <div className="pt-2">
              <button
                type="button"
                onClick={onReviewChangesPrompt}
                className="inline-flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-[#ea580c] hover:bg-[#c2410c] text-white text-xs font-semibold shadow-xs transition-colors cursor-pointer"
              >
                <span>Summarize Git Changes via Chat</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* Recent Project Commits Log */}
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] px-1">
            Verified Project Commits History
          </h4>

          <div className="space-y-2">
            {commits.map((c) => (
              <div
                key={c.hash}
                className="p-3.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-2xs flex items-start justify-between"
              >
                <div className="flex items-start space-x-3">
                  <div className="p-1.5 rounded-md bg-[var(--bg-elevated)] text-[var(--text-muted)] shrink-0 mt-0.5">
                    <GitCommit className="w-4 h-4" />
                  </div>
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="font-mono text-xs font-bold text-[var(--text-primary)]">
                        {c.hash}
                      </span>
                      {c.isHead && (
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-[#ea580c] text-white">
                          HEAD
                        </span>
                      )}
                      <span className="text-[11px] text-[var(--text-muted)] font-mono">
                        by {c.author} • {c.date}
                      </span>
                    </div>
                    <p className="text-xs text-[var(--text-secondary)] mt-1 font-medium">
                      {c.message}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

