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
  ollamaStatus?: 'connected' | 'disconnected' | 'degraded';
  isInferenceActive?: boolean;
  centered?: boolean;
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  title,
  subtitle,
  isBackendOnline = false,
  onRefreshBackend,
  isChecking = false,
  ollamaStatus = 'connected',
  isInferenceActive,
  centered = false,
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

  // Ollama status config
  const isOllamaConnected = isBackendOnline && ollamaStatus === 'connected';
  const isOllamaDegraded = isBackendOnline && ollamaStatus === 'degraded';
  const ollamaDotClass = isOllamaConnected
    ? 'bg-emerald-500'
    : isOllamaDegraded
    ? 'bg-amber-500'
    : 'bg-red-500';
  const ollamaTextClass = isOllamaConnected
    ? 'text-emerald-700'
    : isOllamaDegraded
    ? 'text-amber-700'
    : 'text-red-600';
  const ollamaLabel = isOllamaConnected
    ? 'Ollama Connected'
    : isOllamaDegraded
    ? 'Ollama Degraded'
    : 'Ollama Offline';

  // API status config
  const apiDotClass = isBackendOnline ? 'bg-emerald-500' : 'bg-red-500';
  const apiTextClass = isBackendOnline ? 'text-emerald-700' : 'text-red-600';
  const apiLabel = isBackendOnline ? 'Local API Live' : 'Local API Offline';

  // Inference status config
  const inferenceLive =
    isInferenceActive !== undefined
      ? isInferenceActive
      : isBackendOnline && isOllamaConnected;
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

  if (centered) {
    return (
      <header className="relative z-10 w-full border-b border-[#E4E9F1] bg-white/80 text-[#152033] backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl flex-col items-center justify-center px-4 py-3 sm:px-6">
          {/* Consolidated Top Status Row */}
          <div className="flex flex-wrap items-center justify-center gap-3 sm:gap-4 text-[11px] font-medium text-[#667085]">
            {/* Ollama Status */}
            <span className="inline-flex items-center gap-1.5" role="status">
              <span className={`h-1.5 w-1.5 rounded-full ${ollamaDotClass}`} />
              <span className={ollamaTextClass}>{ollamaLabel}</span>
            </span>

            <span className="text-[#D0D5DD] select-none" aria-hidden="true">
              ·
            </span>

            {/* Local API Status */}
            <span className="inline-flex items-center gap-1.5" role="status">
              <span className={`h-1.5 w-1.5 rounded-full ${apiDotClass}`} />
              <span className={apiTextClass}>{apiLabel}</span>
            </span>

            <span className="text-[#D0D5DD] select-none" aria-hidden="true">
              ·
            </span>

            {/* Local Inference Status */}
            <span className="inline-flex items-center gap-1.5" role="status">
              <span className={`h-1.5 w-1.5 rounded-full ${inferenceDotClass}`} />
              <span className={inferenceTextClass}>{inferenceLabel}</span>
            </span>

            {/* Recheck Health Button */}
            {onRefreshBackend && (
              <button
                type="button"
                onClick={onRefreshBackend}
                disabled={isChecking}
                title="Recheck service health"
                aria-label="Refresh service health"
                className="ml-0.5 inline-flex h-5 w-5 items-center justify-center rounded text-[#8792A5] transition-colors hover:bg-[#F1F5FB] hover:text-[#14213D] disabled:opacity-50 cursor-pointer"
              >
                <RefreshCw
                  className={`h-3 w-3 ${isChecking ? 'animate-spin text-[#14213D]' : ''}`}
                />
              </button>
            )}
          </div>

          {/* Centered Command Center Heading Area */}
          <div className="mt-1.5 text-center">
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[#14213D]">
              {title}
            </h1>
            {subtitle && (
              <p className="mt-0.5 text-xs sm:text-sm font-medium text-[#4B5563]">
                {subtitle}
              </p>
            )}
          </div>
        </div>
      </header>
    );
  }

  return (
    <header className="relative z-10 w-full border-b border-[#E4E9F1] bg-white/90 text-[#152033] backdrop-blur-xl">
      <div className="flex min-h-[70px] flex-col justify-center gap-3 px-4 py-3 sm:px-6 md:flex-row md:items-center md:justify-between md:gap-5 lg:px-8">
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
          <div className="hidden items-center gap-2 rounded-xl border border-[#E4E9F1] bg-[#F7F9FC] px-3 py-1.5 text-xs text-[#667085] sm:flex">
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
            className="inline-flex items-center gap-2 rounded-xl border border-[#D8E9E1] bg-[#F0FAF5] px-3 py-1.5 text-xs text-[#176548]"
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
                  'whitespace-nowrap rounded-xl border px-2.5 py-1.5 text-[10px] font-semibold sm:px-3 sm:text-[11px]',
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
                className="h-8 w-8 rounded-xl border border-transparent p-0 text-[#667085] transition-colors hover:border-[#E4E9F1] hover:bg-[#F1F5FB] hover:text-[#14213D]"
              >
                <RefreshCw
                  aria-hidden="true"
                  className={`h-4 w-4 ${
                    isChecking ? 'animate-spin' : ''
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