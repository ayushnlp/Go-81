'use client';

import React from 'react';
import { Plus, Clock, CheckCircle2, AlertCircle, PlayCircle, Loader2 } from 'lucide-react';
import { TaskGraph } from '@/lib/api/types';

interface RecentWorkPanelProps {
  tasks: TaskGraph[];
  activeTaskId: string | null;
  onSelectTask: (task: TaskGraph) => void;
  onNewRequest: () => void;
  isLoading: boolean;
}

export const RecentWorkPanel: React.FC<RecentWorkPanelProps> = ({
  tasks,
  activeTaskId,
  onSelectTask,
  onNewRequest,
  isLoading,
}) => {
  return (
    <div className="flex flex-col h-full select-none">
      {/* Header with Title and New Request Button */}
      <div className="px-3.5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Recent Work
          </span>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
            Active and historical agent runs
          </p>
        </div>
        <button
          type="button"
          onClick={onNewRequest}
          title="Start a new request"
          className="inline-flex items-center space-x-1 px-2.5 py-1 rounded bg-[#ea580c] hover:bg-[#c2410c] text-white text-xs font-medium shadow-xs transition-colors cursor-pointer"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>New</span>
        </button>
      </div>

      {/* Task List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {isLoading ? (
          <div className="py-8 text-center text-xs text-[var(--text-muted)] flex flex-col items-center justify-center space-y-2">
            <Loader2 className="w-4 h-4 animate-spin text-[var(--accent-primary)]" />
            <span>Loading recent tasks...</span>
          </div>
        ) : tasks.length === 0 ? (
          <div className="py-12 px-3 text-center">
            <Clock className="w-8 h-8 text-[var(--text-muted)] mx-auto mb-2 opacity-50" />
            <p className="text-xs font-medium text-[var(--text-primary)]">
              Ready for your instruction
            </p>
            <p className="text-[11px] text-[var(--text-muted)] mt-1">
              Submit a prompt in the central composer to create your first autonomous workflow.
            </p>
          </div>
        ) : (
          tasks.map((task) => {
            const isSelected = activeTaskId === task.id;
            const completedSteps = task.steps.filter((s) => s.status === 'completed').length;
            const totalSteps = task.steps.length;

            return (
              <button
                key={task.id}
                type="button"
                onClick={() => onSelectTask(task)}
                className={`w-full text-left p-2.5 rounded-lg border transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-[var(--accent-primary-bg)] border-[var(--accent-primary-border)] shadow-xs'
                    : 'bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] border-[var(--border-subtle)]'
                }`}
              >
                <div className="flex items-start justify-between space-x-2">
                  <span className="text-xs font-medium text-[var(--text-primary)] line-clamp-2">
                    {task.goal}
                  </span>
                  {task.status === 'completed' && (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" />
                  )}
                  {task.status === 'running' && (
                    <PlayCircle className="w-3.5 h-3.5 text-orange-500 shrink-0 mt-0.5 animate-pulse" />
                  )}
                  {task.status === 'failed' && (
                    <AlertCircle className="w-3.5 h-3.5 text-rose-500 shrink-0 mt-0.5" />
                  )}
                  {task.status === 'awaiting_approval' && (
                    <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0 mt-1" />
                  )}
                </div>

                <div className="flex items-center justify-between mt-2 text-[10px] text-[var(--text-muted)] font-mono">
                  <span>
                    {totalSteps > 0 ? `${completedSteps}/${totalSteps} steps` : task.status}
                  </span>
                  <span>
                    {new Date(task.createdAt).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
};

