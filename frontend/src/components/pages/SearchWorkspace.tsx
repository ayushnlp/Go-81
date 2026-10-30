'use client';

import React, { useState, useEffect } from 'react';
import { Search, Folder, FileCode, Wrench, Database, Sparkles, ArrowRight, X } from 'lucide-react';
import { api } from '@/lib/api/client';
import { FileEntry, SkillDefinition, MemoryRecord } from '@/lib/api/types';

interface SearchResultItem {
  id: string;
  category: 'file' | 'skill' | 'memory' | 'action';
  title: string;
  subtitle: string;
  icon: React.ElementType;
  badge: string;
  onClick?: () => void;
}

export const SearchWorkspace: React.FC<{ onNavigate?: (dest: string) => void }> = ({ onNavigate }) => {
  const [query, setQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'file' | 'skill' | 'memory' | 'action'>('all');
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const [filesRes, skillsRes, memRes] = await Promise.all([
          api.listFilesystem('.', true),
          api.getSkills(),
          api.getMemories(),
        ]);
        setFiles(filesRes.data || []);
        setSkills(skillsRes.data || []);
        setMemories(memRes.data || []);
      } catch {
        // graceful offline
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const results: SearchResultItem[] = [];

  // Files
  files.forEach((f) => {
    results.push({
      id: `file-${f.rel_path}`,
      category: 'file',
      title: f.name,
      subtitle: f.rel_path,
      icon: f.is_dir ? Folder : FileCode,
      badge: f.is_dir ? 'Directory' : 'File',
    });
  });

  // Skills
  skills.forEach((s) => {
    results.push({
      id: `skill-${s.id}`,
      category: 'skill',
      title: s.displayName || s.name,
      subtitle: s.description || s.id,
      icon: Wrench,
      badge: s.category.toUpperCase(),
    });
  });

  // Memories
  memories.forEach((m) => {
    results.push({
      id: `mem-${m.id}`,
      category: 'memory',
      title: m.type === 'semantic' ? `${m.subject}: ${m.statement}` : m.title,
      subtitle: m.type === 'semantic' ? `Category: ${m.category}` : m.content.slice(0, 80),
      icon: Database,
      badge: m.type === 'semantic' ? 'Semantic' : 'Episodic',
    });
  });

  // Actions
  const actions = [
    { title: 'Fix an Issue', subtitle: 'Investigate errors, failed tests, or runtime exceptions', dest: 'home' },
    { title: 'Review Recent Changes', subtitle: 'Inspect current file diffs and repository status', dest: 'git' },
    { title: 'System Environment', subtitle: 'Inspect developer toolchains and host diagnostics', dest: 'environment' },
    { title: 'Memory Vault', subtitle: 'Access encrypted project facts and preferences', dest: 'memory' },
    { title: 'Skills Forge', subtitle: 'Explore registered tools and capability policies', dest: 'skills' },
    { title: 'Activity History', subtitle: 'View task execution DAGs and checkpoints', dest: 'activity' },
  ];
  actions.forEach((a, i) => {
    results.push({
      id: `action-${i}`,
      category: 'action',
      title: a.title,
      subtitle: a.subtitle,
      icon: Sparkles,
      badge: 'Action',
      onClick: () => onNavigate && onNavigate(a.dest),
    });
  });

  const filtered = results.filter((item) => {
    if (categoryFilter !== 'all' && item.category !== categoryFilter) return false;
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return item.title.toLowerCase().includes(q) || item.subtitle.toLowerCase().includes(q);
  });

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--bg-canvas)]">
      {/* Search Input Banner */}
      <div className="p-6 md:p-8 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0">
        <div className="max-w-3xl mx-auto space-y-4">
          <div className="relative flex items-center">
            <Search className="w-5 h-5 text-[var(--text-muted)] absolute left-4 pointer-events-none" />
            <input
              type="text"
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search files, registered skills, memories, or actions..."
              className="w-full pl-12 pr-10 py-3 rounded-full bg-[var(--bg-canvas)] border border-[var(--border-subtle)] focus:border-[#ea580c] focus:ring-1 focus:ring-[#ea580c] text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none transition-all shadow-xs"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery('')}
                className="absolute right-4 p-1 rounded-full text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* Filter Chips */}
          <div className="flex items-center space-x-2 overflow-x-auto text-xs font-medium select-none pt-1">
            {(['all', 'file', 'skill', 'memory', 'action'] as const).map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setCategoryFilter(cat)}
                className={`px-3 py-1.5 rounded-full capitalize transition-colors cursor-pointer ${
                  categoryFilter === cat
                    ? 'bg-[#ea580c] text-white font-semibold shadow-xs'
                    : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border-subtle)]'
                }`}
              >
                {cat === 'all' ? 'All Results' : `${cat}s`}
              </button>
            ))}
            <span className="text-xs text-[var(--text-muted)] pl-2">
              {filtered.length} result{filtered.length === 1 ? '' : 's'}
            </span>
          </div>
        </div>
      </div>

      {/* Results List */}
      <div className="flex-1 overflow-y-auto p-6 md:p-8">
        <div className="max-w-3xl mx-auto space-y-2">
          {filtered.length === 0 ? (
            <div className="text-center py-20 text-[var(--text-muted)] text-sm space-y-1">
              <p className="font-medium text-[var(--text-primary)]">No matching results found</p>
              <p className="text-xs">Try adjusting your query or filter keywords.</p>
            </div>
          ) : (
            filtered.map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.id}
                  onClick={item.onClick}
                  className={`p-3.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] hover:border-[var(--accent-primary-border)] transition-all flex items-center justify-between text-left group shadow-2xs ${
                    item.onClick ? 'cursor-pointer' : ''
                  }`}
                >
                  <div className="flex items-center space-x-3 truncate mr-3">
                    <div className="p-2 rounded-lg bg-[var(--bg-elevated)] group-hover:bg-[var(--accent-primary-bg)] text-[var(--text-secondary)] group-hover:text-[#ea580c] transition-colors shrink-0">
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="truncate">
                      <div className="flex items-center space-x-2 truncate">
                        <span className="text-sm font-medium text-[var(--text-primary)] truncate">
                          {item.title}
                        </span>
                        <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-muted)] border border-[var(--border-subtle)] shrink-0">
                          {item.badge}
                        </span>
                      </div>
                      <p className="text-xs text-[var(--text-muted)] truncate mt-0.5 font-mono">
                        {item.subtitle}
                      </p>
                    </div>
                  </div>
                  {item.onClick && (
                    <ArrowRight className="w-4 h-4 text-[var(--text-muted)] group-hover:text-[#ea580c] group-hover:translate-x-0.5 transition-all shrink-0" />
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

