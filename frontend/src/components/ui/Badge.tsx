import React from 'react';

export type BadgeVariant = 'emerald' | 'amber' | 'sky' | 'rose' | 'zinc' | 'purple' | 'yellow';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  dot?: boolean;
  className?: string;
}

const variantStyles: Record<BadgeVariant, { bg: string; text: string; border: string; dot: string }> = {
  emerald: {
    bg: 'bg-emerald-50',
    text: 'text-emerald-800',
    border: 'border-emerald-200',
    dot: 'bg-emerald-600',
  },
  amber: {
    bg: 'bg-amber-50',
    text: 'text-amber-800',
    border: 'border-amber-200',
    dot: 'bg-amber-600',
  },
  yellow: {
    bg: 'bg-yellow-100',
    text: 'text-yellow-900',
    border: 'border-yellow-300',
    dot: 'bg-yellow-500',
  },
  sky: {
    bg: 'bg-sky-50',
    text: 'text-sky-800',
    border: 'border-sky-200',
    dot: 'bg-sky-600',
  },
  rose: {
    bg: 'bg-rose-50',
    text: 'text-rose-800',
    border: 'border-rose-200',
    dot: 'bg-rose-600',
  },
  zinc: {
    bg: 'bg-zinc-100',
    text: 'text-zinc-800',
    border: 'border-zinc-200',
    dot: 'bg-zinc-500',
  },
  purple: {
    bg: 'bg-purple-50',
    text: 'text-purple-800',
    border: 'border-purple-200',
    dot: 'bg-purple-600',
  },
};

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'zinc',
  dot = false,
  className = '',
}) => {
  const styles = variantStyles[variant];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${styles.bg} ${styles.text} ${styles.border} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`} />}
      {children}
    </span>
  );
};
