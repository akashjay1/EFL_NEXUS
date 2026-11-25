import React, { useMemo, useState } from 'react';
import { Search, Monitor, Users, Info } from 'lucide-react';
import { Device, Session } from '../../types';
import { StatusBadge, IdentityBadge } from '../common/Badge';
import { Modal } from '../common/Modal';
import { EmptyState } from '../common/LoadingSpinner';
import { formatDateTime, formatDuration, formatTimeAgo, getDisplayName } from '../../lib/status';

type StatusFilter = 'all' | 'active' | 'idle' | 'disconnected';

const FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'active', label: 'Active' },
  { id: 'idle', label: 'Idle' },
  { id: 'disconnected', label: 'Offline' },
];

interface WorkstationBoardProps {
  sessions: Session[];
  devices?: Device[];
  /** Shown only for devices that are not revoked. */
  onViewScreen?: (device: Device) => void;
}

export const WorkstationBoard: React.FC<WorkstationBoardProps> = ({ sessions, devices = [], onViewScreen }) => {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [module, setModule] = useState('all');
  const [selected, setSelected] = useState<Session | null>(null);

  const modules = useMemo(
    () => Array.from(new Set(sessions.map((s) => s.active_module).filter(Boolean))).sort(),
    [sessions]
  );

  const counts = useMemo(() => {
    const c: Record<StatusFilter, number> = { all: sessions.length, active: 0, idle: 0, disconnected: 0 };
    sessions.forEach((s) => {
      if (s.status === 'active' || s.status === 'idle' || s.status === 'disconnected') c[s.status] += 1;
    });
    return c;
  }, [sessions]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return sessions.filter((s) => {
      const { name } = getDisplayName(s.operator_name || s.operator_name_snapshot, s.device_name_snapshot, s.identity_source);
      const matchesQuery =
        !q ||
        name.toLowerCase().includes(q) ||
        s.device_name_snapshot.toLowerCase().includes(q) ||
        (s.active_module ?? '').toLowerCase().includes(q);
      const matchesStatus = status === 'all' || (s.status ?? 'offline') === status;
      const matchesModule = module === 'all' || s.active_module === module;
      return matchesQuery && matchesStatus && matchesModule;
    });
  }, [sessions, query, status, module]);

  const selectedName = selected
    ? getDisplayName(selected.operator_name || selected.operator_name_snapshot, selected.device_name_snapshot, selected.identity_source).name
    : '';

  return (
    <div>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between mb-4">
        <div role="group" aria-label="Filter by status" className="inline-flex flex-wrap gap-1 rounded-xl bg-[#eaecf0] p-1 self-start">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setStatus(f.id)}
              aria-pressed={status === f.id}
              className={`min-h-9 px-3 rounded-lg text-sm font-semibold transition-colors ${
                status === f.id ? 'bg-surface text-ink shadow-[0_1px_2px_rgba(16,24,40,0.08)]' : 'text-muted hover:text-ink'
              }`}
            >
              {f.label} <span className="tabular-nums text-muted font-medium">{counts[f.id]}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <label className="relative block sm:w-72">
            <span className="sr-only">Search workstations</span>
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by operator, device, or module..."
              className="field pl-9"
            />
          </label>
          <label className="sm:w-56">
            <span className="sr-only">Filter by module</span>
            <select value={module} onChange={(e) => setModule(e.target.value)} className="field">
              <option value="all">All modules</option>
              {modules.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon={<Users className="w-10 h-10" />} title={sessions.length === 0 ? 'No workstations reporting yet' : 'No workstations match these filters'}>
          {sessions.length === 0
            ? 'When operators open EFL NEXUS, their workstation appears here automatically.'
            : 'Try a different search or clear the filters.'}
        </EmptyState>
      ) : (
        <ul className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(260px,1fr))]">
          {filtered.map((s) => {
            const { name } = getDisplayName(s.operator_name || s.operator_name_snapshot, s.device_name_snapshot, s.identity_source);
            const device = devices.find((d) => d.id === s.device_id);
            const canView = !!onViewScreen && !!device && !device.revoked_at;
            return (
              <li key={s.id} className="rounded-xl border border-line bg-surface p-4 flex flex-col gap-3 hover:border-line-strong transition-colors">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold text-ink truncate">{name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <IdentityBadge source={s.identity_source} compact />
                      {s.identity_source === 'KPI Profile' && (
                        <span className="font-mono text-xs text-muted truncate">{s.device_name_snapshot}</span>
                      )}
                    </div>
                  </div>
                  <StatusBadge status={s.status || 'offline'} />
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                  <dt className="text-muted">Module</dt>
                  <dd className="text-ink truncate">{s.active_module || 'Dashboard'}</dd>
                  <dt className="text-muted">Heartbeat</dt>
                  <dd className="text-ink">{formatTimeAgo(s.last_seen_at)}</dd>
                  {s.status === 'idle' && s.idle_seconds > 0 && (
                    <>
                      <dt className="text-muted">Idle for</dt>
                      <dd className="text-amber-400 font-medium">{formatDuration(s.idle_seconds)}</dd>
                    </>
                  )}
                </dl>
                <div className="mt-auto flex gap-2">
                  {canView && (
                    <button onClick={() => onViewScreen!(device!)} className="btn btn-sm flex-1">
                      <Monitor className="w-4 h-4" aria-hidden="true" /> View screen
                    </button>
                  )}
                  <button
                    onClick={() => setSelected(s)}
                    className={`btn btn-sm ${canView ? '' : 'flex-1'}`}
                    title="Inspect session"
                  >
                    Details
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {selected && (
        <Modal
          isOpen={!!selected}
          onClose={() => setSelected(null)}
          title={`Session Details: ${selectedName}`}
          description={`Session ID: ${selected.id}`}
        >
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-canvas p-3">
              <div className="flex items-center gap-2">
                <StatusBadge status={selected.status || 'offline'} />
                <span className="text-muted">
                  in <strong className="text-ink font-semibold">{selected.active_module || 'Dashboard'}</strong>
                </span>
              </div>
              <IdentityBadge source={selected.identity_source} />
            </div>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                ['Operator', selected.operator_name || selected.operator_name_snapshot],
                ['Device', selected.device_name_snapshot],
                ['App version', selected.app_version || '—'],
                ['Idle for', formatDuration(selected.idle_seconds || 0)],
                ['Session started', formatDateTime(selected.started_at)],
                ['Last heartbeat', `${formatDateTime(selected.last_seen_at)} (${formatTimeAgo(selected.last_seen_at)})`],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-line p-3">
                  <dt className="text-xs font-medium text-muted">{label}</dt>
                  <dd className="mt-1 font-medium text-ink break-words">{value}</dd>
                </div>
              ))}
            </dl>
            <p className="flex gap-2 rounded-xl bg-accent-soft p-3 text-[13px] text-blue-300">
              <Info className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
              The operator name comes from the KPI profile saved on that PC. Without one, the Windows device name is shown.
            </p>
            <div className="flex justify-end">
              <button onClick={() => setSelected(null)} className="btn">
                Close
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
