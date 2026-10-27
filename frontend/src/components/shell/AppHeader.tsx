'use client';

import React, { useEffect, useState } from 'react';
import {
  ShieldCheck,
  Clock,
  Server,
  RefreshCw,
} from 'lucide-react';

import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

interface AppHeaderProps {
  title: string;
  subtitle?: string;
  isBackendOnline?: boolean;
  onRefreshBackend?: () => void;
  isChecking?: boolean;
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  title,
  subtitle,
  isBackendOnline = false,
  onRefreshBackend,
  isChecking = false,
}) => {
  const [timeStr, setTimeStr] = useState('');

  useEffect(() => {
    const updateTime = () => {
      setTimeStr(
        new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      );
    };

    updateTime();

    const interval = window.setInterval(updateTime, 1000);

    return () => window.clearInterval(interval);
  }, []);

  return (
    <header className="relative z-10 w-full border-b border-[#E4E9F1] bg-white/90 text-[#152033] backdrop-blur-xl">
      <div className="flex min-h-[76px] flex-col justify-center gap-3 px-4 py-3 sm:px-6 md:flex-row md:items-center md:justify-between md:gap-5 lg:px-8">

        {/* Page title */}
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-lg font-bold tracking-[-0.04em] text-[#14213D] sm:text-xl">
            {title}
          </h1>

          {subtitle && (
            <p className="mt-1 max-w-2xl text-xs leading-5 text-[#667085] sm:text-sm">
              {subtitle}
            </p>
          )}
        </div>

        {/* Runtime information */}
        <div className="flex flex-wrap items-center gap-2 sm:gap-2.5">

          {/* Local clock */}
          <div className="hidden items-center gap-2 rounded-xl border border-[#E4E9F1] bg-[#F7F9FC] px-3 py-2 text-xs text-[#667085] sm:flex">
            <Clock
              aria-hidden="true"
              className="h-3.5 w-3.5 text-[#8792A5]"
            />

            <span
              className="font-mono tabular-nums"
              suppressHydrationWarning
            >
              {timeStr || '--:--:--'}
            </span>
          </div>

          {/* Local privacy indicator */}
          <div
            className="inline-flex items-center gap-2 rounded-xl border border-[#D8E9E1] bg-[#F0FAF5] px-3 py-2 text-xs text-[#176548]"
            title="Local-first runtime status"
          >
            <ShieldCheck
              aria-hidden="true"
              className="h-4 w-4 shrink-0 text-[#07845D]"
            />

            <span className="hidden font-semibold sm:inline">
              Shield-Wall
            </span>

            <span className="rounded-md border border-[#D8E9E1] bg-white px-1.5 py-0.5 text-[9px] font-bold tracking-wide text-[#176548]">
              LOCAL
            </span>
          </div>

          {/* Backend status and refresh */}
          <div className="flex items-center gap-1.5">
            <div aria-live="polite" aria-atomic="true">
              <Badge
                variant={isBackendOnline ? 'emerald' : 'amber'}
                dot
                className={[
                  'whitespace-nowrap rounded-xl border px-2.5 py-2 text-[10px] font-semibold sm:px-3 sm:text-[11px]',
                  isBackendOnline
                    ? 'border-[#D8E9E1] bg-[#F0FAF5] text-[#176548]'
                    : 'border-[#F4D8A5] bg-[#FFF7E9] text-[#92540A]',
                ].join(' ')}
              >
                <Server
                  aria-hidden="true"
                  className="mr-1 inline h-3.5 w-3.5"
                />

                {isBackendOnline ? 'API LIVE' : 'API OFFLINE'}
              </Badge>
            </div>

            {onRefreshBackend && (
              <Button
                size="sm"
                variant="ghost"
                onClick={onRefreshBackend}
                loading={isChecking}
                disabled={isChecking}
                aria-label="Refresh backend connection status"
                title="Check backend connection"
                className="h-9 w-9 rounded-xl border border-transparent p-0 text-[#667085] transition-colors hover:border-[#E4E9F1] hover:bg-[#F1F5FB] hover:text-[#14213D]"
              >
                <RefreshCw
                  aria-hidden="true"
                  className={`h-4 w-4 ${isChecking ? 'animate-spin' : ''
                    }`}
                />
              </Button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};