export type AdminRole = 'owner' | 'admin';

export interface AdminProfile {
  user_id: string;
  role: AdminRole;
  slot: number | null;
  created_at: string;
  revoked_at: string | null;
  email?: string;
}

export interface Device {
  id: string;
  installation_uuid: string;
  device_name: string;
  created_at: string;
  revoked_at: string | null;
  // Computed / joined fields
  active_sessions_count?: number;
  last_seen_at?: string | null;
  current_operator?: string | null;
  credential_count?: number;
}

export type IdentitySource = 'KPI Profile' | 'Device Fallback';

export type SessionEndReason = 'closed' | 'unclean' | 'revoked';

export interface Session {
  id: string;
  device_id: string;
  credential_id: string;
  device_name_snapshot: string;
  operator_name_snapshot: string;
  identity_source: IdentitySource;
  app_version: string;
  active_module: string;
  started_at: string;
  received_at: string;
  last_event_at: string;
  last_seen_at: string | null;
  idle_seconds: number;
  ended_at: string | null;
  end_reason: SessionEndReason | null;
  end_is_estimated: boolean;
  event_sequence: number;
  live_sequence: number;
  disconnected_at: string | null;
  // Computed field from joins / snapshot
  operator_name?: string;
  status?: OperatorStatus;
}

export type EventType =
  | 'started'
  | 'operator_changed'
  | 'module_changed'
  | 'closed'
  | 'unclean'
  | 'recording_gap'
  | 'disconnected'
  | 'reconnected';

export interface SessionEvent {
  id: string;
  session_id: string;
  sequence: number;
  event_type: EventType;
  event_timestamp: string;
  received_at: string;
  metadata: Record<string, unknown>;
}

export interface SessionIdentityPeriod {
  session_id: string;
  start_sequence: number;
  operator_name_snapshot: string;
  identity_source: IdentitySource;
  started_at: string;
}

export interface MonitoringSettings {
  id: boolean;
  heartbeat_seconds: number;
  disconnected_seconds: number;
  idle_seconds: number;
  dashboard_refresh_seconds: number;
  history_days: number;
}

export type OperatorStatus = 'active' | 'online' | 'idle' | 'disconnected' | 'offline' | 'closed' | 'revoked';

export interface LiveOperator {
  session_id: string;
  device_id: string;
  operator_name: string;
  identity_source: IdentitySource;
  device_name: string;
  active_module: string;
  app_version: string;
  started_at: string;
  last_seen_at: string | null;
  idle_seconds: number;
  status: OperatorStatus;
  is_fallback: boolean;
}

export interface SnapshotData {
  server_time: string;
  settings: MonitoringSettings;
  devices: Device[];
  sessions: {
    id: string;
    device_id: string;
    device_name_snapshot: string;
    active_module: string;
    app_version: string;
    started_at: string;
    last_seen_at: string | null;
    idle_seconds: number;
    operator_name: string;
    identity_source: IdentitySource;
    status: 'online' | 'idle' | 'disconnected' | 'offline' | 'revoked';
  }[];
}

export interface EnrollmentBundle {
  url: string;
  key: string;
  enrollment_id: string;
  code: string;
  installation_uuid: string;
  device_name: string;
  account_label: string;
  expires_at: string;
  expires_in_seconds: number;
}

export type NavigationTab =
  | 'overview'
  | 'devices'
  | 'sessions'
  | 'reconciliation'
  | 'admins'
  | 'settings';

/** Hash routes from the previous dashboard layout, mapped to their new home. */
export const LEGACY_TAB_MAP: Record<string, NavigationTab> = {
  operators: 'overview',
  events: 'sessions',
  mfa: 'admins',
};

export interface ScreenViewLogEntry {
  id: string;
  device_id: string;
  device_name: string;
  admin_email: string;
  reason: string;
  created_at: string;
  verified_at: string | null;
  ended_at: string | null;
}

export interface ReconciliationJob {
  job_id: string;
  warehouse: string;
  client: string;
  status: 'Pending' | 'In Progress' | 'Completed' | 'Unknown';
  assigned_user: string;
  observed_at: string;
  received_at: string;
  device_name: string;
}
