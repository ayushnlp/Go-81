import React from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger' | 'accent';
export type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-zinc-950 hover:bg-zinc-800 text-white shadow-sm active:translate-y-px border border-zinc-900 font-semibold',
  secondary:
    'bg-white hover:bg-zinc-50 text-zinc-900 border border-zinc-200/90 shadow-xs active:translate-y-px',
  outline:
    'bg-transparent hover:bg-zinc-100 text-zinc-800 border border-zinc-300 active:translate-y-px',
  ghost:
    'bg-transparent hover:bg-zinc-150 text-zinc-600 hover:text-zinc-950 border border-transparent',
  danger:
    'bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 active:translate-y-px',
  accent:
    'bg-yellow-400 hover:bg-yellow-300 text-zinc-950 font-semibold shadow-xs border border-yellow-500/30 active:translate-y-px',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1 text-xs gap-1.5',
  md: 'px-3.5 py-1.5 text-sm gap-2',
  lg: 'px-4 py-2.5 text-base gap-2.5',
};

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  className = '',
  disabled,
  ...props
}) => {
  return (
    <button
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center font-medium rounded-lg transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
      {...props}
    >
      {loading ? (
        <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin mr-1" />
      ) : (
        icon && <span className="shrink-0">{icon}</span>
      )}
      <span>{children}</span>
    </button>
  );
};
