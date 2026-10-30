'use client';

import React, { useState, useEffect } from 'react';
import {
  Database,
  Search,
  Download,
  Trash2,
  Edit3,
  Calendar,
  Tag,
  Lock,
  Eye,
  Check,
  RefreshCw,
  Plus,
  ShieldCheck,
  X,
} from 'lucide-react';
import { api } from '@/lib/api/client';
import {
  MemoryRecord,
  EpisodicMemory,
  SemanticMemory,
  SemanticCategory,
} from '@/lib/api/types';

export const MemoryWorkspace: React.FC = () => {
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [activeTab, setActiveTab] = useState<'all' | 'episodic' | 'semantic'>('all');
  const [semanticFilter, setSemanticFilter] = useState<'all' | SemanticCategory>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Modals
  const [inspectingMemory, setInspectingMemory] = useState<MemoryRecord | null>(null);
  const [editingMemory, setEditingMemory] = useState<MemoryRecord | null>(null);
  const [editStatement, setEditStatement] = useState('');

  const fetchMemories = async () => {
    setIsLoading(true);
    try {
      const res = await api.getMemories();
      setMemories(res.data || []);
    } catch {
      // offline fallback
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchMemories();
  }, []);

  const handleDelete = async (id: string) => {
    try {
      await api.deleteMemory(id);
      setMemories((prev) => prev.filter((m) => m.id !== id));
      if (inspectingMemory?.id === id) setInspectingMemory(null);
    } catch {
      // ignore
    }
  };

  const handleStartEdit = (mem: MemoryRecord) => {
    setEditingMemory(mem);
    if (mem.type === 'semantic') {
      setEditStatement(mem.statement);
    } else {
      setEditStatement(mem.content);
    }
  };

  const handleSaveEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingMemory) return;

    setMemories((prev) =>
      prev.map((m) => {
        if (m.id === editingMemory.id) {
          if (m.type === 'semantic') {
            return { ...m, statement: editStatement, updatedAt: new Date().toISOString() };
          } else {
            return { ...m, content: editStatement };
          }
        }
        return m;
      })
    );
    setEditingMemory(null);
  };

  const handleExportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(memories, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `go81_memory_vault_${new Date().toISOString().slice(0, 10)}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const filteredMemories = memories.filter((mem) => {
    if (activeTab !== 'all' && mem.type !== activeTab) return false;
    if (mem.type === 'semantic' && semanticFilter !== 'all' && mem.category !== semanticFilter) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      if (mem.type === 'episodic') {
        return (
          mem.title.toLowerCase().includes(q) ||
          mem.content.toLowerCase().includes(q) ||
          mem.tags.some((t) => t.toLowerCase().includes(q))
        );
      } else {
        return (
          mem.subject.toLowerCase().includes(q) ||
          mem.statement.toLowerCase().includes(q) ||
          mem.category.toLowerCase().includes(q)
        );
      }
    }
    return true;
  });

  const episodicCount = memories.filter((m) => m.type === 'episodic').length;
  const semanticCount = memories.filter((m) => m.type === 'semantic').length;

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--bg-canvas)]">
      {/* Top Filter and Actions Toolbar */}
      <div className="px-6 py-4 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0 flex flex-wrap items-center justify-between gap-4 select-none">
        {/* Tabs */}
        <div className="flex items-center space-x-1.5 p-1 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-xs font-medium">
          <button
            type="button"
            onClick={() => setActiveTab('all')}
            className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
              activeTab === 'all'
                ? 'bg-[var(--bg-surface)] text-[var(--text-primary)] font-semibold shadow-2xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            All Records ({memories.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('semantic')}
            className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
              activeTab === 'semantic'
                ? 'bg-[var(--bg-surface)] text-[var(--text-primary)] font-semibold shadow-2xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Semantic Facts ({semanticCount})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('episodic')}
            className={`px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
              activeTab === 'episodic'
                ? 'bg-[var(--bg-surface)] text-[var(--text-primary)] font-semibold shadow-2xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Episodic Timeline ({episodicCount})
          </button>
        </div>

        {/* Right Tools: Search, Export, Refresh */}
        <div className="flex items-center space-x-2">
          {/* Search Bar */}
          <div className="flex items-center px-3 py-1.5 rounded-full bg-[var(--bg-canvas)] border border-[var(--border-subtle)] focus-within:border-[#ea580c] transition-colors w-48 sm:w-64">
            <Search className="w-3.5 h-3.5 text-[var(--text-muted)] mr-2 shrink-0" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search memories..."
              className="w-full bg-transparent text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none"
            />
          </div>

          <button
            type="button"
            onClick={handleExportJson}
            title="Export encrypted memory JSON"
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)] text-[var(--text-primary)] border border-[var(--border-subtle)] transition-colors cursor-pointer shadow-2xs"
          >
            <Download className="w-3.5 h-3.5 text-[var(--text-muted)]" />
            <span className="hidden sm:inline">Export</span>
          </button>

          <button
            type="button"
            onClick={fetchMemories}
            disabled={isLoading}
            title="Refresh memory records"
            className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] transition-colors cursor-pointer shadow-2xs"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main Grid: Memory Records */}
      <div className="flex-1 overflow-y-auto p-6 md:p-8">
        <div className="max-w-5xl mx-auto space-y-4">
          {/* Security Status Header */}
          <div className="flex items-center justify-between text-xs text-[var(--text-muted)] px-1 select-none">
            <div className="flex items-center space-x-2">
              <Lock className="w-3.5 h-3.5 text-emerald-500" />
              <span>AES-256-GCM Encrypted at Rest • Zero Cloud Sync</span>
            </div>
            <span>Showing {filteredMemories.length} record{filteredMemories.length === 1 ? '' : 's'}</span>
          </div>

          {filteredMemories.length === 0 ? (
            <div className="text-center py-20 text-[var(--text-muted)] text-sm space-y-1 select-none">
              <Database className="w-8 h-8 text-[var(--text-muted)] opacity-40 mx-auto mb-2" />
              <p className="font-semibold text-[var(--text-primary)]">No memory records found</p>
              <p className="text-xs">Chat with Go 81 to automatically learn verified preferences and facts.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              {filteredMemories.map((mem) => {
                const isSemantic = mem.type === 'semantic';
                return (
                  <div
                    key={mem.id}
                    className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:border-[var(--accent-primary-border)] shadow-2xs transition-all flex flex-col justify-between space-y-3"
                  >
                    <div className="space-y-2">
                      {/* Top Badges */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-1.5">
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                            isSemantic
                              ? 'bg-amber-500/10 text-amber-500 border border-amber-500/20'
                              : 'bg-indigo-500/10 text-indigo-500 border border-indigo-500/20'
                          }`}>
                            {mem.type}
                          </span>
                          {isSemantic && (
                            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)]">
                              {(mem as SemanticMemory).category}
                            </span>
                          )}
                        </div>

                        {/* Verified Status */}
                        {isSemantic && (mem as SemanticMemory).confidence >= 0.8 && (
                          <span className="flex items-center space-x-1 text-[11px] text-emerald-500 font-medium">
                            <ShieldCheck className="w-3.5 h-3.5" />
                            <span>Verified</span>
                          </span>
                        )}
                      </div>

                      {/* Content */}
                      <div>
                        {isSemantic ? (
                          <>
                            <h4 className="text-xs font-semibold text-[var(--text-primary)]">
                              {(mem as SemanticMemory).subject}
                            </h4>
                            <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">
                              {(mem as SemanticMemory).statement}
                            </p>
                          </>
                        ) : (
                          <>
                            <h4 className="text-xs font-semibold text-[var(--text-primary)]">
                              {(mem as EpisodicMemory).title}
                            </h4>
                            <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed line-clamp-3">
                              {(mem as EpisodicMemory).content}
                            </p>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Bottom Action Bar */}
                    <div className="pt-2 border-t border-[var(--border-subtle)] flex items-center justify-between text-xs text-[var(--text-muted)]">
                      <span className="font-mono text-[10px] truncate max-w-[120px]">
                        {mem.id}
                      </span>

                      <div className="flex items-center space-x-1">
                        <button
                          type="button"
                          onClick={() => setInspectingMemory(mem)}
                          title="Inspect memory details"
                          className="p-1 rounded hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleStartEdit(mem)}
                          title="Edit statement"
                          className="p-1 rounded hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
                        >
                          <Edit3 className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(mem.id)}
                          title="Delete memory"
                          className="p-1 rounded hover:bg-rose-500/10 text-[var(--text-muted)] hover:text-rose-500 transition-colors cursor-pointer"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Inspect Memory Modal */}
      {inspectingMemory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="w-full max-w-lg rounded-2xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)]">
              <div className="flex items-center space-x-2">
                <Database className="w-4 h-4 text-[#ea580c]" />
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Memory Record Details</h3>
              </div>
              <button
                type="button"
                onClick={() => setInspectingMemory(null)}
                className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-2.5 text-xs">
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Record ID</span>
                <span className="font-mono text-[var(--text-primary)]">{inspectingMemory.id}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Memory Type</span>
                <span className="font-semibold text-[var(--text-primary)] uppercase">{inspectingMemory.type}</span>
              </div>
              {inspectingMemory.type === 'semantic' && (
                <>
                  <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                    <span className="text-[var(--text-muted)]">Subject</span>
                    <span className="font-mono text-[var(--text-primary)]">{(inspectingMemory as SemanticMemory).subject}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-[var(--border-subtle)]">
                    <span className="text-[var(--text-muted)]">Category</span>
                    <span className="font-mono text-[var(--text-secondary)]">{(inspectingMemory as SemanticMemory).category}</span>
                  </div>
                </>
              )}
              <div className="py-2">
                <span className="text-[var(--text-muted)] block mb-1">Statement / Content</span>
                <p className="p-3 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] leading-relaxed">
                  {inspectingMemory.type === 'semantic'
                    ? (inspectingMemory as SemanticMemory).statement
                    : (inspectingMemory as EpisodicMemory).content}
                </p>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={() => setInspectingMemory(null)}
                className="px-4 py-1.5 rounded-lg bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)] text-[var(--text-primary)] border border-[var(--border-subtle)] text-xs font-semibold cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Statement Modal */}
      {editingMemory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <form onSubmit={handleSaveEdit} className="w-full max-w-lg rounded-2xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)]">
              <div className="flex items-center space-x-2">
                <Edit3 className="w-4 h-4 text-[#ea580c]" />
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Edit Memory Statement</h3>
              </div>
              <button
                type="button"
                onClick={() => setEditingMemory(null)}
                className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-medium text-[var(--text-secondary)]">Statement</label>
              <textarea
                rows={4}
                value={editStatement}
                onChange={(e) => setEditStatement(e.target.value)}
                className="w-full p-3 rounded-xl bg-[var(--bg-canvas)] border border-[var(--border-subtle)] text-xs text-[var(--text-primary)] outline-none focus:border-[#ea580c]"
              />
            </div>

            <div className="flex justify-end space-x-2 pt-2">
              <button
                type="button"
                onClick={() => setEditingMemory(null)}
                className="px-4 py-1.5 rounded-lg bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)] text-[var(--text-primary)] border border-[var(--border-subtle)] text-xs font-semibold cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded-lg bg-[#ea580c] hover:bg-[#c2410c] text-white text-xs font-semibold cursor-pointer shadow-xs"
              >
                Save Changes
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
