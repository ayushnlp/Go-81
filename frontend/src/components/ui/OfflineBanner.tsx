import React from 'react';

interface OfflineBannerProps {
  isLive?: boolean;
  isChecking?: boolean;
  onRetry?: () => void;
  backendUrl?: string;
}

export const OfflineBanner: React.FC<OfflineBannerProps> = () => {
  // Banner removed per user instruction. All runtime status is unified in top AppSidebar.
  return null;
};
