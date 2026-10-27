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
  Cpu,
  Lock,
  Radio,
} from 'lucide-react';
import { Badge } from '../ui/Badge';

interface NavItem {
  name: string;
  href: string;
  icon: React.ElementType;
  badge?: string | number;
  badgeVariant?: 'amber' | 'emerald' | 'zinc';
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
    badge: '1 pending',
    badgeVariant: 'amber',
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
  pendingApprovalsCount = 1,
  ollamaStatus = 'connected',
}) => {
  const pathname = usePathname();

  return (
    <aside className="w-64 shrink-0 bg-[#0c0e14] border-r border-zinc-800/80 flex flex-col justify-between h-screen sticky top-0 z-40 select-none">
      {/* Top Header & Brand */}
      <div>
        <div className="px-5 py-5 border-b border-zinc-800/60 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-3 group">
            <div className="w-8 h-8 rounded-lg bg-emerald-950/80 border border-emerald-500/40 flex items-center justify-center text-emerald-400 group-hover:border-emerald-400/80 transition-colors">
              <span className="font-mono font-bold text-sm">81</span>
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-sm tracking-tight text-zinc-100">
                  GO 81
                </span>
                <span className="text-[10px] font-mono uppercase bg-zinc-800 text-zinc-300 px-1 py-0.2 rounded">
                  v0.9
                </span>
              </div>
              <p className="text-[11px] text-zinc-500 font-mono">
                Sovereign Agent Core
              </p>
            </div>
          </Link>
        </div>

        {/* Navigation Links */}
        <nav className="p-3 space-y-1">
          <div className="px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider text-zinc-500">
            Workspaces
          </div>
          {navItems.map((item) => {
            const isActive =
              item.href === '/'
                ? pathname === '/'
                : pathname.startsWith(item.href);
            const Icon = item.icon;

            const badgeValue =
              item.href === '/tasks' && pendingApprovalsCount > 0
                ? `${pendingApprovalsCount} gate`
                : item.badge;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-zinc-800/90 text-white shadow-xs border border-zinc-700/60 font-semibold'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-850/50 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon
                    className={`w-4 h-4 shrink-0 ${
                      isActive ? 'text-emerald-400' : 'text-zinc-400'
                    }`}
                  />
                  <span>{item.name}</span>
                </div>
                {badgeValue && (
                  <Badge
                    variant={item.badgeVariant || 'zinc'}
                    className="text-[10px] py-0 px-1.5"
                  >
                    {badgeValue}
                  </Badge>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Sovereign Runtime Status Card */}
      <div className="p-3 m-3 rounded-xl bg-[#12151D] border border-zinc-800/80 text-xs">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-mono text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
            <Radio className="w-3 h-3 text-emerald-400 animate-pulse" />
            Local Sentinel
          </span>
          <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800/50 px-1.5 py-0.5 rounded">
            SOVEREIGN
          </span>
        </div>

        <div className="space-y-1.5 text-[11px] text-zinc-400">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1">
              <Cpu className="w-3 h-3 text-zinc-500" /> Ollama Host
            </span>
            <span className="font-mono text-zinc-200">
              {ollamaStatus === 'connected' ? '127.0.0.1' : 'Offline'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1">
              <Lock className="w-3 h-3 text-zinc-500" /> Runes At Rest
            </span>
            <span className="font-mono text-emerald-400">AES-256</span>
          </div>

          <div className="flex items-center justify-between">
            <span>Outbound Leak</span>
            <span className="font-mono text-emerald-400">0 KB (Local)</span>
          </div>
        </div>

        <div className="mt-2.5 pt-2 border-t border-zinc-800/70 flex items-center justify-between text-[10px] text-zinc-500">
          <span>Model: llama3.2:3b</span>
          <span>&lt;30% CPU</span>
        </div>
      </div>
    </aside>
  );
};
