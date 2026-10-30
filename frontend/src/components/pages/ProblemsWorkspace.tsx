'use client';

import React, { useState, useEffect } from 'react';
import { ShieldAlert, AlertCircle, CheckCircle2, RefreshCw, Lock, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api/client';
import { AuditRecord } from '@/lib/api/types';

export const ProblemsWorkspace: React.FC = () => {
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
  const allowedCount = records.filter((r) => r.status === 'allowed' || r.status === 'approved').length;

  const filtered = records.filter((r) => {
    if (filter === 'denied') return r.status === 'denied' || r.status === 'rejected';
    if (filter === 'allowed') return r.status === 'allowed' || r.status === 'approved';
    return true;
  });

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--bg-canvas)]">
      {/* Top Filter and Actions Toolbar */}
      <div className="px-6 py-4 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0 flex flex-wrap items-center justify-between gap-4 select-none">
        {/* Filter Pills */}
        <div className="flex items-center space-x-2 text-xs font-medium">
          <button
            type="button"
            onClick={() => setFilter('all')}
            className={`px-3 py-1.5 rounded-full transition-colors cursor-pointer ${
              filter === 'all'
                ? 'bg-[#ea580c] text-white font-semibold shadow-xs'
                : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border-subtle)]'
            }`}
          >
            All Audit Records ({records.length})
          </button>
          <button
            type="button"
            onClick={() => setFilter('denied')}
            className={`px-3 py-1.5 rounded-full transition-colors cursor-pointer ${
              filter === 'denied'
                ? 'bg-rose-500 text-white font-semibold shadow-xs'
                : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-rose-500 border border-[var(--border-subtle)]'
            }`}
          >
            Denied / Violations ({deniedCount})
          </button>
          <button
            type="button"
            onClick={() => setFilter('allowed')}
            className={`px-3 py-1.5 rounded-full transition-colors cursor-pointer ${
              filter === 'allowed'
                ? 'bg-emerald-600 text-white font-semibold shadow-xs'
                : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-emerald-500 border border-[var(--border-subtle)]'
            }`}
          >
            Authorized ({allowedCount})
          </button>
        </div>

        <button
          type="button"
          onClick={fetchAudit}
          disabled={isLoading}
          title="Refresh audit records"
          className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] transition-colors cursor-pointer shadow-2xs"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-6 md:p-8">
        <div className="max-w-4xl mx-auto space-y-4">
          <div className="flex items-center justify-between text-xs text-[var(--text-muted)] px-1 select-none">
            <span>Stage 3 & 4 Security Gateway Ledger • Redacted Audit</span>
            <span>{filtered.length} event{filtered.length === 1 ? '' : 's'}</span>
          </div>

          {filtered.length === 0 ? (
            <div className="text-center py-20 text-[var(--text-muted)] text-sm space-y-1 select-none">
              <ShieldCheck className="w-8 h-8 text-emerald-500 opacity-60 mx-auto mb-2" />
              <p className="font-semibold text-[var(--text-primary)]">No diagnostics or violations recorded</p>
              <p className="text-xs">Security Permission Gateway operates cleanly under default-deny policy.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {filtered.map((r) => {
                const isDenied = r.status === 'denied' || r.status === 'rejected';
                return (
                  <div
                    key={r.id}
                    className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:border-[var(--accent-primary-border)] shadow-2xs transition-all space-y-2.5"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center space-x-2.5">
                        <div className={`p-1.5 rounded-lg ${isDenied ? 'bg-rose-500/10 text-rose-500' : 'bg-emerald-500/10 text-emerald-500'}`}>
                          {isDenied ? <ShieldAlert className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
                        </div>
                        <div>
                          <div className="flex items-center space-x-2">
                            <span className="font-mono text-xs font-bold text-[var(--text-primary)]">
                              {r.action || r.skill_id || 'Unknown action'}
                            </span>
                            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                              isDenied ? 'bg-rose-500/10 text-rose-500 border border-rose-500/20' : 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                            }`}>
                              {r.status}
                            </span>
                          </div>
                          {r.violation_reason && (
                            <p className="text-xs text-[var(--text-secondary)] mt-1 font-medium leading-relaxed">
                              {r.violation_reason}
                            </p>
                          )}
                        </div>
                      </div>

                      <span className="text-[11px] font-mono text-[var(--text-muted)] shrink-0">
                        {new Date(r.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </span>
                    </div>

                    {r.id && (
                      <div className="pt-2 border-t border-[var(--border-subtle)] flex items-center justify-between text-[11px] text-[var(--text-muted)] font-mono">
                        <span className="truncate max-w-[320px]">
                          Action Hash: {r.id}
                        </span>
                        <span>Actor: {r.actor || 'orchestrator'}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
