import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useMonitoringData } from '../src/hooks/useMonitoringData';
import { supabase, subscribeToMonitoringBroadcast } from '../src/lib/supabase';
import { getDisplayName, calculateOperatorStatus, DEFAULT_SETTINGS } from '../src/lib/status';
import { Session } from '../src/types';

describe('Realtime Broadcast, Synchronization and Error Resilience (Unit / Mocked)', () => {
  it('subscribes to nexus:monitoring channel and unsubscribes cleanly on unmount', () => {
    const mockChannel = {
      on: vi.fn().mockReturnThis(),
      subscribe: vi.fn().mockReturnThis(),
    };
    const channelSpy = vi.spyOn(supabase, 'channel').mockReturnValue(mockChannel as any);
    const removeChannelSpy = vi.spyOn(supabase, 'removeChannel').mockReturnValue(Promise.resolve('ok') as any);

    const onRefresh = vi.fn();
    const unsubscribe = subscribeToMonitoringBroadcast(onRefresh);

    // Verify channel topic matches exact backend RLS policy
    expect(channelSpy).toHaveBeenCalledWith('nexus:monitoring', expect.anything());
    expect(mockChannel.on).toHaveBeenCalledWith('broadcast', { event: 'refresh' }, expect.any(Function));

    // Test unsubscribe cleanup
    unsubscribe();
    expect(removeChannelSpy).toHaveBeenCalledWith(mockChannel);
  });

  it('handles empty monitoring dataset without crashing', async () => {
    vi.spyOn(supabase, 'rpc').mockResolvedValue({
      data: {
        server_time: new Date().toISOString(),
        settings: DEFAULT_SETTINGS,
        devices: [],
        sessions: [],
      },
      error: null,
    } as any);
    vi.spyOn(supabase, 'from').mockReturnValue({
      select: vi.fn().mockReturnThis(),
      order: vi.fn().mockReturnThis(),
      limit: vi.fn().mockResolvedValue({ data: [], error: null }),
    } as any);

    const { result } = renderHook(() => useMonitoringData(15));

    await act(async () => {
      await result.current.refreshAll();
    });

    expect(result.current.devices).toEqual([]);
    expect(result.current.activeSessions).toEqual([]);
    expect(result.current.error).toBeNull();
    expect(result.current.isConnected).toBe(true);
  });

  it('surfaces actionable error message upon Supabase connection failure or 42501 permission error', async () => {
    // 42501 = Administrator access required (AAL2 needed)
    vi.spyOn(supabase, 'rpc').mockResolvedValue({
      data: null,
      error: { code: '42501', message: 'Administrator access required', details: '', hint: '' } as any,
    } as any);
    vi.spyOn(supabase, 'from').mockReturnValue({
      select: vi.fn().mockReturnThis(),
      order: vi.fn().mockReturnThis(),
      limit: vi.fn().mockResolvedValue({ data: [], error: null }),
    } as any);

    const { result } = renderHook(() => useMonitoringData(15));

    await act(async () => {
      await result.current.refreshAll();
    });

    expect(result.current.error).toContain('AAL2 MFA authorization required');
    expect(result.current.isConnected).toBe(false);
  });

  it('tracks operator identity switching mid-session (KPI Profile A -> KPI Profile B -> Device Fallback)', () => {
    const baseSession: Session = {
      id: 'sess-dynamic',
      device_id: 'dev-1',
      credential_id: 'cred-1',
      device_name_snapshot: 'WORKSTATION-05',
      operator_name_snapshot: 'Operator Alpha',
      operator_name: 'Operator Alpha',
      identity_source: 'KPI Profile',
      app_version: '5.2.0',
      active_module: 'Air Export',
      started_at: '2026-11-02T10:00:00Z',
      received_at: '2026-11-02T10:00:00Z',
      last_event_at: '2026-11-02T10:30:00Z',
      last_seen_at: '2026-11-02T10:30:00Z',
      idle_seconds: 10,
      ended_at: null,
      end_reason: null,
      end_is_estimated: false,
      event_sequence: 10,
      live_sequence: 10,
      disconnected_at: null,
      status: 'active',
    };

    // 1. Initial login with Operator Alpha
    const id1 = getDisplayName(baseSession.operator_name, baseSession.device_name_snapshot, baseSession.identity_source);
    expect(id1.name).toBe('Operator Alpha');
    expect(id1.isFallback).toBe(false);

    // 2. Operator switched profile to Operator Beta
    const switchedSession: Session = {
      ...baseSession,
      operator_name: 'Operator Beta',
      operator_name_snapshot: 'Operator Beta',
      event_sequence: 25,
      live_sequence: 25,
    };
    const id2 = getDisplayName(switchedSession.operator_name, switchedSession.device_name_snapshot, switchedSession.identity_source);
    expect(id2.name).toBe('Operator Beta');
    expect(id2.isFallback).toBe(false);

    // 3. Operator logs out of KPI profile, falling back to machine hostname
    const fallbackSession: Session = {
      ...baseSession,
      operator_name: '',
      operator_name_snapshot: '',
      identity_source: 'Device Fallback',
      event_sequence: 35,
      live_sequence: 35,
    };
    const id3 = getDisplayName(fallbackSession.operator_name, fallbackSession.device_name_snapshot, fallbackSession.identity_source);
    expect(id3.name).toBe('WORKSTATION-05');
    expect(id3.isFallback).toBe(true);
  });
});
