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
  Pin,
  Lock,
  Eye,
  Check,
} from 'lucide-react';
import { AppSidebar } from '@/components/shell/AppSidebar';
import { AppHeader } from '@/components/shell/AppHeader';
import { OfflineBanner } from '@/components/ui/OfflineBanner';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { api } from '@/lib/api/client';
import {
  MemoryRecord,
  EpisodicMemory,
  SemanticMemory,
  SemanticCategory,
} from '@/lib/api/types';

export default function MemoryVaultPage() {
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [activeTab, setActiveTab] = useState<'all' | 'episodic' | 'semantic'>('all');
  const [semanticFilter, setSemanticFilter] = useState<'all' | SemanticCategory>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Editing & Inspection modal states
  const [inspectingMemory, setInspectingMemory] = useState<MemoryRecord | null>(null);
  const [editingMemory, setEditingMemory] = useState<MemoryRecord | null>(null);
  const [editStatement, setEditStatement] = useState('');

  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [isCheckingBackend, setIsCheckingBackend] = useState(false);

  const probe = async () => {
    setIsCheckingBackend(true);
    try {
      const health = await api.checkHealth();
      setIsBackendOnline(health.online);

      const res = await api.getMemories();
      setMemories(res.data);
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

        const res = await api.getMemories();
        if (!isMounted) return;
        setMemories(res.data);
      } catch {
        // graceful offline
      }
    })();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleDelete = async (id: string) => {
    await api.deleteMemory(id);
    setMemories((prev) => prev.filter((m) => m.id !== id));
    if (inspectingMemory?.id === id) setInspectingMemory(null);
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
    <div className="flex min-h-screen bg-[#090b0e] text-zinc-100">
      <AppSidebar />

      <div className="flex-1 flex flex-col min-w-0">
        <OfflineBanner
          isLive={isBackendOnline}
          isChecking={isCheckingBackend}
          onRetry={probe}
          backendUrl={api.getBaseUrl()}
        />

        <AppHeader
          title="Memory Vault"
          subtitle="Persistent episodic saga-log (Muninn) & structured semantic knowledge (Mimir) (FR1)"
          isBackendOnline={isBackendOnline}
          isChecking={isCheckingBackend}
          onRefreshBackend={probe}
        />

        <main className="flex-1 max-w-5xl w-full mx-auto p-4 sm:p-6 space-y-6">
          {/* Top Bar Controls */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            {/* Memory Type Tabs */}
            <div className="flex items-center gap-1 bg-[#101319] p-1 rounded-lg border border-zinc-800 text-xs font-mono">
              <button
                onClick={() => setActiveTab('all')}
                className={`px-3 py-1.5 rounded cursor-pointer ${
                  activeTab === 'all'
                    ? 'bg-zinc-800 text-zinc-100 font-semibold'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                All Runes ({memories.length})
              </button>
              <button
                onClick={() => setActiveTab('episodic')}
                className={`px-3 py-1.5 rounded cursor-pointer ${
                  activeTab === 'episodic'
                    ? 'bg-zinc-800 text-zinc-100 font-semibold'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                Episodic Saga ({episodicCount})
              </button>
              <button
                onClick={() => setActiveTab('semantic')}
                className={`px-3 py-1.5 rounded cursor-pointer ${
                  activeTab === 'semantic'
                    ? 'bg-zinc-800 text-zinc-100 font-semibold'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                Mimir Knowledge ({semanticCount})
              </button>
            </div>

            {/* Actions: Export JSON */}
            <Button
              size="sm"
              variant="outline"
              onClick={handleExportJson}
              icon={<Download className="w-3.5 h-3.5" />}
              className="font-mono text-xs"
            >
              Export Vault (JSON)
            </Button>
          </div>

          {/* Search & Category Sub-filter */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[240px]">
              <Search className="w-4 h-4 text-zinc-500 absolute left-3 top-2.5" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search across memory nodes, subjects, or tags..."
                className="w-full text-xs bg-[#101319] border border-zinc-800 rounded-lg pl-9 pr-3 py-2 text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-emerald-500"
              />
            </div>

            {activeTab !== 'episodic' && (
              <div className="flex items-center gap-1 text-xs font-mono text-zinc-400 bg-[#101319] p-1 rounded-lg border border-zinc-800">
                <span className="text-[11px] text-zinc-500 px-2">Category:</span>
                {(['all', 'fact', 'preference', 'rule', 'entity'] as const).map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setSemanticFilter(cat)}
                    className={`px-2 py-1 rounded cursor-pointer capitalize text-xs ${
                      semanticFilter === cat
                        ? 'bg-zinc-800 text-emerald-400 font-semibold'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Memory Records Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredMemories.length === 0 ? (
              <div className="col-span-2 p-12 text-center rounded-xl bg-[#101319] border border-zinc-800 text-zinc-500 space-y-2">
                <Database className="w-8 h-8 mx-auto text-zinc-600" />
                <p className="text-sm">No memory records matched your criteria.</p>
              </div>
            ) : (
              filteredMemories.map((mem) => {
                const isEpisodic = mem.type === 'episodic';
                const episodic = isEpisodic ? (mem as EpisodicMemory) : null;
                const semantic = !isEpisodic ? (mem as SemanticMemory) : null;

                return (
                  <Card
                    key={mem.id}
                    className="flex flex-col justify-between hover:border-zinc-700 transition-colors"
                  >
                    <CardHeader className="bg-[#121620]/50 py-3">
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={isEpisodic ? 'sky' : 'purple'}
                          className="text-[10px] uppercase font-mono"
                        >
                          {isEpisodic ? 'Episodic' : semantic?.category}
                        </Badge>
                        <span className="font-mono text-[11px] text-zinc-500">
                          #{mem.id}
                        </span>
                        {episodic?.pinned && (
                          <Pin className="w-3 h-3 text-amber-400 rotate-45" />
                        )}
                      </div>

                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setInspectingMemory(mem)}
                          className="p-1 text-zinc-400 hover:text-zinc-200 cursor-pointer"
                          title="Inspect Runes"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleStartEdit(mem)}
                          className="p-1 text-zinc-400 hover:text-zinc-200 cursor-pointer"
                          title="Edit Statement"
                        >
                          <Edit3 className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleDelete(mem.id)}
                          className="p-1 text-zinc-400 hover:text-rose-400 cursor-pointer"
                          title="Norn's Cut (Permanently Forget)"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </CardHeader>

                    <CardContent className="space-y-2 pt-3 flex-1">
                      {isEpisodic ? (
                        <>
                          <h4 className="text-sm font-semibold text-zinc-100">
                            {episodic?.title}
                          </h4>
                          <p className="text-xs text-zinc-300 leading-relaxed line-clamp-3">
                            {episodic?.content}
                          </p>
                          <div className="flex flex-wrap items-center gap-1.5 pt-2">
                            {episodic?.tags.map((t) => (
                              <span
                                key={t}
                                className="text-[10px] font-mono bg-zinc-900 border border-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded flex items-center gap-1"
                              >
                                <Tag className="w-2.5 h-2.5 text-zinc-500" />
                                {t}
                              </span>
                            ))}
                          </div>
                        </>
                      ) : (
                        <>
                          <h4 className="text-sm font-semibold text-zinc-100">
                            {semantic?.subject}
                          </h4>
                          <p className="text-xs text-zinc-300 leading-relaxed font-mono bg-zinc-950/60 p-2.5 rounded border border-zinc-850">
                            &quot;{semantic?.statement}&quot;
                          </p>
                          <div className="flex items-center justify-between text-[11px] font-mono text-zinc-500 pt-1">
                            <span>Confidence: {((semantic?.confidence || 0) * 100).toFixed(0)}%</span>
                            <span>Decay: {semantic?.decayFactor.toFixed(2)}</span>
                          </div>
                        </>
                      )}
                    </CardContent>

                    <div className="px-5 py-2.5 border-t border-zinc-800/60 bg-zinc-950/30 flex items-center justify-between text-[11px] font-mono text-zinc-500">
                      <span className="flex items-center gap-1" suppressHydrationWarning>
                        <Calendar className="w-3 h-3" />
                        {new Date(
                          isEpisodic
                            ? episodic!.timestamp
                            : semantic!.updatedAt
                        ).toLocaleDateString()}
                      </span>
                      <span className="text-emerald-400/90 flex items-center gap-1">
                        <Lock className="w-3 h-3 text-emerald-500" />
                        AES-256 Sealed
                      </span>
                    </div>
                  </Card>
                );
              })
            )}
          </div>
        </main>
      </div>

      {/* Inspect Memory Modal */}
      <Modal
        isOpen={Boolean(inspectingMemory)}
        onClose={() => setInspectingMemory(null)}
        title="Mimir Rune Inspection"
        description="Encrypted vector metadata and raw state representation (FR1.2)"
      >
        {inspectingMemory && (
          <div className="space-y-3 font-mono text-xs">
            <div className="p-3 rounded-lg bg-zinc-950 border border-zinc-800 space-y-1.5">
              <div className="flex justify-between text-zinc-400">
                <span>Rune Identifier:</span>
                <span className="text-zinc-200">{inspectingMemory.id}</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Storage Class:</span>
                <span className="text-emerald-400 uppercase">{inspectingMemory.type}</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Cryptographic Key State:</span>
                <span className="text-emerald-400">SEALED (Host Hardware TPM)</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Embedding Model:</span>
                <span className="text-zinc-300">nomic-embed-text (384-dim)</span>
              </div>
            </div>

            <div>
              <span className="text-[11px] text-zinc-500 uppercase tracking-wider block mb-1">
                Raw Record JSON
              </span>
              <pre className="bg-zinc-950 p-3 rounded-lg border border-zinc-850 text-emerald-300 overflow-x-auto text-[11px]">
                {JSON.stringify(inspectingMemory, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </Modal>

      {/* Edit Memory Modal (NFR4.2 User Control) */}
      <Modal
        isOpen={Boolean(editingMemory)}
        onClose={() => setEditingMemory(null)}
        title="Edit Sovereign Memory"
        description="Direct user control over agent knowledge base (NFR4.2)"
      >
        {editingMemory && (
          <form onSubmit={handleSaveEdit} className="space-y-4">
            <div>
              <label className="text-xs font-medium text-zinc-300 block mb-1">
                {editingMemory.type === 'semantic' ? 'Statement of Fact / Rule:' : 'Episodic Log Content:'}
              </label>
              <textarea
                value={editStatement}
                onChange={(e) => setEditStatement(e.target.value)}
                rows={4}
                required
                className="w-full text-xs font-mono rounded-lg bg-zinc-900 border border-zinc-700/80 p-2.5 text-zinc-200 placeholder-zinc-500 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
              />
            </div>

            <div className="pt-2 border-t border-zinc-800 flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setEditingMemory(null)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                icon={<Check className="w-3.5 h-3.5" />}
              >
                Inscribe Update
              </Button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
