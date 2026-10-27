'use client';

import React, { useState, useEffect } from 'react';
import {
  Activity,
  Plus,
  ShieldAlert,
  Filter,
  Sparkles,
} from 'lucide-react';
import { AppSidebar } from '@/components/shell/AppSidebar';
import { AppHeader } from '@/components/shell/AppHeader';
import { OfflineBanner } from '@/components/ui/OfflineBanner';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { TaskTimelineCard } from '@/components/tasks/TaskTimelineCard';
import { ApprovalModal } from '@/components/tasks/ApprovalModal';
import { api } from '@/lib/api/client';
import { TaskGraph, TaskStatus, ApprovalRequest } from '@/lib/api/types';
import { DEMO_APPROVALS } from '@/lib/api/fixtures';

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskGraph[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>(DEMO_APPROVALS);
  const [activeApproval, setActiveApproval] = useState<ApprovalRequest | null>(null);

  const [statusFilter, setStatusFilter] = useState<'all' | TaskStatus>('all');
  const [isNewTaskModalOpen, setIsNewTaskModalOpen] = useState(false);
  const [newGoal, setNewGoal] = useState('');
  const [newPriority, setNewPriority] = useState<'low' | 'normal' | 'high'>('normal');

  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [isCheckingBackend, setIsCheckingBackend] = useState(false);

  const probe = async () => {
    setIsCheckingBackend(true);
    try {
      const health = await api.checkHealth();
      setIsBackendOnline(health.online);

      const tasksRes = await api.getTasks();
      setTasks(tasksRes.data);

      const apprRes = await api.getApprovals();
      setApprovals(apprRes.data);
    } finally {
      setIsCheckingBackend(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    (async () => {
      try {
        const health = await api.checkHealth();
        if (!isMounted) return;
        setIsBackendOnline(health.online);

        const tasksRes = await api.getTasks();
        if (!isMounted) return;
        setTasks(tasksRes.data);

        const apprRes = await api.getApprovals();
        if (!isMounted) return;
        setApprovals(apprRes.data);
      } catch {
        // graceful offline
      }
    })();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleOpenApproval = (requestId: string) => {
    const found = approvals.find((a) => a.id === requestId);
    if (found) {
      setActiveApproval(found);
    }
  };

  const handleResolveApproval = async (
    requestId: string,
    decision: 'approved' | 'rejected',
    notes?: string
  ) => {
    await api.resolveApproval(requestId, decision, notes);

    // Update local approvals state
    setApprovals((prev) =>
      prev.map((a) => (a.id === requestId ? { ...a, status: decision } : a))
    );

    // Update task step status
    setTasks((prev) =>
      prev.map((t) => ({
        ...t,
        status: decision === 'approved' ? 'running' : 'failed',
        steps: t.steps.map((s) => {
          if (s.approvalRequestId === requestId) {
            return {
              ...s,
              status: decision === 'approved' ? 'completed' : 'failed',
              output:
                decision === 'approved'
                  ? 'Authorized by Engineer 3. Subprocess executed cleanly in sandbox.'
                  : `Rejected by user: ${notes || 'Action halted by gatekeeper.'}`,
            };
          }
          return s;
        }),
      }))
    );
  };

  const handleCreateTask = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newGoal.trim()) return;

    const newTask: TaskGraph = {
      id: `task-${Date.now().toString().slice(-6)}`,
      goal: newGoal.trim(),
      status: 'running',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      priority: newPriority,
      estimatedDurationMs: 30000,
      steps: [
        {
          id: `step-${Date.now()}-1`,
          stepNumber: 1,
          title: 'Decompose Ambiguous Goal into Sub-Tasks (FR3.1 Planning)',
          skillName: 'workflow.planner',
          status: 'completed',
          parameters: { goal: newGoal },
          output: 'Decomposed voyage into 3 sequential safe sub-actions.',
          reflectionAttempt: 0,
        },
        {
          id: `step-${Date.now()}-2`,
          stepNumber: 2,
          title: 'Execute Local Domain Tool Behind Sandboxed Shield-Wall',
          skillName: 'system.sandboxed_exec',
          status: 'running',
          parameters: { isolationLevel: 'CONTAINER_SHIELD' },
          reflectionAttempt: 0,
        },
        {
          id: `step-${Date.now()}-3`,
          stepNumber: 3,
          title: 'Verify Results & Inscribe Record into Memory Storage',
          skillName: 'memory.record_saga',
          status: 'pending',
          parameters: { autoConsolidate: true },
          reflectionAttempt: 0,
        },
      ],
    };

    setTasks((prev) => [newTask, ...prev]);
    setNewGoal('');
    setIsNewTaskModalOpen(false);
  };

  const filteredTasks =
    statusFilter === 'all'
      ? tasks
      : tasks.filter((t) => t.status === statusFilter);

  const pendingApprovalsCount = approvals.filter((a) => a.status === 'pending').length;

  return (
    <div className="flex min-h-screen bg-[#FAF9F5] text-zinc-900">
      <AppSidebar pendingApprovalsCount={pendingApprovalsCount} />

      <div className="flex-1 flex flex-col min-w-0">
        <OfflineBanner
          isLive={isBackendOnline}
          isChecking={isCheckingBackend}
          onRetry={probe}
          backendUrl={api.getBaseUrl()}
        />

        <AppHeader
          title="Task Execution Timeline"
          subtitle="Autonomous multi-step execution graphs with approval gates (FR3)"
          isBackendOnline={isBackendOnline}
          isChecking={isCheckingBackend}
          onRefreshBackend={probe}
        />

        <main className="flex-1 max-w-5xl w-full mx-auto p-4 sm:p-6 space-y-6">
          {/* Top Control Bar */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            {/* Filter Tabs */}
            <div className="flex items-center gap-1 bg-white p-1 rounded-lg border border-[#E5E3DC] shadow-2xs text-xs font-mono">
              <span className="text-zinc-500 px-2 flex items-center gap-1">
                <Filter className="w-3 h-3" /> State:
              </span>
              {(['all', 'running', 'awaiting_approval', 'completed', 'failed'] as const).map(
                (filter) => (
                  <button
                    key={filter}
                    onClick={() => setStatusFilter(filter)}
                    className={`px-2.5 py-1 rounded cursor-pointer capitalize ${
                      statusFilter === filter
                        ? 'bg-zinc-950 text-white font-semibold'
                        : 'text-zinc-600 hover:text-zinc-900'
                    }`}
                  >
                    {filter === 'awaiting_approval'
                      ? 'Gate Approval'
                      : filter}
                  </button>
                )
              )}
            </div>

            {/* New Task Trigger Button */}
            <Button
              variant="primary"
              size="sm"
              onClick={() => setIsNewTaskModalOpen(true)}
              icon={<Plus className="w-4 h-4" />}
            >
              Dispatch New Task
            </Button>
          </div>

          {/* Pending Approval Gates Alert Banner */}
          {pendingApprovalsCount > 0 && (
            <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-amber-100 text-amber-800 border border-amber-300">
                  <ShieldAlert className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-semibold text-amber-950 text-sm">
                    {pendingApprovalsCount} Action Requires Gatekeeper Approval (FR4.3)
                  </h3>
                  <p className="text-amber-800 mt-0.5">
                    A task step attempted to perform a sensitive operation (file writes or shell execution).
                  </p>
                </div>
              </div>

              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const pendingReq = approvals.find((a) => a.status === 'pending');
                  if (pendingReq) setActiveApproval(pendingReq);
                }}
                className="border-amber-300 text-amber-900 hover:bg-amber-100 font-mono text-xs"
              >
                Inspect &amp; Authorize
              </Button>
            </div>
          )}

          {/* Task Timeline List */}
          <div className="space-y-4">
            {filteredTasks.length === 0 ? (
              <div className="p-12 text-center rounded-xl bg-white border border-[#E5E3DC] text-zinc-500 space-y-2">
                <Activity className="w-8 h-8 mx-auto text-zinc-400" />
                <p className="text-sm">No tasks found matching current filter.</p>
              </div>
            ) : (
              filteredTasks.map((task) => (
                <TaskTimelineCard
                  key={task.id}
                  task={task}
                  onOpenApproval={handleOpenApproval}
                />
              ))
            )}
          </div>
        </main>
      </div>

      {/* Dispatch New Task Modal */}
      <Modal
        isOpen={isNewTaskModalOpen}
        onClose={() => setIsNewTaskModalOpen(false)}
        title="Dispatch Autonomous Task"
        description="Go 81 will decompose the goal into an execution graph across registered skills (FR3.1)"
      >
        <form onSubmit={handleCreateTask} className="space-y-4">
          <div>
            <label className="text-xs font-semibold text-zinc-700 block mb-1">
              High-Level Goal / Ambiguous User Objective:
            </label>
            <textarea
              value={newGoal}
              onChange={(e) => setNewGoal(e.target.value)}
              placeholder="e.g. Audit repository, run type checks, and prepare PR submission diff..."
              rows={3}
              required
              className="w-full text-xs rounded-lg bg-white border border-zinc-300 p-2.5 text-zinc-900 placeholder-zinc-400 focus:border-zinc-900 focus:ring-1 focus:ring-zinc-900"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-zinc-700 block mb-1">
              Execution Priority:
            </label>
            <div className="flex gap-2">
              {(['low', 'normal', 'high'] as const).map((pri) => (
                <button
                  key={pri}
                  type="button"
                  onClick={() => setNewPriority(pri)}
                  className={`flex-1 py-1.5 px-3 rounded-lg text-xs font-mono capitalize border cursor-pointer ${
                    newPriority === pri
                      ? 'bg-zinc-950 border-zinc-950 text-white font-semibold'
                      : 'bg-white border-zinc-300 text-zinc-700 hover:bg-zinc-100'
                  }`}
                >
                  {pri}
                </button>
              ))}
            </div>
          </div>

          <div className="pt-2 border-t border-zinc-200 flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setIsNewTaskModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              icon={<Sparkles className="w-3.5 h-3.5" />}
            >
              Start Autonomous Plan
            </Button>
          </div>
        </form>
      </Modal>

      {/* Interactive Approval Modal */}
      <ApprovalModal
        request={activeApproval}
        isOpen={Boolean(activeApproval)}
        onClose={() => setActiveApproval(null)}
        onResolve={handleResolveApproval}
      />
    </div>
  );
}
