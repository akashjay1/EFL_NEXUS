import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DevicesPage } from '../src/pages/DevicesPage';
import * as SupabaseLib from '../src/lib/supabase';
import * as AuthContextModule from '../src/context/AuthContext';
import { Device, Session } from '../src/types';

describe('Device Actions and Provisioning Validation (Unit / Mocked)', () => {
  const mockDevices: Device[] = [
    {
      id: 'device-uuid-1',
      installation_uuid: '11111111-2222-3333-4444-555555555555',
      device_name: 'DISPATCH-PC-01',
      created_at: '2026-11-02T08:00:00Z',
      revoked_at: null,
    },
  ];

  const mockSessions: Session[] = [];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('blocks device provisioning if the administrator is only at AAL1', async () => {
    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
      user: { id: 'admin-1', email: 'admin@company.com' } as any,
      session: {} as any,
      adminProfile: { user_id: 'admin-1', role: 'admin', slot: 1, created_at: '', revoked_at: null },
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

    const openModalBtn = screen.getByRole('button', { name: /add device/i });
    fireEvent.click(openModalBtn);

    // Modal opens but shows AAL2 warning instead of submission form
    expect(screen.getByText(/Two-factor sign-in required/i)).toBeDefined();
    expect(screen.queryByPlaceholderText('e.g. WH-DESKTOP-04')).toBeNull();
  });

  it('authorizes enrollment and generates compliant provisioning bundle when authenticated at AAL2', async () => {
    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
      user: { id: 'admin-1', email: 'admin@company.com' } as any,
      session: {} as any,
      adminProfile: { user_id: 'admin-1', role: 'admin', slot: 1, created_at: '', revoked_at: null },
      aalLevel: 'aal2', // AAL2 verified!
      nextAalLevel: 'aal2',
      hasMfaFactors: true,
      isLoading: false,
      error: null,
      signIn: vi.fn(),
      signOut: vi.fn(),
      verifyMfaChallenge: vi.fn(),
      refreshAuthStatus: vi.fn(),
    });

    const callAdminSpy = vi.spyOn(SupabaseLib, 'callAdminAction').mockResolvedValue({
      data: {
        enrollment_code: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
        expires_in_seconds: 600,
      },
    });

    render(
      <DevicesPage
        devices={mockDevices}
        sessions={mockSessions}
        onRefresh={vi.fn()}
        onNavigateToMfa={vi.fn()}
      />
    );

    const openModalBtn = screen.getByRole('button', { name: /add device/i });
    fireEvent.click(openModalBtn);

    // Fill form
    const deviceNameInput = screen.getByPlaceholderText('e.g. WH-OFFICE-PC-01');
    const uuidInput = screen.getByPlaceholderText('xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx');
    const submitBtn = screen.getByRole('button', { name: /create provisioning file/i });

    fireEvent.change(deviceNameInput, { target: { value: 'AIR-EXPORT-02' } });
    fireEvent.change(uuidInput, { target: { value: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(callAdminSpy).toHaveBeenCalledWith('create_enrollment', expect.objectContaining({
        device_name: 'AIR-EXPORT-02',
        installation_uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      }));
      expect(screen.getByText('Provisioning file ready')).toBeDefined();
      expect(screen.getByText(/Download provisioning.json/i)).toBeDefined();
    });
  });

  it('revokes device hardware via admin action when confirmed by an AAL2 administrator', async () => {
    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
      user: { id: 'admin-1', email: 'admin@company.com' } as any,
      session: {} as any,
      adminProfile: { user_id: 'admin-1', role: 'admin', slot: 1, created_at: '', revoked_at: null },
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

    const callAdminSpy = vi.spyOn(SupabaseLib, 'callAdminAction').mockResolvedValue({
      data: { success: true },
    });

    const onRefreshMock = vi.fn();

    render(
      <DevicesPage
        devices={mockDevices}
        sessions={mockSessions}
        onRefresh={onRefreshMock}
        onNavigateToMfa={vi.fn()}
      />
    );

    const revokeBtn = screen.getByTitle(/revoke device authorization/i);
    fireEvent.click(revokeBtn);

    expect(screen.getByText('Revoke DISPATCH-PC-01?')).toBeDefined();

    const confirmBtn = screen.getByRole('button', { name: /^revoke device$/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(callAdminSpy).toHaveBeenCalledWith('revoke_device', { device_id: 'device-uuid-1' });
      expect(onRefreshMock).toHaveBeenCalled();
    });
    expect(callAdminSpy).not.toHaveBeenCalledWith('set_device_uninstall', expect.anything());
  });

  it('only requests uninstall when the administrator ticks the uninstall box', async () => {
    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
      user: { id: 'admin-1', email: 'admin@company.com' } as any,
      session: {} as any,
      adminProfile: { user_id: 'admin-1', role: 'admin', slot: 1, created_at: '', revoked_at: null },
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
    const callAdminSpy = vi.spyOn(SupabaseLib, 'callAdminAction').mockResolvedValue({ data: { result: {} } });

    render(<DevicesPage devices={mockDevices} sessions={mockSessions} onRefresh={vi.fn()} onNavigateToMfa={vi.fn()} />);
    fireEvent.click(screen.getByTitle(/revoke device authorization/i));
    fireEvent.click(screen.getByRole('checkbox', { name: /also uninstall/i }));
    fireEvent.click(screen.getByRole('button', { name: /revoke and uninstall/i }));

    await waitFor(() => {
      expect(callAdminSpy).toHaveBeenNthCalledWith(1, 'revoke_device', { device_id: 'device-uuid-1' });
      expect(callAdminSpy).toHaveBeenNthCalledWith(2, 'set_device_uninstall', { device_id: 'device-uuid-1', uninstall: true });
    });
  });

  it('removes UUID and restrictions from revoked device via remove_device_uuid when confirmed at AAL2', async () => {
    const revokedDevices: Device[] = [
      {
        id: 'revoked-uuid-1',
        installation_uuid: '99999999-8888-7777-6666-555555555555',
        device_name: 'REVOKED-PC-01',
        created_at: '2026-11-02T08:00:00Z',
        revoked_at: '2026-11-02T10:00:00Z',
      },
    ];

    vi.spyOn(AuthContextModule, 'useAuth').mockReturnValue({
      user: { id: 'admin-1', email: 'admin@company.com' } as any,
      session: {} as any,
      adminProfile: { user_id: 'admin-1', role: 'admin', slot: 1, created_at: '', revoked_at: null },
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

    const callAdminSpy = vi.spyOn(SupabaseLib, 'callAdminAction').mockResolvedValue({
      data: { success: true },
    });

    const onRefreshMock = vi.fn();

    render(
      <DevicesPage
        devices={revokedDevices}
        sessions={mockSessions}
        onRefresh={onRefreshMock}
        onNavigateToMfa={vi.fn()}
      />
    );

    // Revoked devices offer Restore (remove_device_uuid)
    const removeUuidBtn = screen.getByRole('button', { name: /^restore$/i });
    expect(removeUuidBtn).toBeDefined();
    fireEvent.click(removeUuidBtn);

    // Modal opens
    expect(screen.getByText('Restore REVOKED-PC-01?')).toBeDefined();
    expect(screen.getAllByText(/REVOKED-PC-01/i).length).toBeGreaterThan(0);

    // Confirm removal
    const confirmBtn = screen.getByRole('button', { name: /restore device/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(callAdminSpy).toHaveBeenCalledWith('remove_device_uuid', { device_id: 'revoked-uuid-1' });
      expect(onRefreshMock).toHaveBeenCalled();
    });
  });
});
