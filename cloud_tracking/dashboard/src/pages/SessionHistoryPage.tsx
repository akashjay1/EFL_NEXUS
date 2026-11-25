import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Session, SessionEvent, IdentitySource } from '../types';
import { Card } from '../components/common/Card';
import { Modal } from '../components/common/Modal';
import { IdentityBadge } from '../components/common/Badge';
import { formatTimeAgo, formatDateTime, formatDuration, getDisplayName } from '../lib/status';
import { supabase } from '../lib/supabase';
import {
  History,
  Search,
  Filter,
  Download,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Eye,
  Activity,
  Laptop,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Clock,
  Layers,
} from 'lucide-react';

interface SessionHistoryPageProps {
  initialSessions: Session[];
}

export const SessionHistoryPage: React.FC<SessionHistoryPageProps> = ({ initialSessions }) => {
  const [sessions, setSessions] = useState<Session[]>(initialSessions);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedOutcome, setSelectedOutcome] = useState('all');
  const [selectedDevice, setSelectedDevice] = useState('all');
  const [page, setPage] = useState(1);
  const pageSize = 20;

  // Selected session for timeline modal
  const [timelineSession, setTimelineSession] = useState<Session | null>(null);
  const [timelineEvents, setTimelineEvents] = useState<SessionEvent[]>([]);
  const [isLoadingEvents, setIsLoadingEvents] = useState(false);

  // Fetch complete sessions from public.sessions
  const loadSessions = useCallback(async () => {
    setIsLoading(true);
    try {
      const { data, error } = await supabase
        .from('sessions')
        .select('*')
        .order('started_at', { ascending: false })
        .limit(200);

      if (!error && data) {
        setSessions(data as Session[]);
      }
    } catch {
      // Fallback to initial
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // Load ordered events for session timeline modal
  const handleOpenTimeline = async (session: Session) => {
    setTimelineSession(session);
    setIsLoadingEvents(true);
    setTimelineEvents([]);

    try {
      const { data, error } = await supabase
        .from('session_events')
        .select('*')
        .eq('session_id', session.id)
        .order('sequence', { ascending: true });

      if (!error && data) {
        setTimelineEvents(data as SessionEvent[]);
      }
    } catch {
      // Handle error
    } finally {
      setIsLoadingEvents(false);
    }
  };

  // Extract unique devices
  const uniqueDevices = useMemo(() => {
    const set = new Set<string>();
    sessions.forEach((s) => {
      if (s.device_name_snapshot) set.add(s.device_name_snapshot);
    });
    return Array.from(set).sort();
  }, [sessions]);

  // Filtered sessions
  const filteredSessions = useMemo(() => {
    return sessions.filter((s) => {
      const { name } = getDisplayName(
        s.operator_name_snapshot,
        s.device_name_snapshot,
        s.identity_source
      );

      const query = searchQuery.trim().toLowerCase();
      const matchesSearch =
        !query ||
        name.toLowerCase().includes(query) ||
        s.device_name_snapshot.toLowerCase().includes(query) ||
        (s.active_module && s.active_module.toLowerCase().includes(query));

      const outcome = s.ended_at ? s.end_reason || 'closed' : 'active';
      const matchesOutcome =
        selectedOutcome === 'all' ||
        (selectedOutcome === 'active' && !s.ended_at) ||
        (selectedOutcome === 'closed' && s.end_reason === 'closed') ||
        (selectedOutcome === 'unclean' && s.end_reason === 'unclean') ||
        (selectedOutcome === 'revoked' && s.end_reason === 'revoked');

      const matchesDevice =
        selectedDevice === 'all' || s.device_name_snapshot === selectedDevice;

      return matchesSearch && matchesOutcome && matchesDevice;
    });
  }, [sessions, searchQuery, selectedOutcome, selectedDevice]);

  // Pagination
  const totalPages = Math.ceil(filteredSessions.length / pageSize) || 1;
  const paginatedSessions = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredSessions.slice(start, start + pageSize);
  }, [filteredSessions, page, pageSize]);

  // Export to CSV
  const handleExportCsv = () => {
    const headers = [
      'Session ID',
      'Operator Name',
      'Identity Source',
      'Device Name',
      'Active Module',
      'App Version',
      'Started At',
      'Ended At',
      'Outcome',
      'Last Seen At',
      'Idle Seconds',
    ];

    const rows = filteredSessions.map((s) => [
      s.id,
      s.operator_name_snapshot,
      s.identity_source,
      s.device_name_snapshot,
      s.active_module,
      s.app_version,
      s.started_at,
      s.ended_at || '',
      s.ended_at ? s.end_reason || 'closed' : 'active',
      s.last_seen_at || '',
      s.idle_seconds || 0,
    ]);

    const csvContent =
      'data:text/csv;charset=utf-8,' +
      [headers.join(','), ...rows.map((e) => e.map((val) => `"${val}"`).join(','))].join('\n');

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `efl_nexus_sessions_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const renderOutcomeBadge = (session: Session) => {
    if (!session.ended_at) {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 inline-flex items-center gap-1">
          <Activity className="w-3 h-3" />
          Active
        </span>
      );
    }

    switch (session.end_reason) {
      case 'closed':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 inline-flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" />
            Normal Exit
          </span>
        );
      case 'unclean':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 inline-flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            Crash / Force Kill
          </span>
        );
      case 'revoked':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-red-500/10 text-red-400 border border-red-500/20 inline-flex items-center gap-1">
            <XCircle className="w-3 h-3" />
            Hardware Revoked
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">
            Ended
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Search, Filter & CSV Export */}
      <Card className="p-4">
        <div className="flex flex-col lg:flex-row gap-4 justify-between items-center">
          {/* Search Input */}
          <div className="relative w-full lg:w-80">
            <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(1);
              }}
              placeholder="Search historical sessions..."
              className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-10 pr-4 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Filters & Export */}
          <div className="flex flex-wrap items-center gap-3 w-full lg:w-auto">
            {/* Outcome Filter */}
            <select
              value={selectedOutcome}
              onChange={(e) => {
                setSelectedOutcome(e.target.value);
                setPage(1);
              }}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
            >
              <option value="all">All Outcomes</option>
              <option value="active">Active Sessions</option>
              <option value="closed">Normal Exits (closed)</option>
              <option value="unclean">Crashes / Terminations (unclean)</option>
              <option value="revoked">Revoked</option>
            </select>

            {/* Device Filter */}
            <select
              value={selectedDevice}
              onChange={(e) => {
                setSelectedDevice(e.target.value);
                setPage(1);
              }}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
            >
              <option value="all">All Devices ({uniqueDevices.length})</option>
              {uniqueDevices.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>

            {/* CSV Export Button */}
            <button
              onClick={handleExportCsv}
              className="bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium py-1.5 px-3.5 rounded-lg text-xs transition-colors flex items-center gap-2 border border-slate-700 shadow-sm"
              title="Export filtered records to CSV"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export CSV</span>
            </button>
          </div>
        </div>
      </Card>

      {/* Main Historical Table */}
      <Card
        title={`Historical Sessions (${filteredSessions.length})`}
        subtitle="Complete audit trail of desktop application lifecycle events"
      >
        {paginatedSessions.length === 0 ? (
          <div className="text-center py-16 text-slate-500 text-xs">
            No session history records found matching your filters.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 uppercase text-[10px] tracking-wider">
                  <th className="py-3.5 pr-4 font-semibold">Operator</th>
                  <th className="py-3.5 pr-4 font-semibold">Device</th>
                  <th className="py-3.5 pr-4 font-semibold">Module</th>
                  <th className="py-3.5 pr-4 font-semibold">Started</th>
                  <th className="py-3.5 pr-4 font-semibold">Duration</th>
                  <th className="py-3.5 pr-4 font-semibold">Outcome</th>
                  <th className="py-3.5 text-right font-semibold">Timeline</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {paginatedSessions.map((session) => {
                  const { name } = getDisplayName(
                    session.operator_name_snapshot,
                    session.device_name_snapshot,
                    session.identity_source
                  );

                  // Calculate duration
                  const startMs = Date.parse(session.started_at);
                  const endMs = session.ended_at
                    ? Date.parse(session.ended_at)
                    : session.last_seen_at
                    ? Date.parse(session.last_seen_at)
                    : Date.now();
                  const durationSec = Math.max(0, Math.floor((endMs - startMs) / 1000));

                  return (
                    <tr
                      key={session.id}
                      className="hover:bg-slate-800/40 transition-colors group cursor-pointer"
                      onClick={() => handleOpenTimeline(session)}
                    >
                      {/* Operator Name & Source */}
                      <td className="py-3.5 pr-4">
                        <div className="font-semibold text-slate-200">{name}</div>
                        <div className="mt-1">
                          <IdentityBadge source={session.identity_source} compact />
                        </div>
                      </td>

                      {/* Device */}
                      <td className="py-3.5 pr-4">
                        <span className="font-mono text-[11px] text-slate-300">
                          {session.device_name_snapshot}
                        </span>
                        <span className="text-[10px] text-slate-500 block">
                          v{session.app_version || '5.2.0'}
                        </span>
                      </td>

                      {/* Module */}
                      <td className="py-3.5 pr-4">
                        <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">
                          {session.active_module || 'Dashboard'}
                        </span>
                      </td>

                      {/* Started */}
                      <td className="py-3.5 pr-4 text-slate-300">
                        <div>{formatDateTime(session.started_at)}</div>
                        <div className="text-[10px] text-slate-500">
                          {formatTimeAgo(session.started_at)}
                        </div>
                      </td>

                      {/* Duration */}
                      <td className="py-3.5 pr-4 text-slate-200 font-mono">
                        {formatDuration(durationSec)}
                      </td>

                      {/* Outcome */}
                      <td className="py-3.5 pr-4">{renderOutcomeBadge(session)}</td>

                      {/* Actions */}
                      <td className="py-3.5 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenTimeline(session);
                          }}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-blue-400 hover:bg-slate-800 transition-colors"
                          title="View Ordered Event Timeline"
                        >
                          <Eye className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Controls */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between pt-5 mt-4 border-t border-slate-800 text-xs text-slate-400">
            <span>
              Page {page} of {totalPages} ({filteredSessions.length} total sessions)
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="p-1.5 rounded-lg border border-slate-800 hover:bg-slate-800 disabled:opacity-40 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
                className="p-1.5 rounded-lg border border-slate-800 hover:bg-slate-800 disabled:opacity-40 transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </Card>

      {/* Ordered Event Timeline Modal */}
      {timelineSession && (
        <Modal
          isOpen={!!timelineSession}
          onClose={() => setTimelineSession(null)}
          title={`Session Timeline: ${timelineSession.operator_name_snapshot}`}
          description={`Hardware: ${timelineSession.device_name_snapshot} • Session: ${timelineSession.id}`}
          maxWidth="xl"
        >
          <div className="space-y-4 text-xs">
            {isLoadingEvents ? (
              <div className="text-center py-10 text-slate-400">
                Loading contiguous session events...
              </div>
            ) : timelineEvents.length === 0 ? (
              <div className="text-center py-10 text-slate-500">
                No events recorded for this session yet.
              </div>
            ) : (
              <div className="relative pl-6 space-y-4 before:content-[''] before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
                {timelineEvents.map((ev) => (
                  <div key={ev.id} className="relative">
                    {/* Timeline bullet */}
                    <span className="absolute -left-6 top-1 w-2.5 h-2.5 rounded-full bg-blue-500 border-2 border-slate-900" />

                    <div className="p-3 rounded-xl bg-slate-950 border border-slate-800/80 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[10px] font-bold uppercase text-blue-400 tracking-wider">
                          Seq #{ev.sequence} • {ev.event_type}
                        </span>
                        <span className="text-[10px] text-slate-500">
                          {formatDateTime(ev.event_timestamp)}
                        </span>
                      </div>

                      {/* Payload metadata */}
                      {ev.metadata && Object.keys(ev.metadata).length > 0 && (
                        <div className="pt-1.5 border-t border-slate-850 mt-1.5">
                          <pre className="text-[10px] font-mono text-slate-300 overflow-x-auto p-2 bg-slate-900/80 rounded border border-slate-800/60">
                            {JSON.stringify(ev.metadata, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="flex justify-end pt-3">
              <button
                onClick={() => setTimelineSession(null)}
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold"
              >
                Close
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
