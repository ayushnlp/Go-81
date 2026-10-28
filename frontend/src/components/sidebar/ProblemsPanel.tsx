'use client';

import React, { useState, useEffect } from 'react';
import { ShieldAlert, AlertCircle, CheckCircle2, RefreshCw, Lock } from 'lucide-react';
import { api } from '@/lib/api/client';
import { AuditRecord } from '@/lib/api/types';

export const ProblemsPanel: React.FC = () => {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [filter, setFilter] = useState<'all' | 'denied' | 'allowed'>('all');

  const fetchAudit = async () => {
    setIsLoading(true);
    try {
      const res = await api.getAuditRecords();
      setRecords(res.data || []);
    } catch {
      // offline fallback
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAudit();
  }, []);

  const deniedCount = records.filter((r) => r.status === 'denied' || r.status === 'rejected').length;

  const filtered = records.filter((r) => {
    if (filter === 'denied') return r.status === 'denied' || r.status === 'rejected';
    if (filter === 'allowed') return r.status === 'allowed' || r.status === 'approved';
    return true;
  });

  return (
    <div className="flex flex-col h-full select-none">
      {/* Header */}
      <div className="px-3.5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Diagnostics & Problems
          </span>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
            Permission Gateway audit logs & violations
          </p>
        </div>
        <button
          type="button"
          onClick={fetchAudit}
          disabled={isLoading}
          title="Refresh audit records"
          className="p-1 rounded hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors cursor-pointer"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Filter Chips */}
      <div className="px-3 py-2 border-b border-[var(--border-subtle)] flex items-center space-x-1.5">
        <button
          type="button"
          onClick={() => setFilter('all')}
          className={`px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer ${
            filter === 'all'
              ? 'bg-[var(--bg-elevated)] text-[var(--text-primary)] border border-[var(--border-subtle)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
          }`}
        >
          All ({records.length})
        </button>
        <button
          type="button"
          onClick={() => setFilter('denied')}
          className={`px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer ${
            filter === 'denied'
              ? 'bg-rose-500/10 text-rose-500 border border-rose-500/20'
              : 'text-[var(--text-muted)] hover:text-rose-400'
          }`}
        >
          Violations ({deniedCount})
        </button>
        <button
          type="button"
          onClick={() => setFilter('allowed')}
          className={`px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer ${
            filter === 'allowed'
              ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
              : 'text-[var(--text-muted)] hover:text-emerald-400'
          }`}
        >
          Allowed ({records.length - deniedCount})
        </button>
      </div>

      {/* Audit List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {isLoading ? (
          <div className="py-8 text-center text-xs text-[var(--text-muted)] flex flex-col items-center justify-center space-y-2">
            <RefreshCw className="w-4 h-4 animate-spin text-[var(--accent-primary)]" />
            <span>Loading security audits...</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-12 px-3 text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2 opacity-60" />
            <p className="text-xs font-medium text-[var(--text-primary)]">
              No problems or policy violations
            </p>
            <p className="text-[11px] text-[var(--text-muted)] mt-1">
              Permission gateway is strictly enforcing default-deny policies.
            </p>
          </div>
        ) : (
          filtered.map((record) => {
            const isDenied = record.status === 'denied' || record.status === 'rejected';
            return (
              <div
                key={record.id}
                className={`p-2.5 rounded-lg border text-xs space-y-1 ${
                  isDenied
                    ? 'bg-rose-500/5 border-rose-500/20'
                    : 'bg-[var(--bg-surface)] border-[var(--border-subtle)]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] font-semibold text-[var(--text-primary)]">
                    {record.skill_id}
                  </span>
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                      isDenied
                        ? 'bg-rose-500/15 text-rose-500'
                        : 'bg-emerald-500/15 text-emerald-500'
                    }`}
                  >
                    {record.status}
                  </span>
                </div>
                <div className="text-[11px] text-[var(--text-secondary)] font-mono">
                  Actor: {record.actor} • Action: {record.action}
                </div>
                {record.violation_reason && (
                  <p className="text-[11px] text-rose-400 font-medium">
                    {record.violation_reason}
                  </p>
                )}
                <div className="text-[10px] text-[var(--text-muted)] font-mono">
                  {new Date(record.timestamp).toLocaleTimeString()}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

