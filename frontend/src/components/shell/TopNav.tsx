'use client';

import React from 'react';
import {
  Search,
  Sun,
  Moon,
  Columns2,
  Terminal,
  ShieldCheck,
  AlertCircle,
  Cpu,
  RefreshCw,
} from 'lucide-react';
import { AudienceMode, AppearancePreset, AgentRuntimeStatus, ModelHealth } from '@/lib/api/types';

interface TopNavProps {
  mode: AudienceMode;
  onModeChange: (mode: AudienceMode) => void;
  theme: AppearancePreset;
  onThemeToggle: () => void;
  isBackendOnline: boolean;
  modelHealth: ModelHealth | null;
  runtimeStatus: AgentRuntimeStatus | null;
  isChecking: boolean;
  onRefreshHealth: () => void;
  onOpenCommandPalette: () => void;
  isCompanionOpen: boolean;
  onToggleCompanion: () => void;
  isDockOpen: boolean;
  onToggleDock: () => void;
}

export const TopNav: React.FC<TopNavProps> = ({
  mode,
  onModeChange,
  theme,
  onThemeToggle,
  isBackendOnline,
  modelHealth,
  runtimeStatus,
  isChecking,
  onRefreshHealth,
  onOpenCommandPalette,
  isCompanionOpen,
  onToggleCompanion,
  isDockOpen,
  onToggleDock,
}) => {
  const isMac = typeof window !== 'undefined' && navigator.platform?.toUpperCase().indexOf('MAC') >= 0;
  const shortcutHint = isMac ? '⌘K' : 'Ctrl+K';

  const isModelOnline = modelHealth?.loaded || (isBackendOnline && runtimeStatus?.ollamaStatus === 'connected');
  const modelName = modelHealth?.model || runtimeStatus?.model || 'llama3.2:3b';

  return (
    <header className="h-12 w-full border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 flex items-center justify-between select-none z-30 shrink-0">
      {/* Left: Brand, Local-First badge, Repo info */}
      <div className="flex items-center space-x-3 shrink-0">
        <div className="flex items-center space-x-2">
          {/* Logo Mark */}
          <div className="w-7 h-7 rounded-md bg-[#ea580c] flex items-center justify-center shadow-xs">
            <span className="text-white font-black text-xs tracking-tighter">81</span>
          </div>
          <span className="font-semibold text-sm tracking-tight text-[var(--text-primary)]">
            Go 81
          </span>
        </div>

        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium tracking-wide uppercase bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)]">
          LOCAL-FIRST
        </span>

        <div className="hidden md:flex items-center space-x-1.5 text-xs text-[var(--text-muted)] border-l border-[var(--border-subtle)] pl-3">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
          <span className="font-mono text-[11px] text-[var(--text-secondary)] truncate max-w-[140px]">
            go-81 (main)
          </span>
        </div>
      </div>

      {/* Center: Global Search & Command Palette Trigger */}
      <div className="flex-1 max-w-md mx-4">
        <button
          type="button"
          onClick={onOpenCommandPalette}
          className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-md bg-[var(--bg-canvas)] border border-[var(--border-subtle)] hover:border-[var(--border-medium)] transition-colors text-xs text-[var(--text-muted)] group cursor-pointer"
        >
          <div className="flex items-center space-x-2 truncate">
            <Search className="w-3.5 h-3.5 text-[var(--text-muted)] group-hover:text-[var(--text-secondary)]" />
            <span className="truncate">Search files or actions...</span>
          </div>
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
            {shortcutHint}
          </kbd>
        </button>
      </div>

      {/* Right: Mode Switcher, Connection Pills, Dock/Companion Toggles, Theme */}
      <div className="flex items-center space-x-2 shrink-0">
        {/* Connection status pills */}
        <div className="hidden lg:flex items-center space-x-1.5">
          {/* FastAPI backend health */}
          <button
            type="button"
            onClick={onRefreshHealth}
            title={isBackendOnline ? `FastAPI backend connected (${isChecking ? 'checking...' : 'click to probe'})` : 'FastAPI offline. Click to retry'}
            className={`inline-flex items-center space-x-1.5 px-2 py-1 rounded text-[11px] font-mono border transition-colors cursor-pointer ${
              isBackendOnline
                ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/15'
                : 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20 hover:bg-rose-500/15'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${isBackendOnline ? 'bg-emerald-500' : 'bg-rose-500'} ${isChecking ? 'animate-ping' : ''}`} />
            <span>FastAPI</span>
            {isChecking && <RefreshCw className="w-2.5 h-2.5 animate-spin ml-0.5" />}
          </button>

          {/* Ollama local model health */}
          <div
            title={isModelOnline ? `Model: ${modelName} active` : 'Local Ollama model offline'}
            className={`inline-flex items-center space-x-1 px-2 py-1 rounded text-[11px] font-mono border ${
              isModelOnline
                ? 'bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/25'
                : 'bg-[var(--bg-elevated)] text-[var(--text-muted)] border-[var(--border-subtle)]'
            }`}
          >
            <Cpu className="w-3 h-3" />
            <span className="truncate max-w-[90px]">{modelName}</span>
          </div>
        </div>

        {/* User / Developer Mode Segmented Toggle */}
        <div className="flex items-center bg-[var(--bg-canvas)] p-0.5 rounded-md border border-[var(--border-subtle)]">
          <button
            type="button"
            onClick={() => onModeChange('user')}
            className={`px-2 py-1 rounded text-xs font-medium transition-all cursor-pointer ${
              mode === 'user'
                ? 'bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-xs'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            User
          </button>
          <button
            type="button"
            onClick={() => onModeChange('developer')}
            className={`px-2 py-1 rounded text-xs font-medium transition-all cursor-pointer ${
              mode === 'developer'
                ? 'bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-xs'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            Dev
          </button>
        </div>

        {/* Theme Toggle (Dark / Light) */}
        <button
          type="button"
          onClick={onThemeToggle}
          title={`Switch to ${theme === 'dark' || theme === 'oled-dark' ? 'Light' : 'Dark'} theme`}
          className="p-1.5 rounded-md text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] border border-[var(--border-subtle)] transition-colors cursor-pointer"
        >
          {theme === 'dark' || theme === 'oled-dark' ? (
            <Sun className="w-4 h-4 text-amber-400" />
          ) : (
            <Moon className="w-4 h-4 text-slate-700" />
          )}
        </button>

        {/* Developer Dock Toggle */}
        <button
          type="button"
          onClick={onToggleDock}
          title={isDockOpen ? 'Collapse Developer Dock' : 'Open Developer Dock'}
          className={`p-1.5 rounded-md border transition-colors cursor-pointer ${
            isDockOpen
              ? 'bg-[var(--accent-primary-bg)] text-[var(--accent-primary)] border-[var(--accent-primary-border)]'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] border-[var(--border-subtle)]'
          }`}
        >
          <Terminal className="w-4 h-4" />
        </button>

        {/* Split View / Agent Companion Toggle */}
        <button
          type="button"
          onClick={onToggleCompanion}
          title={isCompanionOpen ? 'Hide Agent Companion' : 'Open Agent Companion (Split View)'}
          className={`p-1.5 rounded-md border transition-colors cursor-pointer ${
            isCompanionOpen
              ? 'bg-[var(--accent-primary-bg)] text-[var(--accent-primary)] border-[var(--accent-primary-border)]'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] border-[var(--border-subtle)]'
          }`}
        >
          <Columns2 className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};

