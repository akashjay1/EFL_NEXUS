import { createClient } from '@supabase/supabase-js';

// Approved Supabase project configuration (eu-west-1)
export const SUPABASE_URL =
  import.meta.env?.VITE_SUPABASE_URL || 'https://wykmgymitdxkqbpywpzh.supabase.co';

export const SUPABASE_ANON_KEY =
  import.meta.env?.VITE_SUPABASE_ANON_KEY ||
  'sb_publishable_4kmXj_vznXL8qyK5hFXeoQ_eSGi3xkR';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storageKey: 'efl_nexus_admin_session',
  },
  realtime: {
    params: {
      eventsPerSecond: 10,
    },
  },
});

/**
 * Invokes the deployed admin-control Edge Function with the authenticated user's JWT.
 * Requires AAL2 (verified TOTP MFA).
 */
export async function callAdminAction<T = unknown>(
  action: string,
  args: Record<string, unknown> = {}
): Promise<{ data?: T; error?: string }> {
  try {
    const { data: sessionData } = await supabase.auth.getSession();
    const token = sessionData?.session?.access_token;
    if (!token) {
      return { error: 'Authentication required. Please sign in.' };
    }

    const response = await fetch(`${SUPABASE_URL}/functions/v1/admin-control`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        apikey: SUPABASE_ANON_KEY,
      },
      body: JSON.stringify({ action, args }),
    });

    const body = await response.json();

    if (!response.ok) {
      const errorCode = body?.error || body?.message || `HTTP ${response.status}`;
      if (response.status === 403 && errorCode === 'mfa_required') {
        return { error: 'AAL2_REQUIRED: Two-factor authentication (TOTP) is required for this operation.' };
      }
      return { error: `Admin operation failed: ${errorCode}` };
    }

    return { data: body as T };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Network error communicating with admin control.';
    return { error: message };
  }
}

/**
 * Subscribes to private Realtime monitoring refresh broadcasts on 'nexus:monitoring'.
 * Payloads contain { refresh: true }, prompting the client to re-read RLS-protected data.
 */
export function subscribeToMonitoringBroadcast(onRefresh: () => void) {
  const channel = supabase.channel('nexus:monitoring', {
    config: {
      private: true,
      broadcast: { self: false },
    },
  });

  channel
    .on('broadcast', { event: 'refresh' }, () => {
      onRefresh();
    })
    .subscribe((status) => {
      if (status === 'SUBSCRIBED') {
        // Connected to broadcast channel
      }
    });

  return () => {
    supabase.removeChannel(channel);
  };
}
