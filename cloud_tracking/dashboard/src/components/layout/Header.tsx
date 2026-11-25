import React from 'react';
import { RefreshCw, Menu } from 'lucide-react';
import { NavigationTab } from '../../types';

interface HeaderProps {
  activeTab: NavigationTab;
  onRefresh: () => void;
  isRefreshing: boolean;
  lastUpdated: Date;
  isConnected?: boolean;
  onOpenMobile?: () => void;
}

export const PAGE_TITLES: Record<NavigationTab, { title: string; subtitle: string }> = {
  overview: { title: 'Overview', subtitle: 'Live view of every EFL NEXUS workstation' },
  devices: { title: 'Devices', subtitle: 'Add, inspect and revoke workstations' },
  sessions: { title: 'Sessions & activity', subtitle: 'What happened on each workstation, in order' },
  reconciliation: { title: 'Reconciliation jobs', subtitle: 'Job assignments from User KPI and their latest portal status' },
  admins: { title: 'Admins & security', subtitle: 'Who can use this console, two-factor sign-in, and every screen view' },
  settings: { title: 'Settings', subtitle: 'Refresh rate, timing rules and cloud diagnostics' },
};

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  onRefresh,
  isRefreshing,
  lastUpdated,
  isConnected = true,
  onOpenMobile,
}) => {
  const current = PAGE_TITLES[activeTab] ?? PAGE_TITLES.overview;

  return (
    <header className="px-4 sm:px-6 lg:px-8 pt-6 pb-2 flex flex-wrap items-end justify-between gap-4">
      <div className="flex items-start gap-3 min-w-0">
        {onOpenMobile && (
          <button
            onClick={onOpenMobile}
            className="lg:hidden mt-0.5 p-2 -ml-2 rounded-lg text-muted hover:bg-surface"
            aria-label="Open navigation menu"
          >
            <Menu className="w-5 h-5" />
          </button>
        )}
        <div className="min-w-0">
          <h1 className="text-2xl sm:text-[28px] font-bold text-ink leading-tight">{current.title}</h1>
          <p className="text-sm text-muted mt-1">{current.subtitle}</p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
            isConnected ? 'bg-[#ecfdf3] text-[#067647]' : 'bg-[#fee4e2] text-[#b42318]'
          }`}
        >
          <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-[#12b76a]' : 'bg-[#f04438]'}`} />
          {isConnected ? 'Live' : 'Offline'} · {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
        <button onClick={onRefresh} disabled={isRefreshing} className="btn" aria-label="Refresh now" title="Refresh now">
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-accent' : ''}`} />
        </button>
      </div>
    </header>
  );
};
