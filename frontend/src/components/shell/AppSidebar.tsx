'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { RefreshCw } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { api } from '@/lib/api/client';

interface NavItem {
  name: string;
  href: string;
}

const navItems: NavItem[] = [
  {
    name: 'Command Center',
    href: '/',
  },
  {
    name: 'Task Timeline',
    href: '/tasks',
  },
  {
    name: 'Memory Vault',
    href: '/memory',
  },
  {
    name: 'Skills Forge',
    href: '/skills',
  },
  {
    name: 'Privacy & Control',
    href: '/settings',
  },
];

interface AppSidebarProps {
  pendingApprovalsCount?: number;
  ollamaStatus?: 'connected' | 'disconnected' | 'degraded';
  isBackendOnline?: boolean;
  isInferenceActive?: boolean;
  onRefreshBackend?: () => void;
  isChecking?: boolean;
}

export const AppSidebar: React.FC<AppSidebarProps> = ({
  pendingApprovalsCount = 0,
  ollamaStatus: propOllamaStatus,
  isBackendOnline: propIsBackendOnline,
  isInferenceActive: propIsInferenceActive,
  onRefreshBackend: propOnRefreshBackend,
  isChecking: propIsChecking = false,
}) => {
  const pathname = usePathname();

  // Internal fallback probe so all pages (Settings, Tasks, Memory, etc.) get live status
  const [internalOnline, setInternalOnline] = useState<boolean | null>(null);
  const [internalOllamaStatus, setInternalOllamaStatus] = useState<
    'connected' | 'disconnected' | 'degraded'
  >('connected');
  const [internalChecking, setInternalChecking] = useState(false);

  const probe = async () => {
    setInternalChecking(true);
    try {
      const health = await api.checkHealth();
      setInternalOnline(health.online);
      const runtime = await api.getRuntimeStatus();
      if (runtime.data?.ollamaStatus) {
        setInternalOllamaStatus(runtime.data.ollamaStatus);
      }
    } catch {
      setInternalOnline(false);
      setInternalOllamaStatus('disconnected');
    } finally {
      setInternalChecking(false);
    }
  };

  useEffect(() => {
    if (propIsBackendOnline === undefined) {
      probe();
      const interval = window.setInterval(probe, 20000);
      return () => window.clearInterval(interval);
    }
  }, [propIsBackendOnline]);

  const isBackendOnline =
    propIsBackendOnline !== undefined
      ? propIsBackendOnline
      : (internalOnline ?? true);
  const ollamaStatus =
    propOllamaStatus ||
    internalOllamaStatus ||
    (isBackendOnline ? 'connected' : 'disconnected');
  const isChecking = propIsChecking || internalChecking;
  const onRefreshBackend = propOnRefreshBackend || probe;

  // Ollama status (displayed as "Connected" without the word "Ollama")
  const isConnected = isBackendOnline && ollamaStatus === 'connected';
  const isDegraded = isBackendOnline && ollamaStatus === 'degraded';
  const ollamaDotClass = isConnected
    ? 'bg-emerald-500'
    : isDegraded
    ? 'bg-amber-500'
    : 'bg-red-500';
  const ollamaTextClass = isConnected
    ? 'text-emerald-700'
    : isDegraded
    ? 'text-amber-700'
    : 'text-red-600';
  const ollamaLabel = isConnected
    ? 'Connected'
    : isDegraded
    ? 'Degraded'
    : 'Disconnected';

  // API Live status
  const apiDotClass = isBackendOnline ? 'bg-emerald-500' : 'bg-red-500';
  const apiTextClass = isBackendOnline ? 'text-emerald-700' : 'text-red-600';
  const apiLabel = isBackendOnline ? 'API Live' : 'API Offline';

  // Local Inference Active status
  const inferenceLive =
    propIsInferenceActive !== undefined
      ? propIsInferenceActive
      : isBackendOnline && isConnected;
  const inferenceDotClass = inferenceLive
    ? 'bg-emerald-500'
    : isBackendOnline
    ? 'bg-amber-500'
    : 'bg-red-500';
  const inferenceTextClass = inferenceLive
    ? 'text-emerald-700'
    : isBackendOnline
    ? 'text-amber-700'
    : 'text-zinc-500';
  const inferenceLabel = inferenceLive
    ? 'Local Inference Active'
    : isBackendOnline
    ? 'Local Inference Standby'
    : 'Local Inference Offline';

  return (
    <header className="sticky top-0 z-50 w-full border-b border-[#E4E9F1] bg-white/95 text-[#152033] backdrop-blur-xl">
      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-2.5 px-4 py-2.5 sm:px-6 md:flex-row md:items-center md:justify-between md:gap-4 lg:px-8">
        {/* Brand */}
        <div className="flex min-w-0 items-center justify-between gap-3 md:shrink-0">
          <Link
            href="/"
            aria-label="Go 81 home"
            className="group flex shrink-0 items-center gap-2 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#3563F7]"
          >
            <span className="flex flex-col leading-tight">
              <span className="flex items-center gap-2">
                <span className="text-[16px] font-bold tracking-[-0.03em] text-[#14213D] group-hover:text-[#22375C] transition-colors">
                  Go 81
                </span>

                <span className="rounded-md border border-[#E4E9F1] bg-[#F7F9FC] px-1.5 py-0.5 text-[10px] font-medium text-[#667085]">
                  v0.9
                </span>
              </span>

              <span className="mt-0.5 text-[11px] font-medium tracking-wide text-[#8792A5]">
                Personal AI Workspace
              </span>
            </span>
          </Link>
        </div>

        {/* Main navigation */}
        <nav
          aria-label="Main navigation"
          className="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-3 overflow-x-auto pb-1 md:justify-center md:pb-0"
          style={{ scrollbarWidth: 'none' }}
        >
          {navItems.map((item) => {
            const isActive =
              item.href === '/'
                ? pathname === '/'
                : pathname === item.href ||
                pathname.startsWith(`${item.href}/`);

            const isTaskRoute = item.href === '/tasks';

            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? 'page' : undefined}
                className={[
                  'relative inline-flex items-center gap-1.5 whitespace-nowrap px-2.5 py-1 text-[14px] sm:text-[15px] transition-colors duration-150',
                  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#3563F7]',
                  isActive
                    ? 'font-bold text-[#14213D]'
                    : 'font-medium text-[#667085] hover:text-[#14213D]',
                ].join(' ')}
              >
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

        {/* Combined Runtime Status Indicators on the same horizontal line */}
        <div className="flex shrink-0 items-center gap-2.5 sm:gap-3 text-[11px] font-medium">
          {/* Connected (Ollama connectivity without the word 'Ollama') */}
          <span className="inline-flex items-center gap-1.5" role="status">
            <span className={`h-1.5 w-1.5 rounded-full ${ollamaDotClass}`} />
            <span className={ollamaTextClass}>{ollamaLabel}</span>
          </span>

          <span className="text-[#D0D5DD] select-none" aria-hidden="true">·</span>

          {/* API Live */}
          <span className="inline-flex items-center gap-1.5" role="status">
            <span className={`h-1.5 w-1.5 rounded-full ${apiDotClass}`} />
            <span className={apiTextClass}>{apiLabel}</span>
          </span>

          <span className="text-[#D0D5DD] select-none" aria-hidden="true">·</span>

          {/* Local Inference Active */}
          <span className="inline-flex items-center gap-1.5" role="status">
            <span className={`h-1.5 w-1.5 rounded-full ${inferenceDotClass}`} />
            <span className={inferenceTextClass}>{inferenceLabel}</span>
          </span>

          {onRefreshBackend && (
            <button
              type="button"
              onClick={onRefreshBackend}
              disabled={isChecking}
              title="Recheck service health"
              aria-label="Refresh service health"
              className="inline-flex h-6 w-6 items-center justify-center rounded text-[#8792A5] hover:bg-[#F1F5FB] hover:text-[#14213D] disabled:opacity-50 transition-colors cursor-pointer"
            >
              <RefreshCw className={`h-3 w-3 ${isChecking ? 'animate-spin text-[#14213D]' : ''}`} />
            </button>
          )}
        </div>
      </div>
    </header>
  );
};