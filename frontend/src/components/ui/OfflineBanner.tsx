import React from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react';
import { Button } from './Button';

interface OfflineBannerProps {
  isLive: boolean;
  isChecking?: boolean;
  onRetry?: () => void;
  backendUrl?: string;
}

export const OfflineBanner: React.FC<OfflineBannerProps> = ({
  isLive,
  isChecking = false,
  onRetry,
  backendUrl = 'http://127.0.0.1:8000',
}) => {
  if (isLive) {
    return (
      <div className="w-full bg-emerald-950/20 border-b border-emerald-800/30 px-4 py-2 flex items-center justify-between text-xs text-emerald-300">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          <span>
            Connected to Sovereign Local FastAPI Backend at <code className="font-mono text-emerald-200">{backendUrl}</code>
          </span>
        </div>
        <span className="text-[11px] text-emerald-400/80">Local Inference Active (Ollama)</span>
      </div>
    );
  }

  return (
    <aside aria-label="Backend status banner" className="w-full bg-amber-950/30 border-b border-amber-800/40 px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs text-amber-200">
      <div className="flex items-center gap-2.5">
        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
        <div>
          <span className="font-medium text-amber-100">
            Offline Staging Preview Active:
          </span>{' '}
          <span className="text-amber-300/90">
            FastAPI server at <code className="font-mono bg-black/40 px-1 py-0.5 rounded text-amber-200">{backendUrl}</code> is currently offline or starting up.
          </span>{' '}
          <span className="text-zinc-400 text-[11px] block sm:inline">
            (Displaying isolated demonstration fixtures so the interface can be audited. No real external actions are dispatched.)
          </span>
        </div>
      </div>
      {onRetry && (
        <Button
          size="sm"
          variant="outline"
          onClick={onRetry}
          loading={isChecking}
          icon={<RefreshCw className={`w-3 h-3 ${isChecking ? 'animate-spin' : ''}`} />}
          className="text-xs py-1 border-amber-700/60 hover:bg-amber-900/40 text-amber-100"
        >
          Check Connection
        </Button>
      )}
    </aside>
  );
};
