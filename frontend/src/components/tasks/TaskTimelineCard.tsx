'use client';

import React, { useState } from 'react';
import {
  CheckCircle2,
  Clock,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  Repeat,
  Terminal,
} from 'lucide-react';
import { Card, CardHeader, CardContent, CardTitle } from '../ui/Card';
import { Badge, BadgeVariant } from '../ui/Badge';
import { Button } from '../ui/Button';
import { TaskGraph, TaskStep, TaskStatus, StepStatus } from '../../lib/api/types';

interface TaskTimelineCardProps {
  task: TaskGraph;
  onOpenApproval?: (requestId: string) => void;
}

const statusBadgeConfig: Record<
  TaskStatus,
  { variant: BadgeVariant; label: string; dot?: boolean }
> = {
  queued: { variant: 'zinc', label: 'Queued' },
  running: { variant: 'sky', label: 'Executing', dot: true },
  awaiting_approval: { variant: 'amber', label: 'Awaiting Gate Approval', dot: true },
  completed: { variant: 'emerald', label: 'Completed' },
  failed: { variant: 'rose', label: 'Failed' },
};

const stepStatusIcon: Record<StepStatus, React.ReactNode> = {
  pending: <Clock className="w-4 h-4 text-zinc-500" />,
  running: <Loader2 className="w-4 h-4 text-sky-400 animate-spin" />,
  awaiting_approval: <ShieldAlert className="w-4 h-4 text-amber-400 animate-pulse" />,
  completed: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
  failed: <XCircle className="w-4 h-4 text-rose-400" />,
};

export const TaskTimelineCard: React.FC<TaskTimelineCardProps> = ({
  task,
  onOpenApproval,
}) => {
  const [expandedStepId, setExpandedStepId] = useState<string | null>(null);
  const badgeConfig = statusBadgeConfig[task.status];

  const toggleStep = (stepId: string) => {
    setExpandedStepId((curr) => (curr === stepId ? null : stepId));
  };

  return (
    <Card className="overflow-hidden transition-all duration-200">
      <CardHeader className="bg-[#121620]/60 flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1 max-w-xl">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-zinc-400">
              ID: {task.id}
            </span>
            <Badge variant={badgeConfig.variant} dot={badgeConfig.dot}>
              {badgeConfig.label}
            </Badge>
            <span className="text-[11px] font-mono text-zinc-500">
              Priority: {task.priority.toUpperCase()}
            </span>
          </div>
          <CardTitle className="text-base text-zinc-100">{task.goal}</CardTitle>
        </div>

        <div className="text-right text-xs text-zinc-500 font-mono">
          <div>Created: {new Date(task.createdAt).toLocaleTimeString()}</div>
          {task.estimatedDurationMs && (
            <div>Est: {(task.estimatedDurationMs / 1000).toFixed(0)}s</div>
          )}
        </div>
      </CardHeader>

      <CardContent className="pt-4">
        {/* Step Timeline */}
        <div className="relative pl-6 space-y-6 before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-[2px] before:bg-zinc-800">
          {task.steps.map((step: TaskStep) => {
            const isExpanded = expandedStepId === step.id;
            const isAwaitingGate = step.status === 'awaiting_approval';

            return (
              <div key={step.id} className="relative group">
                {/* Step Node Marker */}
                <div className="absolute -left-6 top-0.5 w-6 h-6 rounded-full bg-[#101319] border border-zinc-750 flex items-center justify-center shrink-0">
                  {stepStatusIcon[step.status]}
                </div>

                <div className="bg-[#0e1117] border border-zinc-800/80 rounded-lg p-3.5 hover:border-zinc-700 transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div
                      className="cursor-pointer flex-1"
                      onClick={() => toggleStep(step.id)}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-zinc-400">
                          Step {step.stepNumber}:
                        </span>
                        <h4 className="text-sm font-medium text-zinc-200">
                          {step.title}
                        </h4>
                        {isExpanded ? (
                          <ChevronDown className="w-3.5 h-3.5 text-zinc-500" />
                        ) : (
                          <ChevronRight className="w-3.5 h-3.5 text-zinc-500" />
                        )}
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-400">
                        <span className="font-mono text-emerald-400/90 text-[11px] flex items-center gap-1">
                          <Terminal className="w-3 h-3 text-zinc-500" />
                          {step.skillName}
                        </span>

                        {step.reflectionAttempt > 0 && (
                          <span className="inline-flex items-center gap-1 text-[11px] font-mono text-amber-400 bg-amber-950/40 border border-amber-800/40 px-1.5 py-0.2 rounded">
                            <Repeat className="w-2.5 h-2.5" />
                            FR3.3 Reflection #{step.reflectionAttempt}
                          </span>
                        )}
                      </div>
                    </div>

                    {isAwaitingGate && step.approvalRequestId && onOpenApproval && (
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => onOpenApproval(step.approvalRequestId!)}
                        icon={<ShieldAlert className="w-3.5 h-3.5 text-white" />}
                        className="bg-amber-600 hover:bg-amber-500 text-black font-semibold border-amber-400/50 shrink-0"
                      >
                        Review Gate
                      </Button>
                    )}
                  </div>

                  {/* Output summary snippet */}
                  {step.output && !isExpanded && (
                    <p className="mt-2 text-xs text-zinc-400 line-clamp-1 font-mono bg-zinc-950/40 px-2 py-1 rounded border border-zinc-850">
                      {step.output}
                    </p>
                  )}

                  {/* Detailed Parameter & Output Drawer */}
                  {isExpanded && (
                    <div className="mt-3 pt-3 border-t border-zinc-800/80 space-y-2 text-xs font-mono">
                      {step.parameters && (
                        <div>
                          <span className="text-zinc-500 text-[11px] uppercase tracking-wider block mb-1">
                            Parameters
                          </span>
                          <pre className="bg-zinc-950 p-2.5 rounded border border-zinc-850 text-zinc-300 overflow-x-auto">
                            {JSON.stringify(step.parameters, null, 2)}
                          </pre>
                        </div>
                      )}

                      {step.output && (
                        <div>
                          <span className="text-zinc-500 text-[11px] uppercase tracking-wider block mb-1">
                            Output
                          </span>
                          <pre className="bg-zinc-950 p-2.5 rounded border border-zinc-850 text-emerald-300 overflow-x-auto whitespace-pre-wrap">
                            {step.output}
                          </pre>
                        </div>
                      )}

                      {step.error && (
                        <div className="p-2 rounded bg-rose-950/40 border border-rose-800/40 text-rose-300">
                          <span className="text-rose-400 font-semibold block mb-0.5">
                            Error Trapped (Autonomous Self-Correction Triggered):
                          </span>
                          <p>{step.error}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
};
