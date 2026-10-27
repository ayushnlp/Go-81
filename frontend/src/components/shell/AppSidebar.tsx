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
    <aside className="w-64 shrink-0 bg-[#F4F3EE] border-r border-[#E5E3DC] flex flex-col justify-between h-screen sticky top-0 z-40 select-none text-zinc-900">
      {/* Top Header & Brand */}
      <div>
        <div className="px-5 py-5 border-b border-[#E8E6DF] flex items-center justify-between">
          <Link href="/" className="flex items-center gap-3 group">
            <div className="w-8 h-8 rounded-lg bg-yellow-400 border border-yellow-500/40 flex items-center justify-center text-zinc-950 font-black text-sm shadow-xs group-hover:bg-yellow-300 transition-colors">
              <span className="font-mono">81</span>
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-bold text-sm tracking-tight text-zinc-950">
                  GO 81
                </span>
                <span className="text-[10px] font-mono uppercase bg-zinc-200/80 text-zinc-700 font-semibold px-1 py-0.2 rounded border border-zinc-300/60">
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
          <div className="px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider text-zinc-400 font-semibold">
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
                className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs transition-all ${
                  isActive
                    ? 'bg-zinc-950 text-white shadow-xs font-semibold'
                    : 'text-zinc-600 hover:text-zinc-950 hover:bg-zinc-200/60 font-medium'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon
                    className={`w-4 h-4 shrink-0 ${
                      isActive ? 'text-yellow-400' : 'text-zinc-500'
                    }`}
                  />
                  <span>{item.name}</span>
                </div>
                {badgeValue && (
                  <Badge
                    variant={item.badgeVariant || 'zinc'}
                    className={`text-[10px] py-0 px-1.5 ${
                      isActive ? 'bg-zinc-800 text-yellow-300 border-zinc-700' : ''
                    }`}
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
      <div className="p-3.5 m-3 rounded-xl bg-white border border-[#E5E3DC] shadow-xs text-xs">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-mono text-zinc-700 uppercase tracking-wider font-semibold flex items-center gap-1.5">
            <Radio className="w-3 h-3 text-emerald-600 animate-pulse" />
            GO 81 LOCAL AGENT
          </span>
          <span className="text-[10px] font-mono text-emerald-800 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded font-bold">
            SOVEREIGN
          </span>
        </div>

        <div className="space-y-1.5 text-[11px] text-zinc-600">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1">
              <Cpu className="w-3 h-3 text-zinc-400" /> Ollama Host
            </span>
            <span className="font-mono text-zinc-900 font-medium">
              {ollamaStatus === 'connected' ? '127.0.0.1' : 'Offline'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1">
              <Lock className="w-3 h-3 text-zinc-400" /> Sealed Memory
            </span>
            <span className="font-mono text-emerald-700 font-semibold">AES-256</span>
          </div>

          <div className="flex items-center justify-between">
            <span>Outbound Leak</span>
            <span className="font-mono text-emerald-700 font-semibold">0 KB (Local)</span>
          </div>
        </div>

        <div className="mt-2.5 pt-2 border-t border-[#EAE8E2] flex items-center justify-between text-[10px] text-zinc-500 font-mono">
          <span>llama3.2:3b</span>
          <span>&lt;30% CPU</span>
        </div>
      </div>
    </aside>
  );
};
