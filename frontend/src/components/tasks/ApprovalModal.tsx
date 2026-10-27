'use client';

import React, { useState } from 'react';
import { AlertOctagon, Check, X, ShieldAlert, Terminal } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { Badge, BadgeVariant } from '../ui/Badge';
import { Button } from '../ui/Button';
import { ApprovalRequest, RiskLevel } from '../../lib/api/types';

interface ApprovalModalProps {
  request: ApprovalRequest | null;
  isOpen: boolean;
  onClose: () => void;
  onResolve: (requestId: string, decision: 'approved' | 'rejected', notes?: string) => Promise<void>;
}

const riskVariant: Record<RiskLevel, BadgeVariant> = {
  low: 'sky',
  medium: 'amber',
  high: 'rose',
  critical: 'rose',
};

export const ApprovalModal: React.FC<ApprovalModalProps> = ({
  request,
  isOpen,
  onClose,
  onResolve,
}) => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [rejectionNotes, setRejectionNotes] = useState('');
  const [showRejectionInput, setShowRejectionInput] = useState(false);

  if (!request) return null;

  const handleAction = async (decision: 'approved' | 'rejected') => {
    setIsSubmitting(true);
    try {
      await onResolve(request.id, decision, rejectionNotes || undefined);
      setShowRejectionInput(false);
      setRejectionNotes('');
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Gjallarhorn Approval Gate"
      description="Sensitive operation requires just-in-time user authorization (FR4.3)"
      maxWidth="xl"
    >
      <div className="space-y-4">
        {/* Risk Banner */}
        <div className="p-3.5 rounded-lg bg-zinc-900 border border-zinc-800 flex items-start gap-3">
          <div className="p-2 rounded-md bg-amber-950/60 text-amber-400 border border-amber-800/40 shrink-0">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                Tool: <code className="text-zinc-200 font-semibold">{request.toolName}</code>
              </span>
              <Badge variant={riskVariant[request.riskLevel]} dot>
                {request.riskLevel.toUpperCase()} RISK
              </Badge>
            </div>
            <p className="mt-1 text-sm font-medium text-zinc-100">{request.actionTitle}</p>
            <p className="mt-0.5 text-xs text-zinc-400">{request.rationale}</p>
          </div>
        </div>

        {/* Task Context */}
        <div className="text-xs text-zinc-400 bg-zinc-950/50 p-2.5 rounded-md border border-zinc-850">
          <span className="font-medium text-zinc-300">Originating Task Goal:</span> {request.taskGoal}
        </div>

        {/* Command or Payload Inspection */}
        <div>
          <label className="text-xs font-medium text-zinc-300 flex items-center gap-1.5 mb-1.5">
            <Terminal className="w-3.5 h-3.5 text-zinc-400" />
            Inspected Command / Payload
          </label>
          <div className="relative rounded-lg bg-[#090b0e] border border-zinc-800 p-3 overflow-x-auto">
            <pre className="font-mono text-xs text-emerald-300 leading-relaxed whitespace-pre-wrap break-all">
              {request.commandOrPayload}
            </pre>
          </div>
        </div>

        {/* Rejection input toggle */}
        {showRejectionInput && (
          <div className="space-y-1.5 animate-in fade-in duration-150">
            <label className="text-xs text-zinc-300">
              Rejection Directive for Agent Reflection (FR3.3 Self-Correction):
            </label>
            <textarea
              value={rejectionNotes}
              onChange={(e) => setRejectionNotes(e.target.value)}
              placeholder="e.g. Do not touch production files. Use test/ directory instead."
              rows={2}
              className="w-full text-xs rounded-lg bg-zinc-900 border border-zinc-700/80 p-2 text-zinc-200 placeholder-zinc-500 focus:border-rose-500 focus:ring-1 focus:ring-rose-500"
            />
          </div>
        )}

        {/* Actions */}
        <div className="pt-2 border-t border-zinc-800 flex items-center justify-between gap-3">
          {!showRejectionInput ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setShowRejectionInput(true)}
              className="text-xs text-rose-300 hover:text-rose-200 border-rose-900/40 hover:bg-rose-950/30"
              icon={<AlertOctagon className="w-3.5 h-3.5 text-rose-400" />}
            >
              Reject Action...
            </Button>
          ) : (
            <Button
              type="button"
              variant="danger"
              size="sm"
              onClick={() => handleAction('rejected')}
              loading={isSubmitting}
              icon={<X className="w-3.5 h-3.5" />}
            >
              Confirm Rejection
            </Button>
          )}

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => handleAction('approved')}
              loading={isSubmitting}
              icon={<Check className="w-4 h-4" />}
            >
              Authorize &amp; Execute
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
};
