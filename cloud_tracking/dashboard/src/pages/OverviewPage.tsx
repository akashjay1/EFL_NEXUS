import React, { useMemo, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { SnapshotData, Session, SessionEvent, NavigationTab, Device } from '../types';
import { MetricCard, Card } from '../components/common/Card';
import { WorkstationBoard } from '../components/operators/WorkstationBoard';
import { ScreenViewerModal } from '../components/devices/ScreenViewerModal';
import { formatTimeAgo, getDisplayName } from '../lib/status';
import { describeEvent } from '../lib/events';

interface OverviewPageProps {
  snapshot: SnapshotData | null;
  activeSessions: Session[];
  recentEvents: SessionEvent[];
  sessionsTodayCount?: number | null;
  onNavigate: (tab: NavigationTab) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({
  snapshot,
  activeSessions,
  recentEvents,
  sessionsTodayCount,
  onNavigate,
}) => {
  const devices = snapshot?.devices || [];
  const [deviceToView, setDeviceToView] = useState<Device | null>(null);

  const enrolled = devices.filter((d) => !d.revoked_at).length;
  const active = activeSessions.filter((s) => s.status === 'active').length;
  const idle = activeSessions.filter((s) => s.status === 'idle').length;
  const offline = activeSessions.filter((s) => s.status === 'disconnected').length;
  const working = active + idle;

  const modules = useMemo(() => {
    const counts: Record<string, number> = {};
    activeSessions
      .filter((s) => s.status === 'active' || s.status === 'idle')
      .forEach((s) => {
        const m = s.active_module || 'Dashboard';
        counts[m] = (counts[m] || 0) + 1;
      });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [activeSessions]);

  const sessionById = useMemo(() => new Map(activeSessions.map((s) => [s.id, s])), [activeSessions]);

  return (
    <div className="space-y-6">
      <section aria-label="Summary" className="grid gap-4 grid-cols-2 lg:grid-cols-5">
        <MetricCard title="Active now" value={active} subtitle="Working in the last 5 min" color="green" />
        <MetricCard title="Idle" value={idle} subtitle="No input for 5+ min" color="amber" />
        <MetricCard title="Offline" value={offline} subtitle="Heartbeat lost" color={offline > 0 ? 'red' : 'green'} />
        <MetricCard title="Sessions today" value={sessionsTodayCount ?? '—'} subtitle="Since 00:00 local" color="purple" />
        <MetricCard title="Enrolled devices" value={enrolled} subtitle="Not revoked" color="blue" />
      </section>

      <Card title="Workstations" subtitle="Who is on which PC, and what they are doing right now">
        <WorkstationBoard sessions={activeSessions} devices={devices} onViewScreen={setDeviceToView} />
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card
          title="Recent activity"
          subtitle="Latest events from all workstations"
          action={
            <button onClick={() => onNavigate('sessions')} className="btn btn-sm">
              All activity <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
            </button>
          }
          bodyClassName="px-5 py-2"
        >
          {recentEvents.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted">No activity recorded yet</p>
          ) : (
            <ol className="divide-y divide-line">
              {recentEvents.slice(0, 6).map((ev) => {
                const s = sessionById.get(ev.session_id);
                const who = s
                  ? getDisplayName(s.operator_name || s.operator_name_snapshot, s.device_name_snapshot, s.identity_source).name
                  : 'A workstation';
                const d = describeEvent(ev);
                return (
                  <li key={ev.id} className="flex gap-3 py-3">
                    <span aria-hidden="true" className={`mt-1.5 w-2 h-2 shrink-0 rounded-full ${d.dot}`} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink">
                        <span className="font-semibold">{who}</span> {d.text}
                      </p>
                      <p className="text-xs text-muted mt-0.5">
                        {s ? `${s.device_name_snapshot} · ` : ''}
                        {formatTimeAgo(ev.event_timestamp)}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </Card>

        <Card title="Work by module" subtitle="Open sessions per tool">
          {modules.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted">No modules in use right now</p>
          ) : (
            <ul className="space-y-4">
              {modules.map(([name, count]) => {
                const pct = Math.round((count / Math.max(1, working)) * 100);
                return (
                  <li key={name}>
                    <div className="flex justify-between gap-3 text-sm mb-1.5">
                      <span className="font-medium text-ink truncate">{name}</span>
                      <span className="text-muted tabular-nums whitespace-nowrap">
                        {count} session{count > 1 ? 's' : ''}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-[#eaecf0] overflow-hidden" role="presentation">
                      <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <ScreenViewerModal device={deviceToView} isOpen={!!deviceToView} onClose={() => setDeviceToView(null)} />
    </div>
  );
};
