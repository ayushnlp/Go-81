'use client';

import React, { useEffect, useState } from 'react';
import { ShieldCheck, Clock, Server, RefreshCw } from 'lucide-react';
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
  const [timeStr, setTimeStr] = useState<string>('');

  useEffect(() => {
    const update = () => {
      setTimeStr(
        new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      );
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="h-16 border-b border-[#E8E6DF] bg-[#FAF9F5]/85 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-30">
      <div>
        <h1 className="text-base font-bold text-zinc-950 flex items-center gap-2 tracking-tight">
          {title}
        </h1>
        {subtitle && <p className="text-xs text-zinc-500">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-3">
        {/* Local Clock */}
        <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white border border-[#E5E3DC] text-xs font-mono text-zinc-600 shadow-2xs">
          <Clock className="w-3.5 h-3.5 text-zinc-400" />
          <span suppressHydrationWarning>{timeStr || '--:--:--'}</span>
        </div>

        {/* Shield Wall Status */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 font-medium">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
          <span className="font-semibold hidden md:inline">Shield-Wall</span>
          <span className="font-mono text-[10px] bg-emerald-100 text-emerald-900 px-1 py-0.5 rounded font-bold">
            LOCAL-ONLY
          </span>
        </div>

        {/* Backend Connection Badge & Probe */}
        <div className="flex items-center gap-1.5">
          <Badge
            variant={isBackendOnline ? 'emerald' : 'amber'}
            dot
            className="font-mono text-[11px] font-semibold"
          >
            <Server className="w-3 h-3 mr-0.5" />
            {isBackendOnline ? 'API :8000 LIVE' : 'API OFFLINE'}
          </Badge>

          {onRefreshBackend && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onRefreshBackend}
              loading={isChecking}
              aria-label="Probe backend"
              className="p-1 h-7 w-7 text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/50 rounded-md"
            >
              <RefreshCw className={`w-3 h-3 ${isChecking ? 'animate-spin' : ''}`} />
            </Button>
          )}
        </div>
      </div>
    </header>
  );
};
