'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  Search,
  Plus,
  FolderTree,
  History,
  ShieldAlert,
  Server,
  Database,
  Wrench,
  Settings,
  Sun,
  Moon,
  Laptop,
  CheckCircle,
} from 'lucide-react';
import { AudienceMode, AppearancePreset } from '@/lib/api/types';
import { NavDestination } from './NavRail';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectNav: (tab: NavDestination) => void;
  mode: AudienceMode;
  onToggleMode: (mode: AudienceMode) => void;
  theme: AppearancePreset;
  onToggleTheme: () => void;
  onNewRequest: () => void;
  onSaveCheckpoint: () => void;
  onRunDiagnostics: () => void;
}

interface CommandItem {
  id: string;
  title: string;
  category: 'Navigation' | 'Actions' | 'Preferences';
  icon: React.ComponentType<{ className?: string }>;
  action: () => void;
  shortcut?: string;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onSelectNav,
  mode,
  onToggleMode,
  theme,
  onToggleTheme,
  onNewRequest,
  onSaveCheckpoint,
  onRunDiagnostics,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands: CommandItem[] = [
    {
      id: 'action-new',
      title: 'New Request / Reset Workspace',
      category: 'Actions',
      icon: Plus,
      action: () => {
        onNewRequest();
        onSelectNav('home');
      },
    },
    {
      id: 'action-save-checkpoint',
      title: 'Save Project Checkpoint',
      category: 'Actions',
      icon: CheckCircle,
      action: () => {
        onSaveCheckpoint();
        onSelectNav('activity');
      },
    },
    {
      id: 'action-run-diag',
      title: 'Run System Diagnostics',
      category: 'Actions',
      icon: Server,
      action: () => {
        onRunDiagnostics();
        onSelectNav('environment');
      },
    },
    {
      id: 'nav-home',
      title: 'Go to Command Center (Home)',
      category: 'Navigation',
      icon: Laptop,
      action: () => onSelectNav('home'),
    },
    {
      id: 'nav-explorer',
      title: 'Open File Explorer',
      category: 'Navigation',
      icon: FolderTree,
      action: () => onSelectNav('explorer'),
    },
    {
      id: 'nav-activity',
      title: 'Open Activity History & Checkpoints',
      category: 'Navigation',
      icon: History,
      action: () => onSelectNav('activity'),
    },
    {
      id: 'nav-problems',
      title: 'Open Problems & Diagnostics',
      category: 'Navigation',
      icon: ShieldAlert,
      action: () => onSelectNav('problems'),
    },
    {
      id: 'nav-env',
      title: 'Open System Environment',
      category: 'Navigation',
      icon: Server,
      action: () => onSelectNav('environment'),
    },
    {
      id: 'nav-memory',
      title: 'Open Encrypted Memory Vault',
      category: 'Navigation',
      icon: Database,
      action: () => onSelectNav('memory'),
    },
    {
      id: 'nav-skills',
      title: 'Open Skills Forge',
      category: 'Navigation',
      icon: Wrench,
      action: () => onSelectNav('skills'),
    },
    {
      id: 'nav-settings',
      title: 'Open Settings & Privacy Controls',
      category: 'Navigation',
      icon: Settings,
      action: () => onSelectNav('settings'),
    },
    {
      id: 'pref-mode',
      title: `Switch to ${mode === 'user' ? 'Developer' : 'User'} Mode`,
      category: 'Preferences',
      icon: Laptop,
      action: () => onToggleMode(mode === 'user' ? 'developer' : 'user'),
    },
    {
      id: 'pref-theme',
      title: `Switch to ${theme === 'dark' || theme === 'oled-dark' ? 'Light' : 'Dark'} Theme`,
      category: 'Preferences',
      icon: theme === 'dark' || theme === 'oled-dark' ? Sun : Moon,
      action: onToggleTheme,
    },
  ];

  const filtered = commands.filter((c) =>
    c.title.toLowerCase().includes(query.toLowerCase()) ||
    c.category.toLowerCase().includes(query.toLowerCase())
  );

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQuery('');
    }
  }, [isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1 < filtered.length ? prev + 1 : 0));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 >= 0 ? prev - 1 : filtered.length - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filtered[selectedIndex]) {
          filtered[selectedIndex].action();
          onClose();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, filtered, selectedIndex, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-start justify-center pt-20 p-4 animate-in fade-in duration-100">
      <div
        className="w-full max-w-xl rounded-xl border border-[var(--border-medium)] bg-[var(--bg-surface)] shadow-2xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Bar */}
        <div className="flex items-center px-3.5 py-3 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
          <Search className="w-4 h-4 text-[var(--text-muted)] mr-2.5 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command or search actions..."
            className="w-full bg-transparent text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none"
          />
          <kbd className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-muted)]">
            ESC
          </kbd>
        </div>

        {/* Command List */}
        <div className="max-h-80 overflow-y-auto p-1.5 space-y-0.5">
          {filtered.length === 0 ? (
            <div className="py-8 text-center text-xs text-[var(--text-muted)]">
              No matching actions found for &ldquo;{query}&rdquo;
            </div>
          ) : (
            filtered.map((item, idx) => {
              const Icon = item.icon;
              const isSelected = idx === selectedIndex;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    item.action();
                    onClose();
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs transition-colors cursor-pointer text-left ${
                    isSelected
                      ? 'bg-[var(--accent-primary-bg)] text-[var(--accent-primary)] font-medium'
                      : 'text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]'
                  }`}
                >
                  <div className="flex items-center space-x-2.5 truncate">
                    <Icon className={`w-4 h-4 shrink-0 ${isSelected ? 'text-[var(--accent-primary)]' : 'text-[var(--text-muted)]'}`} />
                    <span className="truncate">{item.title}</span>
                  </div>
                  <span className="text-[10px] text-[var(--text-muted)] font-mono ml-2 shrink-0">
                    {item.category}
                  </span>
                </button>
              );
            })
          )}
        </div>

        {/* Footer Navigation Hints */}
        <div className="px-3.5 py-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] flex items-center justify-between text-[11px] text-[var(--text-muted)]">
          <div className="flex items-center space-x-2">
            <span>↑↓ Navigate</span>
            <span>•</span>
            <span>↵ Select</span>
            <span>•</span>
            <span>ESC Close</span>
          </div>
          <span className="text-[10px] font-mono">Go 81 Sovereign Agent</span>
        </div>
      </div>

      {/* Backdrop click to close */}
      <div className="fixed inset-0 -z-10" onClick={onClose} />
    </div>
  );
};

