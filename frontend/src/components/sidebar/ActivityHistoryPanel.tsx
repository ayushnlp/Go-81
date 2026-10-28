'use client';

import React, { useState, useEffect } from 'react';
import {
  History,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  Bookmark,
  RefreshCw,
  Search,
  Plus,
  RotateCcw,
  GitCommit,
  Clock,
} from 'lucide-react';
import { api } from '@/lib/api/client';
import { FlightRecorderEvent, ProjectCheckpoint } from '@/lib/api/types';

interface ActivityHistoryPanelProps {
  onSaveCheckpointTrigger?: () => void;
}

export const ActivityHistoryPanel: React.FC<ActivityHistoryPanelProps> = ({
  onSaveCheckpointTrigger,
}) => {
  const [activeTab, setActiveTab] = useState<'timeline' | 'checkpoints' | 'diff'>('timeline');
  const [events, setEvents] = useState<FlightRecorderEvent[]>([]);
  const [checkpoints, setCheckpoints] = useState<ProjectCheckpoint[]>([]);
  const [filter, setFilter] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('all');
  const [isLoading, setIsLoading] = useState(false);
  const [isSavingCheckpoint, setIsSavingCheckpoint] = useState(false);
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
      setStatusMessage('Unable to connect to flight recorder service.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleSaveCheckpoint = async () => {
    setIsSavingCheckpoint(true);
    setStatusMessage(null);
    try {
      const res = await api.createCheckpoint(
        `Checkpoint ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
        'User triggered checkpoint from Activity History'
      );
      if (res.data) {
        setStatusMessage('Checkpoint successfully captured and hashed.');
        fetchData();
      } else {
        setStatusMessage(res.error || 'Failed to create checkpoint.');
      }
    } catch (e: unknown) {
      setStatusMessage(e instanceof Error ? e.message : 'Checkpoint creation failed.');
    } finally {
      setIsSavingCheckpoint(false);
    }
  };

  const filteredEvents = events.filter((ev) => {
    const matchesQuery =
      ev.event_type.toLowerCase().includes(filter.toLowerCase()) ||
      JSON.stringify(ev.payload || {}).toLowerCase().includes(filter.toLowerCase());
    if (eventTypeFilter === 'all') return matchesQuery;
    return matchesQuery && ev.event_type.toLowerCase().includes(eventTypeFilter.toLowerCase());
  });

  return (
    <div className="flex flex-col h-full select-none">
      {/* Header */}
      <div className="px-3.5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Activity & History
          </span>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
            Flight recorder & verified checkpoints
          </p>
        </div>
        <button
          type="button"
          onClick={fetchData}
          disabled={isLoading}
          title="Refresh activity logs"
          className="p-1 rounded hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors cursor-pointer"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Segmented Sub-Tabs */}
      <div className="px-3 pt-2.5 pb-2 border-b border-[var(--border-subtle)] flex space-x-1">
        {(['timeline', 'checkpoints', 'diff'] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`flex-1 py-1 text-center rounded text-xs font-medium capitalize transition-colors cursor-pointer ${
              activeTab === tab
                ? 'bg-[var(--bg-elevated)] text-[var(--accent-primary)] border border-[var(--border-subtle)]'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            {tab === 'diff' ? 'Diff Analysis' : tab}
          </button>
        ))}
      </div>

      {/* Filter and Search */}
      {activeTab === 'timeline' && (
        <div className="p-2 border-b border-[var(--border-subtle)] space-y-1.5">
          <div className="flex items-center px-2 py-1 rounded bg-[var(--bg-canvas)] border border-[var(--border-subtle)]">
            <Search className="w-3.5 h-3.5 text-[var(--text-muted)] mr-1.5 shrink-0" />
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search events or files..."
              className="w-full bg-transparent text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none"
            />
          </div>
          <div className="flex items-center space-x-1">
            {['all', 'observed', 'analysis', 'changes'].map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setEventTypeFilter(cat)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium capitalize cursor-pointer ${
                  eventTypeFilter === cat
                    ? 'bg-[#ea580c] text-white'
                    : 'bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Checkpoints Action Bar */}
      {activeTab === 'checkpoints' && (
        <div className="p-2 border-b border-[var(--border-subtle)] flex items-center justify-between bg-[var(--bg-elevated)]">
          <span className="text-xs text-[var(--text-secondary)] font-medium">
            Saved manifests ({checkpoints.length})
          </span>
          <button
            type="button"
            onClick={handleSaveCheckpoint}
            disabled={isSavingCheckpoint}
            className="inline-flex items-center space-x-1 px-2.5 py-1 rounded bg-[#ea580c] hover:bg-[#c2410c] text-white text-xs font-medium transition-colors cursor-pointer shadow-xs disabled:opacity-50"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>{isSavingCheckpoint ? 'Saving...' : 'Save Checkpoint'}</span>
          </button>
        </div>
      )}

      {/* Notification Banner */}
      {statusMessage && (
        <div className="p-2 mx-2 mt-2 rounded bg-[var(--accent-primary-bg)] border border-[var(--accent-primary-border)] text-[11px] text-[var(--accent-primary)] font-medium">
          {statusMessage}
        </div>
      )}

      {/* Tab Contents */}
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="py-8 text-center text-xs text-[var(--text-muted)] flex flex-col items-center justify-center space-y-2">
            <RefreshCw className="w-4 h-4 animate-spin text-[var(--accent-primary)]" />
            <span>Loading records...</span>
          </div>
        ) : activeTab === 'timeline' ? (
          filteredEvents.length === 0 ? (
            <div className="py-12 px-3 text-center">
              <Clock className="w-8 h-8 text-[var(--text-muted)] mx-auto mb-2 opacity-50" />
              <p className="text-xs font-medium text-[var(--text-primary)]">
                No activity records found
              </p>
              <p className="text-[11px] text-[var(--text-muted)] mt-1">
                Autonomous task events and tool invocations will appear here chronologically.
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {filteredEvents.map((ev) => (
                <div
                  key={ev.event_id}
                  className="p-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] transition-colors text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] font-semibold text-[var(--text-primary)]">
                      {ev.event_type}
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">
                      {new Date(ev.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] text-[var(--text-secondary)] font-mono break-all line-clamp-2">
                    {JSON.stringify(ev.payload || {})}
                  </div>
                  {ev.evidence_hashes && ev.evidence_hashes.length > 0 && (
                    <div className="mt-1.5 flex items-center space-x-1 text-[10px] text-emerald-500 font-mono">
                      <ShieldCheck className="w-3 h-3" />
                      <span>{ev.evidence_hashes.length} verified evidence hash(es)</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )
        ) : activeTab === 'checkpoints' ? (
          checkpoints.length === 0 ? (
            <div className="py-12 px-3 text-center">
              <Bookmark className="w-8 h-8 text-[var(--text-muted)] mx-auto mb-2 opacity-50" />
              <p className="text-xs font-medium text-[var(--text-primary)]">
                No checkpoints captured
              </p>
              <p className="text-[11px] text-[var(--text-muted)] mt-1">
                Save a checkpoint to snapshot project state with cryptographic hashing.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {checkpoints.map((chk) => (
                <div
                  key={chk.checkpoint_id}
                  className="p-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-surface)] space-y-1.5 text-xs"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="font-medium text-[var(--text-primary)] block">
                        {chk.label || chk.checkpoint_id}
                      </span>
                      <span className="text-[10px] text-[var(--text-muted)] font-mono">
                        {new Date(chk.timestamp).toLocaleString()}
                      </span>
                    </div>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
                      {chk.status || 'VERIFIED'}
                    </span>
                  </div>
                  {chk.description && (
                    <p className="text-[11px] text-[var(--text-secondary)]">{chk.description}</p>
                  )}
                  <div className="pt-1 border-t border-[var(--border-subtle)] flex items-center justify-between text-[10px] font-mono text-[var(--text-muted)]">
                    <span className="truncate max-w-[140px]">Hash: {chk.state_hash.substring(0, 12)}...</span>
                    <button
                      type="button"
                      onClick={async () => {
                        const res = await api.restoreCheckpoint(chk.checkpoint_id);
                        if (res.data?.restored) {
                          setStatusMessage(`Checkpoint ${chk.checkpoint_id} restored safely.`);
                        } else {
                          setStatusMessage(res.error || 'Restore blocked.');
                        }
                      }}
                      className="inline-flex items-center space-x-1 text-[#ea580c] hover:underline cursor-pointer"
                    >
                      <RotateCcw className="w-3 h-3" />
                      <span>Restore</span>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          /* Diff Analysis Tab */
          <div className="py-6 px-3 text-center">
            <GitCommit className="w-8 h-8 text-[var(--text-muted)] mx-auto mb-2 opacity-50" />
            <p className="text-xs font-medium text-[var(--text-primary)]">
              Diff Analysis & Evidence
            </p>
            <p className="text-[11px] text-[var(--text-muted)] mt-1 max-w-xs mx-auto">
              Inspect snapshot modifications across checkpoints. Flight recorder evidence hashes ensure zero tamper.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

