import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { OverviewPage } from '../src/pages/OverviewPage';
import { WorkstationBoard } from '../src/components/operators/WorkstationBoard';
import { ActivityEventsPage } from '../src/pages/ActivityEventsPage';
import { LoginPage } from '../src/pages/LoginPage';
import { DevicesPage } from '../src/pages/DevicesPage';
import { SessionHistoryPage } from '../src/pages/SessionHistoryPage';
import { Session, Device, SnapshotData, SessionEvent } from '../src/types';
import * as AuthContextModule from '../src/context/AuthContext';

describe('dashboard page tests', () => {
  const baseTime = Date.parse('2026-11-02T12:00:00Z');

  const mockDevices: Device[] = [
    {
      id: 'dev-1',
      installation_uuid: '11111111-1111-1111-1111-111111111111',
      device_name: 'OFFICE-PC-01',
      created_at: '2026-11-02T08:00:00Z',
      revoked_at: null,
    },
    {
      id: 'dev-2',
      installation_uuid: '22222222-2222-2222-2222-222222222222',
      device_name: 'WAREHOUSE-PC-02',
      created_at: '2026-11-02T08:30:00Z',
      revoked_at: null,
    },
    {
      id: 'dev-3',
      installation_uuid: '33333333-3333-3333-3333-333333333333',
      device_name: 'RETIRED-PC-99',
      created_at: '2026-10-01T08:00:00Z',
      revoked_at: '2026-10-15T08:00:00Z',
    },
  ];

  const mockSessions: Session[] = [
    {
      id: 'sess-1',
      device_id: 'dev-1',
      credential_id: 'cred-1',
      device_name_snapshot: 'OFFICE-PC-01',
      operator_name_snapshot: 'Sarah Jenkins',
      operator_name: 'Sarah Jenkins',
      identity_source: 'KPI Profile',
      app_version: '3.12.0',
      active_module: 'Air Export',
      started_at: '2026-11-02T10:00:00Z',
      received_at: '2026-11-02T10:00:00Z',
      last_event_at: '2026-11-02T11:59:50Z',
      last_seen_at: '2026-11-02T11:59:50Z',
      idle_seconds: 15,
      ended_at: null,
      end_reason: null,
      end_is_estimated: false,
      event_sequence: 120,
      live_sequence: 120,
      disconnected_at: null,
      status: 'active',
    },
    {
      id: 'sess-2',
      device_id: 'dev-2',
      credential_id: 'cred-2',
      device_name_snapshot: 'WAREHOUSE-PC-02',
      operator_name_snapshot: 'WAREHOUSE-PC-02',
      operator_name: 'WAREHOUSE-PC-02',
      identity_source: 'Device Fallback',
      app_version: '3.12.0',
      active_module: 'Ocean Import',
      started_at: '2026-11-02T09:30:00Z',
      received_at: '2026-11-02T09:30:00Z',
      last_event_at: '2026-11-02T11:50:00Z',
      last_seen_at: '2026-11-02T11:50:00Z',
      idle_seconds: 600,
      ended_at: null,
      end_reason: null,
      end_is_estimated: false,
      event_sequence: 85,
      live_sequence: 85,
      disconnected_at: null,
      status: 'idle',
    },
  ];

  const mockSnapshot: SnapshotData = {
    server_time: '2026-11-02T12:00:00Z',
    settings: {
      id: true,
      heartbeat_seconds: 60,
      disconnected_seconds: 180,
      idle_seconds: 300,
      dashboard_refresh_seconds: 15,
      history_days: 90,
    },
    devices: mockDevices,
    sessions: [
      {
        id: 'sess-1',
        device_id: 'dev-1',
        device_name_snapshot: 'OFFICE-PC-01',
        active_module: 'Air Export',
        app_version: '3.12.0',
        started_at: '2026-11-02T10:00:00Z',
        last_seen_at: '2026-11-02T11:59:50Z',
        idle_seconds: 15,
        operator_name: 'Sarah Jenkins',
        identity_source: 'KPI Profile',
        status: 'online',
      },
    ],
  };

  const mockEvents: SessionEvent[] = [
    {
      id: 'evt-1',
      session_id: 'sess-1',
      sequence: 1,
      event_type: 'started',
      event_timestamp: '2026-11-02T10:00:00Z',
      received_at: '2026-11-02T10:00:00Z',
      metadata: { module: 'Air Export' },
    },
    {
      id: 'evt-2',
      session_id: 'sess-1',
      sequence: 2,
      event_type: 'module_changed',
      event_timestamp: '2026-11-02T10:15:00Z',
      received_at: '2026-11-02T10:15:00Z',
      metadata: { from_module: 'Air Export', to_module: 'Ocean Import' },
    },
  ];

  describe('OverviewPage', () => {
    it('calculates metrics and renders metric cards and operator table', () => {
      const handleNavigate = vi.fn();
      render(
        <OverviewPage
          snapshot={mockSnapshot}
          activeSessions={mockSessions}
          recentEvents={mockEvents}
          onNavigate={handleNavigate}
        />
      );

      // Active operators count is 1 (sess-1 is active, sess-2 is idle)
      expect(screen.getByText('Active now')).toBeDefined();
      expect(screen.getByText('Enrolled devices')).toBeDefined();
      expect(screen.getByText('Workstations')).toBeDefined();

      // Verified operator name (workstation card + activity feed)
      expect(screen.getAllByText('Sarah Jenkins').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/started a session/)).toBeDefined();
      // Fallback operator name / device name
      expect(screen.getAllByText('WAREHOUSE-PC-02').length).toBeGreaterThanOrEqual(1);

      // KPI Profile and Device Fallback badges
      expect(screen.getByText('KPI Profile')).toBeDefined();
      expect(screen.getByText('Device Fallback')).toBeDefined();

      // Navigation button
      fireEvent.click(screen.getByRole('button', { name: /all activity/i }));
      expect(handleNavigate).toHaveBeenCalledWith('sessions');
    });
  });

  describe('WorkstationBoard', () => {
    it('renders operators and supports filtering by search query and module', () => {
      render(<WorkstationBoard sessions={mockSessions} />);

      expect(screen.getByText('Sarah Jenkins')).toBeDefined();
      expect(screen.getAllByText('WAREHOUSE-PC-02').length).toBeGreaterThanOrEqual(1);

      // Search filter for Sarah
      const searchInput = screen.getByPlaceholderText(/search by operator, device, or module/i);
      fireEvent.change(searchInput, { target: { value: 'Sarah' } });

      expect(screen.getByText('Sarah Jenkins')).toBeDefined();
      expect(screen.queryByText('WAREHOUSE-PC-02')).toBeNull();

      // Clear search
      fireEvent.change(searchInput, { target: { value: '' } });
      expect(screen.getAllByText('WAREHOUSE-PC-02').length).toBeGreaterThanOrEqual(1);
    });

    it('opens session inspection modal upon clicking inspect action', () => {
      render(<WorkstationBoard sessions={mockSessions} />);

      const inspectBtns = screen.getAllByTitle(/inspect session/i);
      expect(inspectBtns.length).toBeGreaterThan(0);
      fireEvent.click(inspectBtns[0]);

      expect(screen.getByText(/Session Details: Sarah Jenkins/i)).toBeDefined();
      expect(screen.getByText(/Session ID: sess-1/i)).toBeDefined();
    });
  });

  describe('ActivityEventsPage', () => {
    it('renders event telemetry stream and supports filtering', () => {
      render(<ActivityEventsPage events={mockEvents} />);

      expect(screen.getAllByText('STARTED').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('MODULE_CHANGED').length).toBeGreaterThanOrEqual(1);

      // Search filter for module_changed
      const searchInput = screen.getByPlaceholderText(/filter by event payload/i);
      fireEvent.change(searchInput, { target: { value: 'Ocean Import' } });

      // Table body only contains MODULE_CHANGED, STARTED option in select might remain
      const rows = screen.getAllByRole('row');
      // 1 header row + 1 matching data row = 2 rows
      expect(rows.length).toBe(2);
      expect(screen.getAllByText('MODULE_CHANGED').length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('LoginPage', () => {
    it('shows error if submitted without email and password', async () => {
      vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
        user: null,
        session: null,
        adminProfile: null,
        aalLevel: null,
        nextAalLevel: null,
        hasMfaFactors: false,
        isLoading: false,
        error: null,
        signIn: vi.fn(),
        signOut: vi.fn(),
        verifyMfaChallenge: vi.fn(),
        refreshAuthStatus: vi.fn(),
      });

      const { container } = render(<LoginPage />);

      const form = container.querySelector('form')!;
      fireEvent.submit(form);

      expect(await screen.findByText(/please enter both email and password/i)).toBeDefined();
    });

    it('calls signIn on submission and shows error message on failure', async () => {
      const mockSignIn = vi.fn().mockResolvedValue({
        success: false,
        error: 'Invalid login credentials',
      });

      vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
        user: null,
        session: null,
        adminProfile: null,
        aalLevel: null,
        nextAalLevel: null,
        hasMfaFactors: false,
        isLoading: false,
        error: null,
        signIn: mockSignIn,
        signOut: vi.fn(),
        verifyMfaChallenge: vi.fn(),
        refreshAuthStatus: vi.fn(),
      });

      render(<LoginPage />);

      const emailInput = screen.getByPlaceholderText('admin@company.com');
      const passInput = screen.getByPlaceholderText('••••••••••••');
      const submitBtn = screen.getByRole('button', { name: /sign in/i });

      fireEvent.change(emailInput, { target: { value: 'owner@eflnexus.com' } });
      fireEvent.change(passInput, { target: { value: 'WrongPassword123' } });
      fireEvent.click(submitBtn);

      expect(mockSignIn).toHaveBeenCalledWith('owner@eflnexus.com', 'WrongPassword123');
      expect(await screen.findByText('Invalid login credentials')).toBeDefined();
    });
  });

  describe('DevicesPage', () => {
    it('renders device list and handles search', () => {
      vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
        user: { id: 'u1', email: 'admin@company.com' } as any,
        session: {} as any,
        adminProfile: { user_id: 'u1', role: 'admin', slot: 1, created_at: '', revoked_at: null },
        aalLevel: 'aal2',
        nextAalLevel: 'aal2',
        hasMfaFactors: true,
        isLoading: false,
        error: null,
        signIn: vi.fn(),
        signOut: vi.fn(),
        verifyMfaChallenge: vi.fn(),
        refreshAuthStatus: vi.fn(),
      });

      render(
        <DevicesPage
          devices={mockDevices}
          sessions={mockSessions}
          onRefresh={vi.fn()}
          onNavigateToMfa={vi.fn()}
        />
      );

      expect(screen.getByText('OFFICE-PC-01')).toBeDefined();
      expect(screen.getAllByText('WAREHOUSE-PC-02').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('RETIRED-PC-99')).toBeDefined();
    });

    it('opens provision new device modal and enforces AAL2 verification', async () => {
      vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
        user: { id: 'u1', email: 'admin@company.com' } as any,
        session: {} as any,
        adminProfile: { user_id: 'u1', role: 'admin', slot: 1, created_at: '', revoked_at: null },
        aalLevel: 'aal1', // AAL1 only!
        nextAalLevel: 'aal2',
        hasMfaFactors: true,
        isLoading: false,
        error: null,
        signIn: vi.fn(),
        signOut: vi.fn(),
        verifyMfaChallenge: vi.fn(),
        refreshAuthStatus: vi.fn(),
      });

      render(
        <DevicesPage
          devices={mockDevices}
          sessions={mockSessions}
          onRefresh={vi.fn()}
          onNavigateToMfa={vi.fn()}
        />
      );

      const addBtn = screen.getByRole('button', { name: /add device/i });
      fireEvent.click(addBtn);

      expect(screen.getByText('Add a workstation')).toBeDefined();
      expect(screen.getByText(/Two-factor sign-in required/i)).toBeDefined();
    });
  });

  describe('SessionHistoryPage', () => {
    it('renders session list with audit metrics and outcome badges', () => {
      render(<SessionHistoryPage initialSessions={mockSessions} />);

      expect(screen.getByText(/Historical Sessions \(2\)/)).toBeDefined();
      expect(screen.getByText('Sarah Jenkins')).toBeDefined();
      expect(screen.getAllByText('OFFICE-PC-01').length).toBeGreaterThanOrEqual(1);
    });
  });
});
