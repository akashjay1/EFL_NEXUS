import React from 'react';
import { Loader2 } from 'lucide-react';

export const LoadingSpinner: React.FC<{ message?: string; className?: string }> = ({
  message = 'Loading monitoring data...',
  className = 'py-12',
}) => {
  return (
    <div role="status" className={`flex flex-col items-center justify-center gap-3 text-muted ${className}`}>
      <Loader2 className="w-7 h-7 text-accent animate-spin" aria-hidden="true" />
      {message && <p className="text-sm font-medium">{message}</p>}
    </div>
  );
};

export const EmptyState: React.FC<{ icon?: React.ReactNode; title: string; children?: React.ReactNode }> = ({
  icon,
  title,
  children,
}) => (
  <div className="text-center py-12 px-4">
    {icon && <div className="mx-auto mb-3 w-10 h-10 text-slate-600 flex items-center justify-center">{icon}</div>}
    <p className="text-sm font-semibold text-ink">{title}</p>
    {children && <p className="text-sm text-muted mt-1 max-w-sm mx-auto">{children}</p>}
  </div>
);

export const Tabs: React.FC<{
  tabs: { id: string; label: string; badge?: string | number }[];
  active: string;
  onChange: (id: string) => void;
  label: string;
}> = ({ tabs, active, onChange, label }) => (
  <div role="tablist" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-xl bg-[#eaecf0] p-1">
    {tabs.map((t) => {
      const selected = t.id === active;
      return (
        <button
          key={t.id}
          role="tab"
          aria-selected={selected}
          onClick={() => onChange(t.id)}
          className={`min-h-9 px-3.5 rounded-lg text-sm font-semibold transition-colors ${
            selected ? 'bg-surface text-ink shadow-[0_1px_2px_rgba(16,24,40,0.08)]' : 'text-muted hover:text-ink'
          }`}
        >
          {t.label}
          {t.badge !== undefined && (
            <span className="ml-2 rounded-full bg-[#fef3c7] px-1.5 text-[11px] font-bold text-[#92400e]">{t.badge}</span>
          )}
        </button>
      );
    })}
  </div>
);
