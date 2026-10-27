'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Terminal,
  Activity,
  Database,
  Wrench,
  ShieldCheck,
  Radio,
} from 'lucide-react';
import { Badge } from '../ui/Badge';

interface NavItem {
  name: string;
  href: string;
  icon: React.ElementType;
}

const navItems: NavItem[] = [
  {
    name: 'Command Center',
    href: '/',
    icon: Terminal,
  },
  {
    name: 'Task Timeline',
    href: '/tasks',
    icon: Activity,
  },
  {
    name: 'Memory Vault',
    href: '/memory',
    icon: Database,
  },
  {
    name: 'Skills Forge',
    href: '/skills',
    icon: Wrench,
  },
  {
    name: 'Privacy & Control',
    href: '/settings',
    icon: ShieldCheck,
  },
];

interface AppSidebarProps {
  pendingApprovalsCount?: number;
  ollamaStatus?: 'connected' | 'disconnected' | 'degraded';
}

export const AppSidebar: React.FC<AppSidebarProps> = ({
  pendingApprovalsCount = 0,
  ollamaStatus = 'disconnected',
}) => {
  const pathname = usePathname();

  const statusConfig = {
    connected: {
      label: 'Ollama connected',
      dot: 'bg-emerald-500',
      text: 'text-emerald-700',
      background: 'bg-emerald-50',
      border: 'border-emerald-200',
    },
    disconnected: {
      label: 'Ollama offline',
      dot: 'bg-red-500',
      text: 'text-red-700',
      background: 'bg-red-50',
      border: 'border-red-200',
    },
    degraded: {
      label: 'Ollama degraded',
      dot: 'bg-amber-500',
      text: 'text-amber-700',
      background: 'bg-amber-50',
      border: 'border-amber-200',
    },
  } as const;

  const status =
    (ollamaStatus && statusConfig[ollamaStatus as keyof typeof statusConfig]) ||
    statusConfig.disconnected;

  return (
    <header className="sticky top-0 z-50 w-full border-b border-[#E4E9F1] bg-white/95 text-[#152033] backdrop-blur-xl">
      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-3 px-4 py-3 sm:px-6 md:flex-row md:items-center md:gap-5 lg:px-8">

        {/* Brand */}
        <div className="flex min-w-0 items-center justify-between gap-3 md:shrink-0">
          <Link
            href="/"
            aria-label="Go 81 home"
            className="group flex shrink-0 items-center gap-3 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#3563F7]"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#14213D] text-sm font-extrabold tracking-tight text-white shadow-sm transition-colors group-hover:bg-[#22375C]">
              81
            </span>

            <span className="flex flex-col leading-tight">
              <span className="flex items-center gap-2">
                <span className="text-[15px] font-bold tracking-[-0.04em] text-[#14213D]">
                  Go 81
                </span>

                <span className="rounded-md border border-[#E4E9F1] bg-[#F7F9FC] px-1.5 py-0.5 text-[10px] font-medium text-[#667085]">
                  v0.9
                </span>
              </span>

              <span className="mt-1 text-[11px] font-medium tracking-wide text-[#8792A5]">
                Personal AI Workspace
              </span>
            </span>
          </Link>

          {/* Status for mobile */}
          <span
            role="status"
            className={`inline-flex items-center gap-1.5 text-[11px] font-medium md:hidden ${status.text}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
            {status.label}
          </span>
        </div>

        {/* Main navigation */}
        <nav
          aria-label="Main navigation"
          className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto pb-1 md:justify-center md:pb-0"
          style={{ scrollbarWidth: 'none' }}
        >
          {navItems.map((item) => {
            const isActive =
              item.href === '/'
                ? pathname === '/'
                : pathname === item.href ||
                pathname.startsWith(`${item.href}/`);

            const Icon = item.icon;
            const isTaskRoute = item.href === '/tasks';

            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? 'page' : undefined}
                className={[
                  'relative inline-flex min-h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-xl px-3 py-2 text-[12px] font-medium transition-colors duration-150',
                  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#3563F7]',
                  isActive
                    ? 'bg-[#EAF0FF] text-[#14213D]'
                    : 'text-[#667085] hover:bg-[#F1F5FB] hover:text-[#14213D]',
                ].join(' ')}
              >
                <Icon
                  aria-hidden="true"
                  className={`h-4 w-4 shrink-0 ${isActive ? 'text-[#3563F7]' : 'text-[#8792A5]'
                    }`}
                  strokeWidth={isActive ? 2.2 : 1.8}
                />

                <span>{item.name}</span>

                {isTaskRoute && pendingApprovalsCount > 0 && (
                  <Badge
                    variant="amber"
                    className="ml-0.5 border border-[#F4D8A5] bg-[#FFF5E5] px-1.5 py-0.5 text-[10px] font-semibold text-[#92540A]"
                  >
                    {pendingApprovalsCount}
                  </Badge>
                )}
              </Link>
            );
          })}
        </nav>

        {/* Runtime status for desktop */}
        <div className="hidden shrink-0 items-center gap-2 md:flex">
          <span
            role="status"
            className={`inline-flex items-center gap-1.5 text-xs font-medium ${status.text}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
            {status.label}
          </span>
        </div>
      </div>
    </header>
  );
};