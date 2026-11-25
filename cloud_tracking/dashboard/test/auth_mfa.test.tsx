import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from '../src/context/AuthContext';
import { supabase } from '../src/lib/supabase';
import { SecurityMfaPage } from '../src/pages/SecurityMfaPage';

// Helper component to inspect auth context values in tests
const TestAuthConsumer: React.FC = () => {
  const { user, adminProfile, aalLevel, error, signIn, signOut } = useAuth();
  return (
    <div>
      <div data-testid="user-id">{user?.id || 'none'}</div>
      <div data-testid="admin-role">{adminProfile?.role || 'none'}</div>
      <div data-testid="aal-level">{aalLevel || 'none'}</div>
      <div data-testid="auth-error">{error || 'none'}</div>
      <button onClick={() => signIn('admin@company.com', 'password123')}>Login</button>
      <button onClick={() => signOut()}>Logout</button>
    </div>
  );
};

describe('Authentication and AAL Assurance Lifecycle (Unit / Mocked)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(supabase.auth, 'onAuthStateChange').mockReturnValue({
      data: { subscription: { unsubscribe: vi.fn() } as any },
    });
  });

  it('rejects users who are not registered in the admin_profiles table (unauthorized administrator rejection)', async () => {
    // Mock successful auth.signInWithPassword
    vi.spyOn(supabase.auth, 'signInWithPassword').mockResolvedValue({
      data: {
        user: { id: 'unauthorized-user-uuid', email: 'intruder@external.com' } as any,
        session: { access_token: 'valid-jwt-token' } as any,
      },
      error: null,
    });

    // Mock admin_profiles check returning null (not on 5-slot roster)
    vi.spyOn(supabase, 'from').mockReturnValue({
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      is: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
    } as any);

    // Mock signOut
    const signOutSpy = vi.spyOn(supabase.auth, 'signOut').mockResolvedValue({ error: null } as any);

    render(
      <AuthProvider>
        <TestAuthConsumer />
      </AuthProvider>
    );

    const loginBtn = screen.getByText('Login');
    fireEvent.click(loginBtn);

    await waitFor(() => {
      expect(screen.getByTestId('auth-error').textContent).toContain('Unauthorized');
      expect(screen.getByTestId('admin-role').textContent).toBe('none');
      expect(signOutSpy).toHaveBeenCalled();
    });
  });

  it('sets AAL1 session state when user logs in with password only', async () => {
    const mockUser = { id: 'admin-slot-1-uuid', email: 'admin1@eflnexus.com' };
    const mockSession = { access_token: 'valid-jwt-token', user: mockUser };

    vi.spyOn(supabase.auth, 'signInWithPassword').mockResolvedValue({
      data: {
        user: mockUser as any,
        session: mockSession as any,
      },
      error: null,
    });

    vi.spyOn(supabase.auth, 'getUser').mockResolvedValue({
      data: { user: mockUser as any },
      error: null,
    });

    vi.spyOn(supabase.auth, 'getSession').mockResolvedValue({
      data: { session: mockSession as any },
      error: null,
    });

    vi.spyOn(supabase, 'from').mockReturnValue({
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      is: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({
        data: { user_id: 'admin-slot-1-uuid', role: 'admin', slot: 1, created_at: '', revoked_at: null },
        error: null,
      }),
    } as any);

    vi.spyOn(supabase.auth.mfa, 'getAuthenticatorAssuranceLevel').mockResolvedValue({
      data: { currentLevel: 'aal1', nextLevel: 'aal2', currentAuthenticationMethods: [] },
      error: null,
    });

    vi.spyOn(supabase.auth.mfa, 'listFactors').mockResolvedValue({
      data: { all: [], totp: [], phone: [], recovery_code: [], webauthn: [] },
      error: null,
    } as any);

    render(
      <AuthProvider>
        <TestAuthConsumer />
      </AuthProvider>
    );

    const loginBtn = screen.getByText('Login');
    fireEvent.click(loginBtn);

    await waitFor(() => {
      expect(screen.getByTestId('admin-role').textContent).toBe('admin');
      expect(screen.getByTestId('aal-level').textContent).toBe('aal1');
    });
  });

  it('elevates session state to AAL2 upon successful TOTP challenge verification', async () => {
    const mockUser = { id: 'admin-owner-uuid', email: 'owner@eflnexus.com' };
    const mockProfile = { user_id: 'admin-owner-uuid', role: 'owner' as const, slot: 0, created_at: '', revoked_at: null };

    // Initially AAL1
    let currentAal: 'aal1' | 'aal2' = 'aal1';

    vi.spyOn(supabase.auth, 'getUser').mockResolvedValue({ data: { user: mockUser as any }, error: null });
    vi.spyOn(supabase.auth, 'getSession').mockResolvedValue({
      data: { session: { access_token: 'mock-token', user: mockUser } as any },
      error: null,
    });
    vi.spyOn(supabase.auth.mfa, 'getAuthenticatorAssuranceLevel').mockImplementation(async () => ({
      data: { currentLevel: currentAal, nextLevel: 'aal2', currentAuthenticationMethods: [] },
      error: null,
    }));
    vi.spyOn(supabase.auth.mfa, 'listFactors').mockResolvedValue({
      data: {
        all: [],
        totp: [{ id: 'factor-1', friendly_name: 'Work Authenticator', factor_type: 'totp', status: 'verified', created_at: '', updated_at: '' }],
        phone: [],
        recovery_code: [],
        webauthn: [],
      },
      error: null,
    } as any);
    vi.spyOn(supabase, 'from').mockReturnValue({
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      is: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({ data: mockProfile, error: null }),
    } as any);

    // Mock challenge and verify
    vi.spyOn(supabase.auth.mfa, 'challenge').mockResolvedValue({
      data: { id: 'challenge-1', expires_at: 0, type: 'totp' },
      error: null,
    } as any);

    vi.spyOn(supabase.auth.mfa, 'verify').mockImplementation(async (params: any) => {
      if (params.code === '123456') {
        currentAal = 'aal2';
        return { data: { user: mockUser } as any, error: null };
      }
      return { data: null, error: { message: 'Invalid TOTP code' } as any };
    });

    render(
      <AuthProvider>
        <SecurityMfaPage />
      </AuthProvider>
    );

    // Verify AAL1 warning banner is displayed
    await waitFor(() => {
      expect(screen.getByText(/Current Session: AAL1 \(Password Only\)/i)).toBeDefined();
    });

    // Open challenge modal
    const verifyMfaBtn = await screen.findByText('Verify Code for AAL2');
    fireEvent.click(verifyMfaBtn);

    // Enter 6-digit code in modal
    const codeInput = screen.getByPlaceholderText('000000');
    fireEvent.change(codeInput, { target: { value: '123456' } });

    const submitVerifyBtn = screen.getByRole('button', { name: /verify & elevate to aal2/i });
    fireEvent.click(submitVerifyBtn);

    await waitFor(() => {
      expect(screen.getByText(/You are now authenticated at AAL2/i)).toBeDefined();
    });
  });

  it('handles expired authentication cleanly by clearing session state', async () => {
    vi.spyOn(supabase.auth, 'getUser').mockResolvedValue({
      data: { user: null },
      error: { message: 'JWT expired' } as any,
    });
    vi.spyOn(supabase.auth, 'getSession').mockResolvedValue({
      data: { session: null },
      error: null,
    });

    render(
      <AuthProvider>
        <TestAuthConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('user-id').textContent).toBe('none');
      expect(screen.getByTestId('admin-role').textContent).toBe('none');
      expect(screen.getByTestId('aal-level').textContent).toBe('none');
    });
  });
});
