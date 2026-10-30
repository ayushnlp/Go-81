'use client';

import React, { useState, useEffect } from 'react';
import {
  Folder,
  FileCode,
  FileText,
  Search,
  RefreshCw,
  ShieldCheck,
  AlertCircle,
  File,
  Eye,
  Check,
  Copy,
} from 'lucide-react';
import { api } from '@/lib/api/client';
import { FileEntry } from '@/lib/api/types';

export const ExplorerWorkspace: React.FC = () => {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [filter, setFilter] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<FileEntry | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [isLoadingContent, setIsLoadingContent] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

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

  const handleSelectFile = async (entry: FileEntry) => {
    setSelectedFile(entry);
    if (entry.is_dir) {
      setFileContent(null);
      return;
    }
    setIsLoadingContent(true);
    try {
      const res = await api.readFile(entry.rel_path);
      setFileContent(res.data?.content || '(Empty file or binary format)');
    } catch (e: unknown) {
      setFileContent(`Error reading file: ${e instanceof Error ? e.message : 'Failed to load file.'}`);
    } finally {
      setIsLoadingContent(false);
    }
  };

  const handleCopyContent = () => {
    if (!fileContent) return;
    navigator.clipboard.writeText(fileContent);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  const filteredEntries = entries.filter((e) =>
    e.name.toLowerCase().includes(filter.toLowerCase()) ||
    e.rel_path.toLowerCase().includes(filter.toLowerCase())
  );

  const getFileIcon = (entry: FileEntry) => {
    if (entry.is_dir) {
      return <Folder className="w-4 h-4 text-amber-500 shrink-0 mr-2" />;
    }
    const ext = entry.name.split('.').pop()?.toLowerCase();
    if (['ts', 'tsx', 'js', 'jsx', 'py', 'json', 'sh', 'css', 'html'].includes(ext || '')) {
      return <FileCode className="w-4 h-4 text-[#ea580c] shrink-0 mr-2" />;
    }
    return <FileText className="w-4 h-4 text-[var(--text-muted)] shrink-0 mr-2" />;
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--bg-canvas)]">
      {/* Top Action Toolbar */}
      <div className="px-6 py-3.5 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] flex flex-wrap items-center justify-between gap-4 select-none shrink-0">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)]">
            <span className="font-mono font-medium">Path:</span>
            <span className="font-mono text-[var(--text-primary)]">. (Project Root)</span>
          </div>
          <div className="flex items-center space-x-1.5 text-xs text-emerald-500">
            <ShieldCheck className="w-4 h-4" />
            <span className="hidden sm:inline">Path-Secured Sandbox</span>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          {/* Search/Filter Bar */}
          <div className="flex items-center px-3 py-1 rounded-full bg-[var(--bg-canvas)] border border-[var(--border-subtle)] focus-within:border-[var(--accent-primary-border)] transition-colors w-48 sm:w-64">
            <Search className="w-3.5 h-3.5 text-[var(--text-muted)] mr-2 shrink-0" />
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter files..."
              className="w-full bg-transparent text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none"
            />
          </div>

          <button
            type="button"
            onClick={fetchFiles}
            disabled={isLoading}
            title="Refresh files"
            className="p-1.5 rounded-md hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border-subtle)] transition-colors cursor-pointer"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main Split Layout: Files List & File Inspector */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Files List */}
        <div className="w-full md:w-5/12 border-r border-[var(--border-subtle)] bg-[var(--bg-surface)] flex flex-col h-full overflow-hidden">
          <div className="p-3 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)] text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider flex justify-between items-center select-none">
            <span>Project Files ({filteredEntries.length})</span>
            {selectedFile && (
              <span className="text-[11px] font-normal normal-case text-[var(--text-muted)] font-mono truncate max-w-[150px]">
                {selectedFile.name}
              </span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
            {isLoading ? (
              <div className="py-16 text-center text-xs text-[var(--text-muted)] flex flex-col items-center justify-center space-y-2">
                <RefreshCw className="w-5 h-5 animate-spin text-[#ea580c]" />
                <span>Reading project filesystem...</span>
              </div>
            ) : error ? (
              <div className="m-3 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-500 text-xs">
                <div className="flex items-center space-x-1.5 font-semibold mb-1">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>Filesystem Unavailable</span>
                </div>
                <p className="text-[11px] text-rose-500/80 leading-relaxed">{error}</p>
              </div>
            ) : filteredEntries.length === 0 ? (
              <div className="py-16 text-center text-xs text-[var(--text-muted)]">
                {filter ? 'No matching files found.' : 'Directory is empty.'}
              </div>
            ) : (
              filteredEntries.map((entry) => {
                const isSelected = selectedFile?.rel_path === entry.rel_path;
                return (
                  <button
                    key={entry.rel_path}
                    type="button"
                    onClick={() => handleSelectFile(entry)}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs transition-colors cursor-pointer text-left truncate ${
                      isSelected
                        ? 'bg-[var(--accent-primary-bg)] text-[#ea580c] font-semibold border border-[var(--accent-primary-border)]'
                        : 'text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]'
                    }`}
                  >
                    <div className="flex items-center truncate mr-2">
                      {getFileIcon(entry)}
                      <span className="truncate font-mono text-[12px]">{entry.name}</span>
                    </div>
                    {entry.size !== undefined && !entry.is_dir && (
                      <span className="text-[10px] text-[var(--text-muted)] font-mono shrink-0">
                        {entry.size > 1024 ? `${(entry.size / 1024).toFixed(1)} KB` : `${entry.size} B`}
                      </span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right: File Preview & Inspection */}
        <div className="hidden md:flex flex-1 flex-col h-full bg-[var(--bg-canvas)] overflow-hidden">
          {selectedFile ? (
            <div className="flex-1 flex flex-col h-full overflow-hidden">
              {/* File Info Bar */}
              <div className="px-5 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] flex items-center justify-between select-none">
                <div className="flex items-center space-x-2 truncate">
                  <Eye className="w-4 h-4 text-[#ea580c] shrink-0" />
                  <span className="font-mono text-xs font-semibold text-[var(--text-primary)] truncate">
                    {selectedFile.rel_path}
                  </span>
                </div>
                {fileContent && (
                  <button
                    type="button"
                    onClick={handleCopyContent}
                    className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-xs bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)] text-[var(--text-primary)] border border-[var(--border-subtle)] transition-colors cursor-pointer"
                  >
                    {isCopied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5 text-[var(--text-muted)]" />}
                    <span>{isCopied ? 'Copied' : 'Copy'}</span>
                  </button>
                )}
              </div>

              {/* Code / Content Viewer */}
              <div className="flex-1 overflow-auto p-4 font-mono text-xs text-[var(--text-primary)] leading-relaxed select-text">
                {isLoadingContent ? (
                  <div className="py-20 text-center text-[var(--text-muted)] flex flex-col items-center justify-center space-y-2">
                    <RefreshCw className="w-5 h-5 animate-spin text-[#ea580c]" />
                    <span>Loading file content...</span>
                  </div>
                ) : (
                  <pre className="whitespace-pre-wrap font-mono p-4 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)]">
                    {fileContent || '(Select a file to inspect its contents)'}
                  </pre>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-8 select-none text-[var(--text-muted)] space-y-2">
              <File className="w-10 h-10 stroke-[1.5] text-[var(--text-muted)] opacity-50" />
              <p className="text-sm font-medium">Select a file from the explorer to preview</p>
              <p className="text-xs max-w-sm">
                Files are resolved through Go 81 sovereign sandbox boundaries with complete directory traversal protections.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

