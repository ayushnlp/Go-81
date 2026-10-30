'use client';

import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { NavDestination } from '../shell/NavRail';
import { RecentWorkPanel } from './RecentWorkPanel';
import { ExplorerPanel } from './ExplorerPanel';
import { ActivityHistoryPanel } from './ActivityHistoryPanel';
import { GitChangesPanel } from './GitChangesPanel';
import { ProblemsPanel } from './ProblemsPanel';
import { EnvironmentPanel } from './EnvironmentPanel';
import { TaskGraph, AgentRuntimeStatus, ModelHealth, FileEntry } from '@/lib/api/types';

interface ContextualSidebarProps {
  activeNav: NavDestination;
  isOpen: boolean;
  onToggle: () => void;
  tasks: TaskGraph[];
  activeTaskId: string | null;
  onSelectTask: (task: TaskGraph) => void;
  onNewRequest: () => void;
  isLoadingTasks: boolean;
  runtimeStatus: AgentRuntimeStatus | null;
  modelHealth: ModelHealth | null;
  isBackendOnline: boolean;
  onRefreshEnvironment?: () => void;
  onSelectFile?: (file: FileEntry) => void;
  onReviewChangesPrompt?: () => void;
}

export const ContextualSidebar: React.FC<ContextualSidebarProps> = ({
  activeNav,
  isOpen,
  onToggle,
  tasks,
  activeTaskId,
  onSelectTask,
  onNewRequest,
  isLoadingTasks,
  runtimeStatus,
  modelHealth,
  isBackendOnline,
  onRefreshEnvironment,
  onSelectFile,
  onReviewChangesPrompt,
}) => {
  if (!isOpen) {
    return null;
  }

  return (
    <aside
      aria-label="Contextual Sidebar"
      className="w-72 sm:w-80 border-r border-[var(--border-subtle)] bg-[var(--bg-surface)] flex flex-col h-full relative shrink-0 transition-all duration-150"
    >
      {/* Collapse Toggle Button */}
      <button
        type="button"
        onClick={onToggle}
        title="Collapse sidebar"
        className="absolute -right-3 top-3 w-6 h-6 rounded-full bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] border border-[var(--border-subtle)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] shadow-xs transition-colors cursor-pointer z-20"
      >
        <ChevronLeft className="w-3.5 h-3.5" />
      </button>

      {/* Dynamic Panel Content Based on Selected Tab */}
      <div className="flex-1 overflow-hidden">
        {activeNav === 'home' && (
          <RecentWorkPanel
            tasks={tasks}
            activeTaskId={activeTaskId}
            onSelectTask={onSelectTask}
            onNewRequest={onNewRequest}
            isLoading={isLoadingTasks}
          />
        )}

        {activeNav === 'explorer' && (
          <ExplorerPanel onSelectFile={onSelectFile} />
        )}

        {activeNav === 'search' && (
          <div className="p-4 text-xs text-[var(--text-secondary)] select-none">
            <span className="font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-2">
              Global Search
            </span>
            <p className="text-[11px] text-[var(--text-muted)] mb-3">
              Press <kbd className="px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)] font-mono text-[10px]">Ctrl+K</kbd> to launch the command palette across all files, memories, and actions.
            </p>
          </div>
        )}

        {activeNav === 'git' && (
          <GitChangesPanel onReviewChangesPrompt={onReviewChangesPrompt} />
        )}

        {activeNav === 'activity' && (
          <ActivityHistoryPanel />
        )}

        {activeNav === 'problems' && (
          <ProblemsPanel />
        )}

        {activeNav === 'environment' && (
          <EnvironmentPanel
            runtimeStatus={runtimeStatus}
            modelHealth={modelHealth}
            isBackendOnline={isBackendOnline}
            onRefresh={onRefreshEnvironment}
          />
        )}

        {(activeNav === 'memory' || activeNav === 'skills' || activeNav === 'settings') && (
          <div className="p-4 space-y-3 select-none text-xs">
            <span className="font-semibold uppercase tracking-wider text-[var(--text-muted)] block">
              {activeNav === 'memory'
                ? 'Encrypted Memory Vault'
                : activeNav === 'skills'
                ? 'Skills Forge'
                : 'Settings & Privacy'}
            </span>
            <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
              {activeNav === 'memory'
                ? 'Semantic and episodic facts stored locally with zero external sync.'
                : activeNav === 'skills'
                ? 'Verified capability sandbox with strict default-deny enforcement.'
                : 'Local-first configuration and sovereign model boundaries.'}
            </p>
            <a
              href={`/${activeNav}`}
              className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-md bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)] text-[var(--text-primary)] border border-[var(--border-subtle)] font-medium transition-colors"
            >
              <span>Open Full {activeNav === 'memory' ? 'Vault' : activeNav === 'skills' ? 'Forge' : 'Settings'} View →</span>
            </a>
          </div>
        )}
      </div>
    </aside>
  );
};

