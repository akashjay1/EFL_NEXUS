import React, { useEffect, useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { useMonitoringData } from './hooks/useMonitoringData';
import { LEGACY_TAB_MAP, NavigationTab } from './types';
import { Layout } from './components/layout/Layout';
import { LoadingSpinner } from './components/common/LoadingSpinner';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { DevicesPage } from './pages/DevicesPage';
import { SessionsAndActivityPage } from './pages/SessionsAndActivityPage';
import { AdminsSecurityPage } from './pages/AdminsSecurityPage';
import { SettingsPage } from './pages/SettingsPage';
import { ReconciliationJobsPage } from './pages/ReconciliationJobsPage';

const TABS: NavigationTab[] = ['overview', 'devices', 'sessions', 'reconciliation', 'admins', 'settings'];

/** Reads the hash route; old routes (#operators, #events, #mfa) land on their new page. */
export function tabFromHash(hash: string): NavigationTab {
  const key = hash.replace('#', '');
  if ((TABS as string[]).includes(key)) return key as NavigationTab;
  return LEGACY_TAB_MAP[key] ?? 'overview';
}

const DashboardContent: React.FC = () => {
  const { user, isLoading: isAuthLoading } = useAuth();
  const [activeTab, setActiveTab] = useState<NavigationTab>(() => tabFromHash(window.location.hash));
  const [refreshInterval, setRefreshInterval] = useState<number>(10);

  const handleTabChange = (tab: NavigationTab) => {
    setActiveTab(tab);
    window.location.hash = tab;
    window.scrollTo({ top: 0 });
  };

  useEffect(() => {
    const onHash = () => setActiveTab(tabFromHash(window.location.hash));
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const {
    snapshot,
    devices,
    activeSessions,
    recentEvents,
    sessionsTodayCount,
    isRefreshing,
    lastUpdated,
    isConnected,
    refreshAll,
  } = useMonitoringData(refreshInterval);

  if (isAuthLoading) {
    return (
      <div className="min-h-screen bg-canvas flex items-center justify-center">
        <LoadingSpinner message="Checking your sign-in…" />
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  const page = (() => {
    switch (activeTab) {
      case 'devices':
        return (
          <DevicesPage
            devices={devices}
            sessions={activeSessions}
            onRefresh={refreshAll}
            onNavigateToMfa={() => handleTabChange('admins')}
          />
        );
      case 'sessions':
        return <SessionsAndActivityPage sessions={activeSessions} events={recentEvents} />;
      case 'reconciliation':
        return <ReconciliationJobsPage refreshInterval={refreshInterval} refreshKey={lastUpdated.getTime()} />;
      case 'admins':
        return <AdminsSecurityPage />;
      case 'settings':
        return <SettingsPage refreshInterval={refreshInterval} onUpdateRefreshInterval={setRefreshInterval} />;
      case 'overview':
      default:
        return (
          <OverviewPage
            snapshot={snapshot}
            activeSessions={activeSessions}
            recentEvents={recentEvents}
            sessionsTodayCount={sessionsTodayCount}
            onNavigate={handleTabChange}
          />
        );
    }
  })();

  return (
    <Layout
      activeTab={activeTab}
      onSelectTab={handleTabChange}
      onRefresh={refreshAll}
      isRefreshing={isRefreshing}
      lastUpdated={lastUpdated}
      isConnected={isConnected}
      deviceCount={devices.length}
    >
      {page}
    </Layout>
  );
};

export const App: React.FC = () => (
  <AuthProvider>
    <DashboardContent />
  </AuthProvider>
);

export default App;
