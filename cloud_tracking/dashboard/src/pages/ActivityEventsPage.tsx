import React, { useState, useMemo } from 'react';
import { Search, Activity } from 'lucide-react';
import { SessionEvent } from '../types';
import { Card } from '../components/common/Card';
import { EmptyState } from '../components/common/LoadingSpinner';
import { formatTimeAgo, formatDateTime } from '../lib/status';
import { describeEvent } from '../lib/events';

interface ActivityEventsPageProps {
  events: SessionEvent[];
}

export const ActivityEventsPage: React.FC<ActivityEventsPageProps> = ({ events }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedEventType, setSelectedEventType] = useState('all');

  const uniqueEventTypes = useMemo(
    () => Array.from(new Set(events.map((e) => e.event_type).filter(Boolean))).sort(),
    [events]
  );

  const filteredEvents = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return events.filter((e) => {
      const matchesSearch =
        !query ||
        e.event_type.toLowerCase().includes(query) ||
        e.session_id.toLowerCase().includes(query) ||
        JSON.stringify(e.metadata || {}).toLowerCase().includes(query);
      const matchesType = selectedEventType === 'all' || e.event_type === selectedEventType;
      return matchesSearch && matchesType;
    });
  }, [events, searchQuery, selectedEventType]);

  return (
    <Card
      title={`Events (${filteredEvents.length})`}
      subtitle="Every lifecycle and module change reported by the desktops, newest first"
      bodyClassName="p-0"
      action={
        <div className="flex flex-col sm:flex-row gap-2">
          <label className="relative block sm:w-64">
            <span className="sr-only">Search events</span>
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter by event payload or session..."
              className="field pl-9"
            />
          </label>
          <label>
            <span className="sr-only">Event type</span>
            <select value={selectedEventType} onChange={(e) => setSelectedEventType(e.target.value)} className="field">
              <option value="all">All event types ({events.length})</option>
              {uniqueEventTypes.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </label>
        </div>
      }
    >
      {filteredEvents.length === 0 ? (
        <EmptyState icon={<Activity className="w-10 h-10" />} title="No events match these filters" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="px-5 py-3 font-semibold">Event</th>
                <th className="px-3 py-3 font-semibold">What happened</th>
                <th className="px-3 py-3 font-semibold">Session</th>
                <th className="px-3 py-3 font-semibold">Details</th>
                <th className="px-3 py-3 font-semibold">Time</th>
                <th className="px-5 py-3 font-semibold text-right">Received</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {filteredEvents.map((ev) => {
                const d = describeEvent(ev);
                return (
                  <tr key={ev.id} className="hover:bg-canvas">
                    <td className="px-5 py-3">
                      <span className="inline-flex items-center gap-1.5 rounded-md bg-canvas px-2 py-0.5 font-mono text-[11px] font-semibold text-ink-2">
                        <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${d.dot}`} />
                        {ev.event_type.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-ink first-letter:uppercase">{d.text}</td>
                    <td className="px-3 py-3 font-mono text-xs text-muted">
                      {ev.session_id.slice(0, 8)} · #{ev.sequence}
                    </td>
                    <td className="px-3 py-3">
                      {ev.metadata && Object.keys(ev.metadata).length > 0 ? (
                        <code className="rounded-md bg-canvas px-2 py-1 font-mono text-[11px] text-ink-2 break-all">
                          {JSON.stringify(ev.metadata)}
                        </code>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-ink-2 whitespace-nowrap">{formatDateTime(ev.event_timestamp)}</td>
                    <td className="px-5 py-3 text-right text-muted whitespace-nowrap">{formatTimeAgo(ev.received_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
};
