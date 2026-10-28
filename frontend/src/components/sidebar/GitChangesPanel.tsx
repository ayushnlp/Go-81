'use client';

import React from 'react';
import { GitBranch, GitCommit, GitPullRequest, Info, CheckCircle2, ArrowRight } from 'lucide-react';

interface GitChangesPanelProps {
  onReviewChangesPrompt?: () => void;
}

export const GitChangesPanel: React.FC<GitChangesPanelProps> = ({ onReviewChangesPrompt }) => {
  return (
    <div className="flex flex-col h-full select-none">
      {/* Header */}
      <div className="px-3.5 py-3 border-b border-[var(--border-subtle)]">
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Source Control
        </span>
        <div className="flex items-center space-x-1.5 mt-1">
          <GitBranch className="w-3.5 h-3.5 text-[#ea580c]" />
          <span className="font-mono text-xs font-semibold text-[var(--text-primary)]">
            ui/go81-command-center
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Branch Info Card */}
        <div className="p-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--text-secondary)] font-medium">Active Branch</span>
            <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)]">
              ui/go81-command-center
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--text-secondary)] font-medium">Base Hardening Commit</span>
            <span className="font-mono text-[11px] text-[var(--text-muted)]">251ddf5</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--text-secondary)] font-medium">Remote Origin</span>
            <span className="font-mono text-[11px] text-[var(--text-muted)] truncate max-w-[140px]" title="https://github.com/ayushnlp/Go-81.git">
              Go-81.git
            </span>
          </div>
        </div>

        {/* Missing API Disclosure Notice */}
        <div className="p-3 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] space-y-1.5 text-xs">
          <div className="flex items-center space-x-1.5 text-[var(--accent-primary)] font-medium">
            <Info className="w-4 h-4 shrink-0" />
            <span>Git REST Boundary Note</span>
          </div>
          <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
            Go 81 backend does not expose an unrestricted raw git-diff HTTP route to maintain sovereign sandbox security. Changes are inspected via verified checkpoints and approved skills.
          </p>
        </div>

        {/* Action Button: Trigger Review */}
        {onReviewChangesPrompt && (
          <button
            type="button"
            onClick={onReviewChangesPrompt}
            className="w-full flex items-center justify-between p-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] hover:border-[var(--accent-primary-border)] transition-all cursor-pointer group text-xs font-medium text-[var(--text-primary)]"
          >
            <div className="flex items-center space-x-2">
              <GitCommit className="w-4 h-4 text-[#ea580c]" />
              <span>Review Recent Changes in Chat</span>
            </div>
            <ArrowRight className="w-3.5 h-3.5 text-[var(--text-muted)] group-hover:text-[var(--accent-primary)] transition-transform group-hover:translate-x-0.5" />
          </button>
        )}
      </div>
    </div>
  );
};

