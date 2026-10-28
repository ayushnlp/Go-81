'use client';

import React from 'react';

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
}) => {
  return (
    <header className="relative z-10 w-full border-b border-[#E4E9F1] bg-white/70 py-2 sm:py-2.5 px-4 text-[#152033] backdrop-blur-md">
      <div className="mx-auto max-w-4xl text-center">
        <h1 className="text-[15px] sm:text-[17px] font-bold tracking-tight text-[#14213D]">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-0.5 text-[11px] sm:text-[12px] text-[#667085] font-medium leading-relaxed max-w-2xl mx-auto">
            {subtitle}
          </p>
        )}
      </div>
    </header>
  );
};