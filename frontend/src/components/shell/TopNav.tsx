'use client';

import React from 'react';
import { Sun, Moon, Terminal, Columns2 } from 'lucide-react';
import { AudienceMode, AppearancePreset, AgentRuntimeStatus, ModelHealth } from '@/lib/api/types';
import { CenteredSearchBar } from './CenteredSearchBar';

export interface TopNavProps {
  mode: AudienceMode;
  onModeChange: (mode: AudienceMode) => void;
  theme: AppearancePreset;
  onThemeToggle: () => void;
  isBackendOnline: boolean;
  modelHealth?: ModelHealth | null;
  runtimeStatus?: AgentRuntimeStatus | null;
  isChecking?: boolean;
  onRefreshHealth?: () => void;
  onOpenCommandPalette: () => void;
  onNavigate?: (destination: string, query?: string) => void;
  isCompanionOpen?: boolean;
  onToggleCompanion?: () => void;
  isDockOpen?: boolean;
  onToggleDock?: () => void;
}

export const TopNav: React.FC<TopNavProps> = ({
  mode,
  onModeChange,
  theme,
  onThemeToggle,
  isBackendOnline,
  modelHealth,
  runtimeStatus,
  onRefreshHealth,
  onOpenCommandPalette,
  onNavigate,
  isCompanionOpen,
  onToggleCompanion,
  isDockOpen,
  onToggleDock,
}) => {
  const isDark = theme === 'dark' || theme === 'oled-dark';

  const isDegraded = isBackendOnline && (
    modelHealth?.status === 'degraded' ||
    runtimeStatus?.ollamaStatus === 'degraded' ||
    (modelHealth && !modelHealth.loaded)
  );

  const isHealthy = isBackendOnline && !isDegraded;
  const dotColor = isHealthy ? 'bg-emerald-500 animate-pulse' : 'bg-[#ea580c]';
  const tooltipText = isHealthy ? 'Backend Connected' : 'Backend Disconnected';

  return (
    <header className="relative h-12 w-full border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 flex items-center justify-between select-none z-30 shrink-0">
      {/* 1. Go 81 Branding - Clean Typography Only */}
      <div className="flex items-center shrink-0 z-10">
        <span className="font-bold text-[15px] sm:text-base tracking-tight text-[var(--text-primary)] select-none">
          Go 81
        </span>
      </div>

      {/* 2. Global Centered Search Bar - Mathematically Centered in Top Bar */}
      <div className="absolute inset-x-0 mx-auto w-full max-w-[420px] sm:max-w-[460px] px-4 pointer-events-none flex justify-center items-center z-20">
        <div className="pointer-events-auto w-full">
          <CenteredSearchBar
            onNavigate={(dest, query) => {
              if (onNavigate) {
                onNavigate(dest, query);
              } else {
                onOpenCommandPalette();
              }
            }}
          />
        </div>
      </div>

      {/* Right Controls: 3. Mode Switcher, Dock/Companion, 4. Theme Icon, 5. Backend Status Dot */}
      <div className="flex items-center space-x-4 shrink-0 z-10">
        {/* 3. User / Dev Mode Switch (Text-only directly on background) */}
        <div className="flex items-center space-x-3">
          <button
            type="button"
            onClick={() => onModeChange('user')}
            className={`text-xs transition-colors cursor-pointer focus:outline-none ${
              mode === 'user'
                ? 'font-medium text-[var(--text-primary)]'
                : 'font-normal text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
          >
            User
          </button>
          <button
            type="button"
            onClick={() => onModeChange('developer')}
            className={`text-xs transition-colors cursor-pointer focus:outline-none ${
              mode === 'developer'
                ? 'font-medium text-[var(--text-primary)]'
                : 'font-normal text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            }`}
          >
            Dev
          </button>
        </div>

        {/* Functional Terminal (Dock) Control */}
        {onToggleDock && (
          <button
            type="button"
            onClick={onToggleDock}
            aria-label={isDockOpen ? 'Collapse Developer Dock' : 'Open Developer Dock'}
            title={isDockOpen ? 'Collapse Developer Dock' : 'Open Developer Dock'}
            className={`p-1 transition-colors cursor-pointer flex items-center justify-center focus:outline-none ${
              isDockOpen ? 'text-[#ea580c]' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            <Terminal className="w-4 h-4" />
          </button>
        )}

        {/* Functional Split-View (Companion) Control */}
        {onToggleCompanion && (
          <button
            type="button"
            onClick={onToggleCompanion}
            aria-label={isCompanionOpen ? 'Hide Agent Companion' : 'Open Agent Companion'}
            title={isCompanionOpen ? 'Hide Agent Companion' : 'Open Agent Companion'}
            className={`p-1 transition-colors cursor-pointer flex items-center justify-center focus:outline-none ${
              isCompanionOpen ? 'text-[#ea580c]' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            <Columns2 className="w-4 h-4" />
          </button>
        )}

        {/* 4. Dark / Light Theme Icon (Clean icon, no container box or border) */}
        <button
          type="button"
          onClick={onThemeToggle}
          aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
          title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
          className="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors cursor-pointer flex items-center justify-center focus:outline-none"
        >
          {isDark ? (
            <Moon className="w-4 h-4 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors" />
          ) : (
            <Sun className="w-4 h-4 text-amber-500 hover:text-amber-600 transition-colors" />
          )}
        </button>

        {/* 5. Backend Connection Status Dot with animated tooltip */}
        <div className="relative group flex items-center justify-center">
          <button
            type="button"
            onClick={onRefreshHealth}
            aria-label={tooltipText}
            className="p-1.5 flex items-center justify-center cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-[#ea580c] rounded"
          >
            <span className={`w-2 h-2 rounded-full transition-all duration-300 ${dotColor}`} />
          </button>
          <div
            role="tooltip"
            className="pointer-events-none absolute right-0 top-full mt-2 z-50 whitespace-nowrap px-2.5 py-1 text-[11px] font-medium rounded-md bg-[var(--bg-elevated)] text-[var(--text-primary)] border border-[var(--border-subtle)] shadow-md opacity-0 scale-95 group-hover:opacity-100 group-hover:scale-100 group-focus-within:opacity-100 group-focus-within:scale-100 transition-all duration-150 ease-out origin-top-right"
          >
            {tooltipText}
          </div>
        </div>
      </div>
    </header>
  );
};
