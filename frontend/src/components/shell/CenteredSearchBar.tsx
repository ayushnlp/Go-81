'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Folder, FileCode, Wrench, Database, Sparkles, Loader2, X } from 'lucide-react';
import { api } from '@/lib/api/client';
import { FileEntry, SkillDefinition, MemoryRecord } from '@/lib/api/types';

export interface CenteredSearchItem {
  id: string;
  category: 'file' | 'skill' | 'memory' | 'action';
  title: string;
  subtitle: string;
  icon: React.ElementType;
  badge: string;
  destination: string;
  onClick?: () => void;
}

export interface CenteredSearchBarProps {
  onNavigate: (destination: string, initialQuery?: string) => void;
}

export const CenteredSearchBar: React.FC<CenteredSearchBarProps> = ({ onNavigate }) => {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  // Cached raw items
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [hasLoadedData, setHasLoadedData] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const isMac = typeof window !== 'undefined' && navigator.platform?.toUpperCase().indexOf('MAC') >= 0;
  const shortcutHint = isMac ? '⌘K' : 'Ctrl+K';

  // Load search data once on focus or typing
  const loadSearchData = useCallback(async () => {
    if (hasLoadedData || isLoading) return;
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
      setHasLoadedData(true);
    } catch {
      // Graceful offline fallback
    } finally {
      setIsLoading(false);
    }
  }, [hasLoadedData, isLoading]);

  // Global keyboard shortcut (Ctrl+K or ⌘K)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        setIsOpen(true);
        loadSearchData();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [loadSearchData]);

  // Click outside listener
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Standard Action items
  const defaultActions = [
    { title: 'Fix an Issue', subtitle: 'Investigate errors, failed tests, or runtime exceptions', dest: 'home' },
    { title: 'Review Recent Changes', subtitle: 'Inspect current file diffs and repository status', dest: 'git' },
    { title: 'System Environment', subtitle: 'Inspect developer toolchains and host diagnostics', dest: 'environment' },
    { title: 'Memory Vault', subtitle: 'Access encrypted project facts and preferences', dest: 'memory' },
    { title: 'Skills Forge', subtitle: 'Explore registered tools and capability policies', dest: 'skills' },
    { title: 'Activity History', subtitle: 'View task execution DAGs and checkpoints', dest: 'activity' },
  ];

  // Compile results
  const allItems: CenteredSearchItem[] = [];

  // Files
  files.forEach((f) => {
    allItems.push({
      id: `file-${f.rel_path}`,
      category: 'file',
      title: f.name,
      subtitle: f.rel_path,
      icon: f.is_dir ? Folder : FileCode,
      badge: f.is_dir ? 'Dir' : 'File',
      destination: 'explorer',
    });
  });

  // Skills
  skills.forEach((s) => {
    allItems.push({
      id: `skill-${s.id}`,
      category: 'skill',
      title: s.displayName || s.name,
      subtitle: s.description || s.id,
      icon: Wrench,
      badge: s.category.toUpperCase(),
      destination: 'skills',
    });
  });

  // Memories
  memories.forEach((m) => {
    allItems.push({
      id: `mem-${m.id}`,
      category: 'memory',
      title: m.type === 'semantic' ? `${m.subject}: ${m.statement}` : m.title,
      subtitle: m.type === 'semantic' ? `Category: ${m.category}` : m.content.slice(0, 80),
      icon: Database,
      badge: m.type === 'semantic' ? 'Semantic' : 'Episodic',
      destination: 'memory',
    });
  });

  // Actions
  defaultActions.forEach((a, i) => {
    allItems.push({
      id: `action-${i}`,
      category: 'action',
      title: a.title,
      subtitle: a.subtitle,
      icon: Sparkles,
      badge: 'Action',
      destination: a.dest,
    });
  });

  // Filter items based on user query
  const filteredItems = query.trim()
    ? allItems.filter((item) => {
        const q = query.toLowerCase();
        return (
          item.title.toLowerCase().includes(q) ||
          item.subtitle.toLowerCase().includes(q) ||
          item.category.toLowerCase().includes(q)
        );
      }).slice(0, 16)
    : allItems.filter((item) => item.category === 'action' || item.category === 'file').slice(0, 8);

  // Group by category
  const groupedResults: { [key: string]: CenteredSearchItem[] } = {};
  filteredItems.forEach((item) => {
    const cat = item.category;
    if (!groupedResults[cat]) groupedResults[cat] = [];
    groupedResults[cat].push(item);
  });

  // Flat list for keyboard indexing
  const flatSelectable = filteredItems;

  const handleSelectItem = (item: CenteredSearchItem) => {
    setIsOpen(false);
    if (item.onClick) {
      item.onClick();
    } else {
      onNavigate(item.destination, query);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setIsOpen(true);
      setActiveIndex((prev) => (prev < flatSelectable.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setIsOpen(true);
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : flatSelectable.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0 && activeIndex < flatSelectable.length) {
        handleSelectItem(flatSelectable[activeIndex]);
      } else {
        // Pressing Enter opens full Search Workspace with query prefilled
        setIsOpen(false);
        onNavigate('search', query);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setIsOpen(false);
    }
  };

  return (
    <div ref={containerRef} className="relative w-full max-w-[440px] sm:max-w-[480px]">
      {/* Search Input Box */}
      <div className="relative flex items-center">
        <Search className="w-3.5 h-3.5 text-[var(--text-muted)] absolute left-3.5 pointer-events-none shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onFocus={() => {
            setIsOpen(true);
            loadSearchData();
          }}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
            setActiveIndex(-1);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Search files, memories, skills and actions..."
          aria-label="Global Search"
          className="w-full pl-9 pr-14 py-1.5 rounded-full bg-[var(--bg-canvas)] border border-[var(--border-subtle)] hover:border-[var(--border-medium)] focus:border-[#F4511E] focus:ring-1 focus:ring-[#F4511E] text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none transition-all shadow-xs"
        />

        <div className="absolute right-2.5 flex items-center space-x-1.5">
          {isLoading ? (
            <Loader2 className="w-3.5 h-3.5 text-[var(--text-muted)] animate-spin" />
          ) : query ? (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                inputRef.current?.focus();
              }}
              className="p-0.5 rounded-full text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
            >
              <X className="w-3 h-3" />
            </button>
          ) : (
            <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[9px] font-mono rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-muted)] select-none">
              {shortcutHint}
            </kbd>
          )}
        </div>
      </div>

      {/* Floating Results Dropdown */}
      {isOpen && (
        <div
          ref={listRef}
          className="absolute left-0 right-0 top-full mt-1.5 max-h-[380px] overflow-y-auto rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] shadow-xl z-50 py-2 divide-y divide-[var(--border-subtle)] select-none animate-in fade-in zoom-in-95 duration-100"
        >
          {filteredItems.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-[var(--text-muted)]">
              <p>No matching files, skills, or memories found.</p>
              <p className="mt-1 text-[11px] text-[var(--text-muted)]/70">
                Press <kbd className="font-mono font-semibold">Enter</kbd> to search the full Search Workspace.
              </p>
            </div>
          ) : (
            Object.entries(groupedResults).map(([category, items]) => (
              <div key={category} className="py-1">
                <div className="px-3 py-1 text-[10px] font-semibold tracking-wider text-[var(--text-muted)] uppercase flex items-center justify-between">
                  <span>{category}s</span>
                  <span className="text-[9px] font-mono opacity-60">{items.length}</span>
                </div>
                {items.map((item) => {
                  const globalIdx = flatSelectable.findIndex((fi) => fi.id === item.id);
                  const isSelected = globalIdx === activeIndex;
                  const Icon = item.icon;

                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => handleSelectItem(item)}
                      onMouseEnter={() => setActiveIndex(globalIdx)}
                      className={`w-full px-3 py-1.5 flex items-center space-x-2.5 text-left text-xs transition-colors cursor-pointer ${
                        isSelected
                          ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                          : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                      }`}
                    >
                      <div className="p-1 rounded-md bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-muted)] shrink-0">
                        <Icon className="w-3.5 h-3.5" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center space-x-1.5">
                          <span className="font-medium text-[var(--text-primary)] truncate text-[12px]">
                            {item.title}
                          </span>
                          <span className="px-1.5 py-0.2 text-[9px] font-mono rounded bg-[var(--bg-surface)] text-[var(--text-muted)] border border-[var(--border-subtle)] shrink-0">
                            {item.badge}
                          </span>
                        </div>
                        <p className="text-[11px] text-[var(--text-muted)] truncate">
                          {item.subtitle}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>
            ))
          )}

          {/* Footer query hint */}
          <div className="px-3 pt-2 pb-1 text-[10px] text-[var(--text-muted)] flex items-center justify-between">
            <span>Press <kbd className="font-mono px-1 py-0.5 rounded bg-[var(--bg-surface)] border border-[var(--border-subtle)]">↵</kbd> to open Search Workspace</span>
            <span><kbd className="font-mono px-1 py-0.5 rounded bg-[var(--bg-surface)] border border-[var(--border-subtle)]">ESC</kbd> to close</span>
          </div>
        </div>
      )}
    </div>
  );
};

