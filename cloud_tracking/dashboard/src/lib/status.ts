import { OperatorStatus, IdentitySource, Session, MonitoringSettings } from '../types';

export const DEFAULT_SETTINGS: MonitoringSettings = {
  id: true,
  heartbeat_seconds: 30,
  disconnected_seconds: 90,
  idle_seconds: 300,
  dashboard_refresh_seconds: 10,
  history_days: 90,
};

export function calculateOperatorStatus(
  session: Partial<Session> & { revoked_at?: string | null },
  settings: MonitoringSettings = DEFAULT_SETTINGS,
  now: number = Date.now()
): OperatorStatus {
  if (session.revoked_at || session.status === 'revoked') {
    return 'revoked';
  }

  if (session.ended_at) {
    return session.end_reason === 'closed' ? 'closed' : 'offline';
  }

  // The snapshot marks terminal sessions offline without including ended_at.
  if (session.status === 'offline') {
    return 'offline';
  }

  if (!session.last_seen_at) {
    return 'disconnected';
  }

  const lastSeenMs = Date.parse(session.last_seen_at);
  const diffSec = (now - lastSeenMs) / 1000;

  if (diffSec > settings.disconnected_seconds) {
    return 'disconnected';
  }

  if ((session.idle_seconds ?? 0) >= settings.idle_seconds) {
    return 'idle';
  }

  return 'active';
}

export function getDisplayName(
  operatorName: string | undefined | null,
  deviceName: string,
  identitySource: IdentitySource
): { name: string; isFallback: boolean } {
  if (identitySource === 'KPI Profile' && operatorName && operatorName.trim().length > 0) {
    return { name: operatorName.trim(), isFallback: false };
  }
  return { name: deviceName || 'Unknown Device', isFallback: true };
}

export function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '0s';
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hrs > 0) {
    return `${hrs}h ${mins}m`;
  }
  if (mins > 0) {
    return `${mins}m ${secs}s`;
  }
  return `${secs}s`;
}

export function formatTimeAgo(timestamp: string | null | undefined, now: number = Date.now()): string {
  if (!timestamp) return 'Never';
  const ms = Date.parse(timestamp);
  if (isNaN(ms)) return '—';

  const seconds = Math.max(0, Math.floor((now - ms) / 1000));
  if (seconds < 5) return 'Just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatDateTime(timestamp: string | null | undefined, timeZone?: string): string {
  if (!timestamp) return '—';
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return '—';
  const resolvedTz = timeZone === 'utc' ? 'UTC' : timeZone === 'Asia/Colombo' ? 'Asia/Colombo' : undefined;
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: resolvedTz,
  });
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1)} ${sizes[i]}`;
}
