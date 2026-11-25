import React, { useState } from 'react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { NavigationTab } from '../../types';

interface LayoutProps {
  children: React.ReactNode;
  activeTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  lastUpdated: Date;
  isConnected: boolean;
  deviceCount?: number;
}

export const Layout: React.FC<LayoutProps> = ({
  children,
  activeTab,
  onSelectTab,
  onRefresh,
  isRefreshing,
  lastUpdated,
  isConnected,
  deviceCount,
}) => {
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <Sidebar
        activeTab={activeTab}
        onSelectTab={onSelectTab}
        isConnected={isConnected}
        deviceCount={deviceCount}
        isMobileOpen={isMobileOpen}
        onCloseMobile={() => setIsMobileOpen(false)}
      />

      <div className="lg:pl-64 flex flex-col min-h-screen">
        <Header
          activeTab={activeTab}
          onRefresh={onRefresh}
          isRefreshing={isRefreshing}
          lastUpdated={lastUpdated}
          isConnected={isConnected}
          onOpenMobile={() => setIsMobileOpen(true)}
        />
        <main className="flex-1 w-full max-w-[1440px] px-4 sm:px-6 lg:px-8 pt-4 pb-12">{children}</main>
      </div>
    </div>
  );
};
