'use client';

import React, { useState, useEffect } from 'react';
import {
  Folder,
  FolderOpen,
  File,
  FileCode,
  FileText,
  Search,
  RefreshCw,
  AlertCircle,
  ShieldCheck,
} from 'lucide-react';
import { api } from '@/lib/api/client';
import { FileEntry } from '@/lib/api/types';

interface ExplorerPanelProps {
  onSelectFile?: (file: FileEntry) => void;
}

export const ExplorerPanel: React.FC<ExplorerPanelProps> = ({ onSelectFile }) => {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [filter, setFilter] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  const fetchFiles = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.listFilesystem('.', true);
      if (res.error) {
        setError(res.error);
      }
      setEntries(res.data || []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Filesystem listing failed.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchFiles();
  }, []);

  const filteredEntries = entries.filter((e) =>
    e.name.toLowerCase().includes(filter.toLowerCase()) ||
    e.rel_path.toLowerCase().includes(filter.toLowerCase())
  );

  const getFileIcon = (entry: FileEntry) => {
    if (entry.is_dir) {
      return <Folder className="w-4 h-4 text-amber-500 shrink-0 mr-1.5" />;
    }
    const ext = entry.name.split('.').pop()?.toLowerCase();
    if (['ts', 'tsx', 'js', 'jsx', 'py', 'json', 'sh'].includes(ext || '')) {
      return <FileCode className="w-4 h-4 text-orange-400 shrink-0 mr-1.5" />;
    }
    return <FileText className="w-4 h-4 text-[var(--text-muted)] shrink-0 mr-1.5" />;
  };

  return (
    <div className="flex flex-col h-full select-none">
      {/* Header */}
      <div className="px-3.5 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Explorer
          </span>
          <div className="flex items-center space-x-1 mt-0.5 text-[10px] text-emerald-500">
            <ShieldCheck className="w-3 h-3" />
            <span>Path-Secured Sandbox</span>
          </div>
        </div>
        <button
          type="button"
          onClick={fetchFiles}
          disabled={isLoading}
          title="Refresh files"
          className="p-1 rounded hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors cursor-pointer"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Filter / Search Bar */}
      <div className="p-2 border-b border-[var(--border-subtle)]">
        <div className="flex items-center px-2 py-1 rounded bg-[var(--bg-canvas)] border border-[var(--border-subtle)]">
          <Search className="w-3.5 h-3.5 text-[var(--text-muted)] mr-1.5 shrink-0" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter files..."
            className="w-full bg-transparent text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none"
          />
        </div>
      </div>

      {/* File Tree List */}
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="py-8 text-center text-xs text-[var(--text-muted)] flex flex-col items-center justify-center space-y-2">
            <RefreshCw className="w-4 h-4 animate-spin text-[var(--accent-primary)]" />
            <span>Reading project directory...</span>
          </div>
        ) : error ? (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-500 text-xs">
            <div className="flex items-center space-x-1.5 font-medium mb-1">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>Filesystem Unavailable</span>
            </div>
            <p className="text-[11px] text-rose-500/80 leading-relaxed">
              {error}
            </p>
          </div>
        ) : filteredEntries.length === 0 ? (
          <div className="py-8 text-center text-xs text-[var(--text-muted)]">
            {filter ? 'No matching files found.' : 'Directory is empty.'}
          </div>
        ) : (
          <div className="space-y-0.5">
            {filteredEntries.map((entry) => {
              const isSelected = selectedPath === entry.rel_path;
              return (
                <button
                  key={entry.rel_path}
                  type="button"
                  onClick={() => {
                    setSelectedPath(entry.rel_path);
                    if (onSelectFile) onSelectFile(entry);
                  }}
                  className={`w-full flex items-center px-2 py-1.5 rounded text-xs transition-colors cursor-pointer text-left truncate ${
                    isSelected
                      ? 'bg-[var(--accent-primary-bg)] text-[var(--accent-primary)] font-medium'
                      : 'text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]'
                  }`}
                >
                  {getFileIcon(entry)}
                  <span className="truncate font-mono text-[11.5px]">{entry.name}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Selected File Footer */}
      {selectedPath && (
        <div className="p-2 border-t border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-[11px] text-[var(--text-muted)] font-mono truncate">
          <span className="text-[var(--text-secondary)] font-medium">Selected: </span>
          {selectedPath}
        </div>
      )}
    </div>
  );
};

