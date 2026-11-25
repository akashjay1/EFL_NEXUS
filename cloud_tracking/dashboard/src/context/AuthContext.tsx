import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { User, Session } from '@supabase/supabase-js';
import { supabase } from '../lib/supabase';
import { AdminProfile } from '../types';

interface AuthContextType {
  user: User | null;
  session: Session | null;
  adminProfile: AdminProfile | null;
  aalLevel: 'aal1' | 'aal2' | null;
  nextAalLevel: 'aal1' | 'aal2' | null;
  hasMfaFactors: boolean;
  isLoading: boolean;
  error: string | null;
  signIn: (email: string, pass: string) => Promise<{ success: boolean; error?: string }>;
  signOut: () => Promise<void>;
  refreshAuthStatus: () => Promise<void>;
  verifyMfaChallenge: (factorId: string, challengeId: string, code: string) => Promise<{ success: boolean; error?: string }>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [adminProfile, setAdminProfile] = useState<AdminProfile | null>(null);
  const [aalLevel, setAalLevel] = useState<'aal1' | 'aal2' | null>(null);
  const [nextAalLevel, setNextAalLevel] = useState<'aal1' | 'aal2' | null>(null);
  const [hasMfaFactors, setHasMfaFactors] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAdminProfile = useCallback(async (userId: string): Promise<AdminProfile | null> => {
    try {
      const { data, error } = await supabase
        .from('admin_profiles')
        .select('*')
        .eq('user_id', userId)
        .is('revoked_at', null)
        .maybeSingle();

      if (error || !data) {
        return null;
      }
      return data as AdminProfile;
    } catch {
      return null;
    }
  }, []);

  const refreshAuthStatus = useCallback(async () => {
    try {
      const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
      if (sessionError || !sessionData?.session) {
        setUser(null);
        setSession(null);
        setAdminProfile(null);
        setAalLevel(null);
        setNextAalLevel(null);
        setHasMfaFactors(false);
        setIsLoading(false);
        return;
      }

      const activeSession = sessionData.session;
      const activeUser = activeSession.user;
      setUser(activeUser);
      setSession(activeSession);

      // Verify administrator status from database table
      const profile = await fetchAdminProfile(activeUser.id);
      if (!profile) {
        // Not an authorized admin
        await supabase.auth.signOut();
        setUser(null);
        setSession(null);
        setAdminProfile(null);
        setError('Access denied: You are not registered as an authorized administrator.');
        setIsLoading(false);
        return;
      }
      setAdminProfile({ ...profile, email: activeUser.email });

      // Check MFA / AAL status
      const { data: aalData } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
      if (aalData) {
        setAalLevel((aalData.currentLevel as 'aal1' | 'aal2') || null);
        setNextAalLevel((aalData.nextLevel as 'aal1' | 'aal2') || null);
      }

      // Check verified factors
      const { data: factorsData } = await supabase.auth.mfa.listFactors();
      const verifiedTotp = factorsData?.totp?.some((f) => f.status === 'verified') || false;
      setHasMfaFactors(verifiedTotp);
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Authentication verification failed';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [fetchAdminProfile]);

  useEffect(() => {
    refreshAuthStatus();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, newSession) => {
      if (newSession) {
        // Run SDK calls after the auth callback releases the session lock.
        setTimeout(() => { void refreshAuthStatus(); }, 0);
      } else {
        setUser(null);
        setSession(null);
        setAdminProfile(null);
        setAalLevel(null);
        setNextAalLevel(null);
        setHasMfaFactors(false);
        setIsLoading(false);
      }
    });

    return () => {
      subscription.unsubscribe();
    };
  }, [refreshAuthStatus]);

  const signIn = async (email: string, pass: string): Promise<{ success: boolean; error?: string }> => {
    setIsLoading(true);
    setError(null);
    try {
      const { data, error: signInError } = await supabase.auth.signInWithPassword({
        email: email.trim().toLowerCase(),
        password: pass,
      });

      if (signInError) {
        setError(signInError.message);
        setIsLoading(false);
        return { success: false, error: signInError.message };
      }

      if (!data.user) {
        setError('Login failed');
        setIsLoading(false);
        return { success: false, error: 'Login failed' };
      }

      // Check admin profile
      const profile = await fetchAdminProfile(data.user.id);
      if (!profile) {
        await supabase.auth.signOut();
        const accessDenied = 'Unauthorized: Account does not have administrator privileges.';
        setError(accessDenied);
        setIsLoading(false);
        return { success: false, error: accessDenied };
      }

      await refreshAuthStatus();
      return { success: true };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Sign in failed';
      setError(msg);
      setIsLoading(false);
      return { success: false, error: msg };
    }
  };

  const verifyMfaChallenge = async (
    factorId: string,
    challengeId: string,
    code: string
  ): Promise<{ success: boolean; error?: string }> => {
    try {
      const { data, error: verifyErr } = await supabase.auth.mfa.verify({
        factorId,
        challengeId,
        code: code.trim(),
      });

      if (verifyErr) {
        return { success: false, error: verifyErr.message };
      }

      if (data) {
        await refreshAuthStatus();
        return { success: true };
      }
      return { success: false, error: 'Verification failed' };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to verify MFA code';
      return { success: false, error: msg };
    }
  };

  const signOut = async () => {
    setIsLoading(true);
    try {
      await supabase.auth.signOut();
    } finally {
      setUser(null);
      setSession(null);
      setAdminProfile(null);
      setAalLevel(null);
      setNextAalLevel(null);
      setHasMfaFactors(false);
      setIsLoading(false);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        adminProfile,
        aalLevel,
        nextAalLevel,
        hasMfaFactors,
        isLoading,
        error,
        signIn,
        signOut,
        refreshAuthStatus,
        verifyMfaChallenge,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
