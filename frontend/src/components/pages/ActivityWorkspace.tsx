'use client';

import React, { useState, useEffect } from 'react';
import {
  History,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  RefreshCw,
  Search,
  Plus,
  GitCommit,
  Clock,
  Bookmark,
} from 'lucide-react';
import { api } from '@/lib/api/client';
import { FlightRecorderEvent, ProjectCheckpoint } from '@/lib/api/types';

export const ActivityWorkspace: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'timeline' | 'checkpoints'>('timeline');
  const [events, setEvents] = useState<FlightRecorderEvent[]>([]);
  const [checkpoints, setCheckpoints] = useState<ProjectCheckpoint[]>([]);
  const [filter, setFilter] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const fetchData = async () => {
    setIsLoading(true);
    setStatusMessage(null);
    try {
      const [eventsRes, checkRes] = await Promise.all([
        api.getEvents(100),
        api.getCheckpoints(50),
      ]);
      setEvents(eventsRes.data || []);
      setCheckpoints(checkRes.data || []);
    } catch {
      setStatusMessage('Flight recorder ledger offline. Showing cached timeline.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleSaveCheckpoint = async () => {
    setIsSaving(true);
    try {
      const res = await api.createCheckpoint('Manual operator checkpoint');
      if (res.data) {
        if (res.data) setCheckpoints((prev) => [res.data!, ...prev]);
        setStatusMessage('Checkpoint saved to sovereign ledger.');
        setTimeout(() => setStatusMessage(null), 3000);
      }
    } catch {
      setStatusMessage('Failed to persist checkpoint.');
    } finally {
      setIsSaving(false);
    }
  };

  const filteredEvents = events.filter((e) => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    const summary = String(e.payload?.summary || e.payload?.message || e.event_type).toLowerCase();
    return (
      summary.includes(q) ||
      e.event_type.toLowerCase().includes(q) ||
      Boolean(e.task_id && e.task_id.toLowerCase().includes(q))
    );
  });

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--bg-canvas)]">
      {/* Top Controls Toolbar */}
      <div className="px-6 py-4 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0 flex flex-wrap items-center justify-between gap-4 select-none">
        {/* Tabs */}
        <div className="flex items-center space-x-1.5 p-1 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-xs font-medium">
          <button
            type="button"
            onClick={() => setActiveTab('timeline')}
            className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
              activeTab === 'timeline'
                ? 'bg-[var(--bg-surface)] text-[var(--text-primary)] font-semibold shadow-2xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Flight Recorder Timeline ({events.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('checkpoints')}
            className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
              activeTab === 'checkpoints'
                ? 'bg-[var(--bg-surface)] text-[var(--text-primary)] font-semibold shadow-2xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Checkpoints ({checkpoints.length})
          </button>
        </div>

        {/* Right Tools: Filter, Save, Refresh */}
        <div className="flex items-center space-x-2">
          <div className="flex items-center px-3 py-1.5 rounded-full bg-[var(--bg-canvas)] border border-[var(--border-subtle)] focus-within:border-[#ea580c] transition-colors w-48 sm:w-60">
            <Search className="w-3.5 h-3.5 text-[var(--text-muted)] mr-2 shrink-0" />
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter events..."
              className="w-full bg-transparent text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none"
            />
          </div>

          <button
            type="button"
            onClick={handleSaveCheckpoint}
            disabled={isSaving}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs bg-[#ea580c] hover:bg-[#c2410c] text-white font-semibold transition-colors cursor-pointer shadow-xs disabled:opacity-50"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Checkpoint</span>
          </button>

          <button
            type="button"
            onClick={fetchData}
            disabled={isLoading}
            title="Refresh history"
            className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] transition-colors cursor-pointer shadow-2xs"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {statusMessage && (
        <div className="mx-6 mt-4 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-500 font-medium">
          {statusMessage}
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-6 md:p-8">
        <div className="max-w-4xl mx-auto space-y-4">
          {activeTab === 'timeline' ? (
            filteredEvents.length === 0 ? (
              <div className="text-center py-20 text-[var(--text-muted)] text-sm space-y-1 select-none">
                <History className="w-8 h-8 text-[var(--text-muted)] opacity-40 mx-auto mb-2" />
                <p className="font-semibold text-[var(--text-primary)]">No activity events recorded</p>
                <p className="text-xs">Orchestrator executions and tool actions are automatically logged here.</p>
              </div>
            ) : (
              <div className="space-y-2.5">
                {filteredEvents.map((ev) => {
                  const summary = String(ev.payload?.summary || ev.payload?.message || ev.event_type);
                  return (
                    <div
                      key={ev.event_id}
                      className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:border-[var(--accent-primary-border)] shadow-2xs transition-all flex items-start justify-between"
                    >
                      <div className="flex items-start space-x-3 truncate mr-3">
                        <div className="p-2 rounded-lg bg-[var(--bg-elevated)] text-[#ea580c] shrink-0 mt-0.5">
                          <Clock className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="flex items-center space-x-2">
                            <span className="text-xs font-bold text-[var(--text-primary)] font-mono">
                              {ev.event_type}
                            </span>
                            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-muted)] border border-[var(--border-subtle)]">
                              {ev.source_type}
                            </span>
                          </div>
                          <p className="text-xs text-[var(--text-secondary)] mt-1 font-medium leading-relaxed">
                            {summary}
                          </p>
                          {ev.task_id && (
                            <span className="text-[10px] text-[var(--text-muted)] font-mono block mt-1">
                              Task: {ev.task_id}
                            </span>
                          )}
                        </div>
                      </div>

                      <span className="text-[11px] font-mono text-[var(--text-muted)] shrink-0">
                        {new Date(ev.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </span>
                    </div>
                  );
                })}
              </div>
            )
          ) : (
            checkpoints.length === 0 ? (
              <div className="text-center py-20 text-[var(--text-muted)] text-sm space-y-1 select-none">
                <Bookmark className="w-8 h-8 text-[var(--text-muted)] opacity-40 mx-auto mb-2" />
                <p className="font-semibold text-[var(--text-primary)]">No checkpoints stored</p>
                <p className="text-xs">Click '+ Checkpoint' to create an instant state snapshot.</p>
              </div>
            ) : (
              <div className="space-y-2.5">
                {checkpoints.map((cp) => (
                  <div
                    key={cp.checkpoint_id}
                    className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-2xs flex items-center justify-between"
                  >
                    <div className="flex items-center space-x-3 truncate mr-2">
                      <div className="p-2 rounded-lg bg-[var(--bg-elevated)] text-[#ea580c] shrink-0">
                        <Bookmark className="w-4 h-4" />
                      </div>
                      <div className="truncate">
                        <h4 className="text-xs font-bold text-[var(--text-primary)] truncate">
                          {cp.label || cp.description || cp.checkpoint_id}
                        </h4>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono block mt-0.5">
                          ID: {cp.checkpoint_id} • Commit: {cp.git_commit ? cp.git_commit.slice(0, 7) : 'HEAD'}
                        </span>
                      </div>
                    </div>
                    <span className="text-[11px] font-mono text-[var(--text-muted)] shrink-0">
                      {new Date(cp.timestamp).toLocaleDateString()}
                    </span>
                  </div>
                ))}
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
};
