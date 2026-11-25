import React, { useState } from 'react';
import { Tabs } from '../components/common/LoadingSpinner';
import { useAuth } from '../context/AuthContext';
import { AdminManagementPage } from './AdminManagementPage';
import { SecurityMfaPage } from './SecurityMfaPage';
import { ScreenAuditLog } from './ScreenAuditLog';

type Tab = 'admins' | 'mfa' | 'audit';

export const AdminsSecurityPage: React.FC = () => {
  const { aalLevel } = useAuth();
  const needsMfa = aalLevel !== 'aal2';
  // Without MFA nothing else here works, so open on the two-factor tab.
  const [tab, setTab] = useState<Tab>(needsMfa ? 'mfa' : 'admins');

  return (
    <div className="space-y-5">
      <Tabs
        label="Admins and security"
        active={tab}
        onChange={(id) => setTab(id as Tab)}
        tabs={[
          { id: 'admins', label: 'Administrators' },
          { id: 'mfa', label: 'Two-factor sign-in', badge: needsMfa ? '!' : undefined },
          { id: 'audit', label: 'Screen-view log' },
        ]}
      />
      {tab === 'admins' && <AdminManagementPage />}
      {tab === 'mfa' && <SecurityMfaPage />}
      {tab === 'audit' && <ScreenAuditLog />}
    </div>
  );
};
