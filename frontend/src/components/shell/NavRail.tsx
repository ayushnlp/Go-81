'use client';

import React from 'react';
import {
  Home,
  FolderTree,
  Search,
  GitBranch,
  AlertTriangle,
  History,
  Server,
  Database,
  Wrench,
  Settings,
} from 'lucide-react';

export type NavDestination =
  | 'home'
  | 'explorer'
  | 'search'
  | 'git'
  | 'problems'
  | 'activity'
  | 'environment'
  | 'memory'
  | 'skills'
  | 'settings';

interface NavRailProps {
  activeTab: NavDestination;
  onSelectTab: (tab: NavDestination) => void;
  pendingApprovalsCount?: number;
  problemsCount?: number;
}

interface NavItemDef {
  id: NavDestination;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: number;
}

const mainNavItems: NavItemDef[] = [
  { id: 'home', label: 'Command Center', icon: Home },
  { id: 'explorer', label: 'File Explorer', icon: FolderTree },
  { id: 'search', label: 'Global Search', icon: Search },
  { id: 'git', label: 'Source Control & Changes', icon: GitBranch },
  { id: 'activity', label: 'Activity History & Checkpoints', icon: History },
  { id: 'problems', label: 'Problems & Diagnostics', icon: AlertTriangle },
  { id: 'environment', label: 'System Environment', icon: Server },
  { id: 'memory', label: 'Encrypted Memory Vault', icon: Database },
  { id: 'skills', label: 'Skills Forge', icon: Wrench },
];

export const NavRail: React.FC<NavRailProps> = ({
  activeTab,
  onSelectTab,
  pendingApprovalsCount = 0,
  problemsCount = 0,
}) => {
  return (
    <aside
      aria-label="Application Navigation Rail"
      className="w-13 border-r border-[var(--border-subtle)] bg-[var(--bg-surface)] flex flex-col items-center justify-between py-2 shrink-0 select-none z-20"
    >
      {/* Top Main Navigation Group */}
      <div className="flex flex-col items-center space-y-1 w-full px-1">
        {mainNavItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          const badgeCount =
            item.id === 'problems'
              ? problemsCount + pendingApprovalsCount
              : item.id === 'skills'
              ? pendingApprovalsCount
              : 0;

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelectTab(item.id)}
              title={item.label}
              className={`relative w-10 h-10 rounded-lg flex items-center justify-center transition-all group cursor-pointer ${
                isActive
                  ? 'bg-[var(--accent-primary-bg)] text-[var(--accent-primary)] font-medium shadow-2xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]'
              }`}
            >
              {/* Left Active Indicator Bar */}
              {isActive && (
                <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r bg-[#ea580c]" />
              )}

              <Icon className="w-4.5 h-4.5 transition-transform duration-150 group-hover:scale-105" />

              {/* Badge for Pending Items or Errors */}
              {badgeCount > 0 && (
                <span className="absolute top-1 right-1 min-w-[14px] h-[14px] px-0.5 rounded-full bg-[#ea580c] text-white text-[9px] font-bold flex items-center justify-center">
                  {badgeCount > 9 ? '9+' : badgeCount}
                </span>
              )}

              {/* Tooltip on hover */}
              <span className="absolute left-13 px-2 py-1 rounded bg-[var(--bg-elevated)] text-[var(--text-primary)] border border-[var(--border-subtle)] text-xs font-normal whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity duration-150 shadow-md z-50">
                {item.label}
              </span>
            </button>
          );
        })}
      </div>

      {/* Bottom Pinned Controls: Settings */}
      <div className="flex flex-col items-center space-y-1 w-full px-1 pt-2 border-t border-[var(--border-subtle)]">
        <button
          type="button"
          onClick={() => onSelectTab('settings')}
          title="Settings & Privacy Controls"
          className={`relative w-10 h-10 rounded-lg flex items-center justify-center transition-all group cursor-pointer ${
            activeTab === 'settings'
              ? 'bg-[var(--accent-primary-bg)] text-[var(--accent-primary)] shadow-2xs'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]'
          }`}
        >
          {activeTab === 'settings' && (
            <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r bg-[#ea580c]" />
          )}
          <Settings className="w-4.5 h-4.5 transition-transform duration-150 group-hover:scale-105" />
          <span className="absolute left-13 px-2 py-1 rounded bg-[var(--bg-elevated)] text-[var(--text-primary)] border border-[var(--border-subtle)] text-xs font-normal whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity duration-150 shadow-md z-50">
            Settings & Privacy
          </span>
        </button>
      </div>
    </aside>
  );
};

