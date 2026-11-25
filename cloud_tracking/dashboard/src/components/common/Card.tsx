import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  children,
  className = '',
  bodyClassName = 'p-5',
  title,
  subtitle,
  action,
  icon,
}) => {
  return (
    <section className={`bg-surface border border-line rounded-2xl shadow-[0_1px_2px_rgba(16,24,40,0.04)] ${className}`}>
      {(title || action || icon) && (
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5 pb-4 border-b border-line">
          <div className="flex items-center gap-3 min-w-0">
            {icon && <div className="text-accent shrink-0">{icon}</div>}
            <div className="min-w-0">
              {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
              {subtitle && <p className="text-sm text-muted mt-0.5">{subtitle}</p>}
            </div>
          </div>
          {action && <div className="flex items-center gap-2">{action}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
};

export const MetricCard: React.FC<{
  title: string;
  value: number | string;
  subtitle?: string;
  icon?: React.ReactNode;
  color?: 'blue' | 'green' | 'amber' | 'red' | 'purple';
  trend?: string;
}> = ({ title, value, subtitle, color = 'blue', trend }) => {
  const dot = {
    blue: 'bg-[#2563eb]',
    green: 'bg-[#16a34a]',
    amber: 'bg-[#d97706]',
    red: 'bg-[#f04438]',
    purple: 'bg-[#7c3aed]',
  }[color];

  return (
    <div className="bg-surface border border-line rounded-2xl px-5 py-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className={`w-2 h-2 rounded-full ${dot}`} />
        <p className="text-sm font-medium text-muted">{title}</p>
      </div>
      <div className="flex items-baseline gap-2 mt-2">
        <span className="font-display text-3xl font-bold tracking-tight text-ink tabular-nums">{value}</span>
        {trend && <span className="text-xs text-emerald-400 font-medium">{trend}</span>}
      </div>
      {subtitle && <p className="text-xs text-muted mt-1">{subtitle}</p>}
    </div>
  );
};
