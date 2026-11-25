import React, { useCallback, useEffect, useState } from 'react';
import { Eye, RefreshCw } from 'lucide-react';
import { Card } from '../components/common/Card';
import { EmptyState, LoadingSpinner } from '../components/common/LoadingSpinner';
import { callAdminAction } from '../lib/supabase';
import { formatDateTime, formatDuration } from '../lib/status';
import { ScreenViewLogEntry } from '../types';

function viewOutcome(v: ScreenViewLogEntry): { label: string; cls: string } {
  if (!v.verified_at) return { label: 'Not answered', cls: 'bg-[#f2f4f7] text-[#475467]' };
  return { label: 'Viewed', cls: 'bg-[#eff4ff] text-[#1e40af]' };
}

export const ScreenAuditLog: React.FC = () => {
  const [rows, setRows] = useState<ScreenViewLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error: err } = await callAdminAction<{ result: ScreenViewLogEntry[] }>('screen_view_log', {});
    setLoading(false);
    if (err) {
      setError(
        err.startsWith('AAL2_REQUIRED')
          ? 'Turn on two-factor sign-in to see the screen-view log.'
          : 'The screen-view log could not be loaded.'
      );
      return;
    }
    setError(null);
    setRows(data?.result ?? []);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card
      title="Screen-view audit log"
      subtitle="Every live screen view, who started it and why. Entries cannot be edited or deleted from here."
      bodyClassName="p-0"
      action={
        <button onClick={load} disabled={loading} className="btn btn-sm">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" /> Refresh
        </button>
      }
    >
      {error ? (
        <p role="alert" className="p-5 text-sm text-red-400">
          {error}
        </p>
      ) : rows === null ? (
        <LoadingSpinner message="Loading screen views…" />
      ) : rows.length === 0 ? (
        <EmptyState icon={<Eye className="w-10 h-10" />} title="No screens have been viewed yet" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="px-5 py-3 font-semibold">When</th>
                <th className="px-3 py-3 font-semibold">Administrator</th>
                <th className="px-3 py-3 font-semibold">Device</th>
                <th className="px-3 py-3 font-semibold">Reason</th>
                <th className="px-3 py-3 font-semibold">Duration</th>
                <th className="px-5 py-3 font-semibold">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((v) => {
                const outcome = viewOutcome(v);
                const duration =
                  v.verified_at && v.ended_at
                    ? formatDuration(Math.max(0, Math.round((Date.parse(v.ended_at) - Date.parse(v.verified_at)) / 1000)))
                    : v.verified_at
                      ? 'Open or not closed cleanly'
                      : '—';
                return (
                  <tr key={v.id} className="hover:bg-canvas">
                    <td className="px-5 py-3 whitespace-nowrap text-ink-2">{formatDateTime(v.created_at)}</td>
                    <td className="px-3 py-3 text-ink">{v.admin_email}</td>
                    <td className="px-3 py-3 font-medium text-ink">{v.device_name}</td>
                    <td className="px-3 py-3 text-ink-2">{v.reason}</td>
                    <td className="px-3 py-3 text-muted whitespace-nowrap">{duration}</td>
                    <td className="px-5 py-3">
                      <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${outcome.cls}`}>{outcome.label}</span>
                    </td>
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
