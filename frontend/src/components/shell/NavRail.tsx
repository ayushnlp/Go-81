'use client';

import React from 'react';

export type NavDestination =
  | 'home'
  | 'explorer'
  | 'search'
  | 'git'
  | 'activity'
  | 'problems'
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
}

// 1. Workspace Group
const workspaceItems: NavItemDef[] = [
  { id: 'home', label: 'Home' },
  { id: 'explorer', label: 'Explorer' },
  { id: 'search', label: 'Search' },
];

// 2. Development Group
const devItems: NavItemDef[] = [
  { id: 'git', label: 'Git & Changes' },
  { id: 'activity', label: 'Activity History' },
  { id: 'problems', label: 'Problems' },
  { id: 'environment', label: 'Environment' },
];

// 3. Knowledge Group
const knowledgeItems: NavItemDef[] = [
  { id: 'memory', label: 'Memory Vault' },
  { id: 'skills', label: 'Skills Forge' },
];

// 4. Bottom Group
const bottomItems: NavItemDef[] = [
  { id: 'settings', label: 'Settings' },
];

export const NavRail: React.FC<NavRailProps> = ({
  activeTab,
  onSelectTab,
  pendingApprovalsCount = 0,
  problemsCount = 0,
}) => {
  const renderItem = (item: NavItemDef) => {
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
        aria-current={isActive ? 'page' : undefined}
        className="w-full text-left h-[34px] pl-3.5 pr-2.5 rounded-md text-[14px] sm:text-[14.5px] transition-colors cursor-pointer flex items-center justify-between select-none hover:bg-black/[0.04] dark:hover:bg-white/[0.04]"
        style={{
          color: isActive ? 'var(--sidebar-text-active, #F4511E)' : 'var(--sidebar-text, #18181B)',
          fontWeight: isActive ? 600 : 500,
          opacity: 1,
        }}
      >
        <span
          className="truncate"
          style={{
            color: isActive ? 'var(--sidebar-text-active, #F4511E)' : 'var(--sidebar-text, #18181B)',
            fontWeight: isActive ? 600 : 500,
            opacity: 1,
          }}
        >
          {item.label}
        </span>
        <div className="flex items-center space-x-1.5 shrink-0 ml-1.5">
          {badgeCount > 0 && (
            <span className="text-[10px] font-bold px-1.5 py-0.2 rounded-full bg-[#F4511E] text-white">
              {badgeCount > 9 ? '9+' : badgeCount}
            </span>
          )}
          {isActive && (
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ backgroundColor: 'var(--sidebar-text-active, #F4511E)' }}
            />
          )}
        </div>
      </button>
    );
  };

  return (
    <aside
      aria-label="Application Navigation"
      className="w-[212px] min-w-[212px] max-w-[212px] border-r border-[var(--border-subtle)] bg-[var(--bg-sidebar)] flex flex-col justify-between py-3 px-2 shrink-0 select-none z-20 overflow-y-auto"
      style={{
        width: '212px',
        minWidth: '212px',
        maxWidth: '212px',
        backgroundColor: 'var(--bg-sidebar, #EEF0F3)',
        opacity: 1,
      }}
    >
      {/* Top and Middle Navigation Groups */}
      <div className="flex flex-col w-full space-y-0.5">
        {/* Workspace */}
        <div className="flex flex-col space-y-0.5 w-full">
          {workspaceItems.map(renderItem)}
        </div>

        {/* Separator */}
        <div className="my-1.5 border-t border-[var(--border-subtle)] opacity-60" />

        {/* Development */}
        <div className="flex flex-col space-y-0.5 w-full">
          {devItems.map(renderItem)}
        </div>

        {/* Separator */}
        <div className="my-1.5 border-t border-[var(--border-subtle)] opacity-60" />

        {/* Knowledge */}
        <div className="flex flex-col space-y-0.5 w-full">
          {knowledgeItems.map(renderItem)}
        </div>
      </div>

      {/* Bottom Pinned Group: Settings */}
      <div className="flex flex-col w-full pt-2 border-t border-[var(--border-subtle)] mt-auto">
        {bottomItems.map(renderItem)}
      </div>
    </aside>
  );
};
