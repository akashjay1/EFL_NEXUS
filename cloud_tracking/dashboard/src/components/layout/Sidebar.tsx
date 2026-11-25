import React from 'react';
import {
  LayoutGrid,
  Laptop,
  History,
  ClipboardCheck,
  ShieldCheck,
  Settings,
  LogOut,
  ShieldAlert,
  X,
} from 'lucide-react';
import { NavigationTab } from '../../types';
import { useAuth } from '../../context/AuthContext';

interface SidebarProps {
  activeTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  isConnected: boolean;
  deviceCount?: number;
  isMobileOpen?: boolean;
  onCloseMobile?: () => void;
}

type NavItem = { id: NavigationTab; label: string; icon: React.ComponentType<{ className?: string }>; count?: number; warn?: boolean };

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onSelectTab,
  isConnected,
  deviceCount,
  isMobileOpen = false,
  onCloseMobile,
}) => {
  const { adminProfile, aalLevel, signOut } = useAuth();
  const needsMfa = aalLevel !== 'aal2';

  const monitor: NavItem[] = [
    { id: 'overview', label: 'Overview', icon: LayoutGrid },
    { id: 'devices', label: 'Devices', icon: Laptop, count: deviceCount },
    { id: 'sessions', label: 'Sessions & activity', icon: History },
    { id: 'reconciliation', label: 'Reconciliation jobs', icon: ClipboardCheck },
  ];
  const manage: NavItem[] = [
    { id: 'admins', label: 'Admins & security', icon: ShieldCheck, warn: needsMfa },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  const email = adminProfile?.email || 'Administrator';
  const initials = email.slice(0, 2).toUpperCase();

  const renderItem = (item: NavItem) => {
    const Icon = item.icon;
    const isActive = activeTab === item.id;
    return (
      <li key={item.id}>
        <button
          onClick={() => {
            onSelectTab(item.id);
            onCloseMobile?.();
          }}
          aria-current={isActive ? 'page' : undefined}
          className={`w-full flex items-center gap-3 min-h-11 px-3 rounded-xl text-sm font-medium transition-colors ${
            isActive ? 'bg-accent-soft text-accent-strong font-semibold' : 'text-ink-2 hover:bg-canvas'
          }`}
        >
          <Icon className={`w-[18px] h-[18px] shrink-0 ${isActive ? 'text-accent' : 'text-slate-500'}`} />
          <span className="flex-1 text-left truncate">{item.label}</span>
          {item.count !== undefined && (
            <span className="rounded-full bg-[#eef2ff] px-2 text-xs font-semibold text-[#3730a3] tabular-nums">{item.count}</span>
          )}
          {item.warn && (
            <span className="rounded-full bg-[#fef3c7] px-2 text-[11px] font-bold text-[#92400e]">MFA</span>
          )}
        </button>
      </li>
    );
  };

  return (
    <>
      {isMobileOpen && (
        <div className="fixed inset-0 bg-[#101828]/40 z-30 lg:hidden" onClick={onCloseMobile} aria-hidden="true" />
      )}
      <aside
        className={`fixed top-0 left-0 z-40 h-screen w-64 bg-surface border-r border-line flex flex-col transition-transform duration-200 ${
          isMobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
        aria-label="Main navigation"
      >
        <div className="flex items-center gap-3 h-16 px-5">
          <div className="w-9 h-9 rounded-xl bg-accent flex items-center justify-center font-display font-bold text-white text-sm">
            NX
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-display font-bold text-[15px] text-ink leading-tight">EFL NEXUS</p>
            <p className="text-xs text-muted">Admin console</p>
          </div>
          {onCloseMobile && (
            <button onClick={onCloseMobile} aria-label="Close menu" className="lg:hidden p-2 rounded-lg text-muted hover:bg-canvas">
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto px-3 pt-3">
          <p className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">Monitor</p>
          <ul className="space-y-0.5">{monitor.map(renderItem)}</ul>
          <p className="px-3 pt-5 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">Manage</p>
          <ul className="space-y-0.5">{manage.map(renderItem)}</ul>

          {needsMfa && (
            <button
              onClick={() => {
                onSelectTab('admins');
                onCloseMobile?.();
              }}
              className="mt-5 w-full text-left rounded-xl border border-[#fedf89] bg-[#fffaeb] p-3 text-xs text-[#93370d] flex gap-2 hover:bg-[#fef0c7]"
            >
              <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
              <span>Turn on two-factor sign-in to manage devices and view screens.</span>
            </button>
          )}
        </nav>

        <div className="border-t border-line p-4 space-y-3">
          <div className="flex items-center gap-2 px-1 text-xs text-muted">
            <span aria-hidden="true" className={`w-2 h-2 rounded-full ${isConnected ? 'bg-[#16a34a]' : 'bg-[#f04438]'}`} />
            {isConnected ? 'Connected to cloud' : 'Cloud connection lost'}
          </div>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-[#e0e7ff] text-[#3730a3] flex items-center justify-center text-xs font-bold shrink-0">
              {initials}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-ink truncate">{email}</p>
              <p className={`text-xs ${needsMfa ? 'text-amber-400' : 'text-emerald-400'}`}>
                <span className="capitalize">{adminProfile?.role ?? 'admin'}</span> · {needsMfa ? 'MFA needed' : 'MFA verified'}
              </p>
            </div>
            <button
              onClick={() => signOut()}
              className="p-2 rounded-lg text-muted hover:text-red-400 hover:bg-canvas"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
};
