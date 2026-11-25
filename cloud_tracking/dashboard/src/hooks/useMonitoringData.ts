import { useState, useEffect, useCallback, useRef } from 'react';
import { supabase, subscribeToMonitoringBroadcast } from '../lib/supabase';
import { SnapshotData, Session, Device, SessionEvent, MonitoringSettings } from '../types';
import { calculateOperatorStatus, DEFAULT_SETTINGS } from '../lib/status';

export function useMonitoringData(refreshIntervalSec: number = 10) {
  const [snapshot, setSnapshot] = useState<SnapshotData | null>(null);
  const [settings, setSettings] = useState<MonitoringSettings>(DEFAULT_SETTINGS);
  const [devices, setDevices] = useState<Device[]>([]);
  const [activeSessions, setActiveSessions] = useState<Session[]>([]);
  const [recentEvents, setRecentEvents] = useState<SessionEvent[]>([]);
  const [sessionsTodayCount, setSessionsTodayCount] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState<boolean>(true);

  const isMountedRef = useRef(true);

  const fetchSnapshot = useCallback(async (isBackground = false) => {
    if (!isBackground) {
      setIsRefreshing(true);
    }
    try {
      const { data, error: rpcError } = await supabase.rpc('nexus_current_snapshot');

      if (rpcError) {
        // If 42501 (Administrator access required / AAL2 required), surface clear message
        if (rpcError.code === '42501') {
          setError('AAL2 MFA authorization required to load monitoring snapshot.');
        } else {
          setError(rpcError.message);
        }
        setIsConnected(false);
        return;
      }

      if (data && isMountedRef.current) {
        const snap = data as SnapshotData;
        setSnapshot(snap);
        if (snap.settings) {
          setSettings(snap.settings);
        }
        if (snap.devices) {
          setDevices(snap.devices);
        }
        if (snap.sessions) {
          // Normalize sessions with active status calculation
          const now = Date.now();
          const normalized: Session[] = snap.sessions.map((s) => ({
            id: s.id,
            device_id: s.device_id,
            credential_id: '',
            device_name_snapshot: s.device_name_snapshot,
            operator_name_snapshot: s.operator_name,
            operator_name: s.operator_name,
            identity_source: s.identity_source,
            app_version: s.app_version,
            active_module: s.active_module,
            started_at: s.started_at,
            received_at: s.started_at,
            last_event_at: s.last_seen_at || s.started_at,
            last_seen_at: s.last_seen_at,
            idle_seconds: s.idle_seconds,
            ended_at: null,
            end_reason: null,
            end_is_estimated: false,
            event_sequence: 0,
            live_sequence: 0,
            disconnected_at: null,
            status: calculateOperatorStatus(s, snap.settings || DEFAULT_SETTINGS, now),
          }));

          // Deduplicate by physical device: each device has exactly ONE current live operator session
          const statusPriority = (status?: string) => {
            if (status === 'active') return 4;
            if (status === 'idle') return 3;
            if (status === 'disconnected') return 2;
            return 1;
          };

          const sorted = [...normalized].sort((a, b) => {
            const pDiff = statusPriority(b.status) - statusPriority(a.status);
            if (pDiff !== 0) return pDiff;
            const bTime = b.started_at ? Date.parse(b.started_at) : 0;
            const aTime = a.started_at ? Date.parse(a.started_at) : 0;
            return bTime - aTime;
          });

          const deviceMap = new Map<string, Session>();
          for (const s of sorted) {
            const key = s.device_id || s.device_name_snapshot;
            if (!deviceMap.has(key)) {
              deviceMap.set(key, s);
            }
          }

          setActiveSessions(Array.from(deviceMap.values()));
        }
        setLastUpdated(new Date());
        setError(null);
        setIsConnected(true);
      }
    } catch (err: unknown) {
      if (isMountedRef.current) {
        const msg = err instanceof Error ? err.message : 'Error loading monitoring data';
        setError(msg);
        setIsConnected(false);
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, []);

  const fetchRecentEvents = useCallback(async () => {
    try {
      const { data, error: eventsErr } = await supabase
        .from('session_events')
        .select('*')
        .order('received_at', { ascending: false })
        .limit(50);

      if (!eventsErr && data && isMountedRef.current) {
        setRecentEvents(data as SessionEvent[]);
      }
    } catch {
      // Ignore background event refresh errors
    }
  }, []);

  const fetchSessionsTodayCount = useCallback(async () => {
    try {
      const startOfToday = new Date();
      startOfToday.setHours(0, 0, 0, 0);
      const { count, error: countError } = await supabase
        .from('sessions')
        .select('id', { count: 'exact', head: true })
        .gte('started_at', startOfToday.toISOString());
      if (isMountedRef.current) setSessionsTodayCount(countError ? null : count);
    } catch {
      if (isMountedRef.current) setSessionsTodayCount(null);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([fetchSnapshot(false), fetchRecentEvents(), fetchSessionsTodayCount()]);
  }, [fetchSnapshot, fetchRecentEvents, fetchSessionsTodayCount]);

  useEffect(() => {
    isMountedRef.current = true;
    refreshAll();

    // 15-second periodic refresh while visible
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        fetchSnapshot(true);
        fetchRecentEvents();
        fetchSessionsTodayCount();
      }
    }, Math.max(10, refreshIntervalSec) * 1000);

    // Private Realtime broadcast subscription
    const unsubscribeRealtime = subscribeToMonitoringBroadcast(() => {
      fetchSnapshot(true);
      fetchRecentEvents();
      fetchSessionsTodayCount();
    });

    return () => {
      isMountedRef.current = false;
      clearInterval(interval);
      unsubscribeRealtime();
    };
  }, [fetchSnapshot, fetchRecentEvents, fetchSessionsTodayCount, refreshIntervalSec, refreshAll]);

  return {
    snapshot,
    settings,
    devices,
    activeSessions,
    recentEvents,
    sessionsTodayCount,
    isLoading,
    isRefreshing,
    lastUpdated,
    error,
    isConnected,
    refreshAll,
  };
}
