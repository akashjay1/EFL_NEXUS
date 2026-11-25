import React, { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { ReconciliationJob } from '../types';
import { Card } from '../components/common/Card';
import { formatDateTime } from '../lib/status';

export const ReconciliationJobsPage: React.FC<{ refreshInterval: number; refreshKey: number }> = ({ refreshInterval, refreshKey }) => {
  const [jobs, setJobs] = useState<ReconciliationJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [assignment, setAssignment] = useState('all');
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await supabase.rpc('nexus_reconciliation_jobs');
        if (!active) return;
        if (result.error) setError(result.error.message);
        else { setJobs(result.data || []); setError(''); }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : 'Could not load reconciliation jobs.');
      } finally { if (active) setLoading(false); }
    };
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, Math.max(10, refreshInterval) * 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [refreshInterval, refreshKey]);

  const filtered = jobs.filter(job =>
    (status === 'all' || job.status === status) &&
    (assignment === 'all' || (assignment === 'assigned' ? !!job.assigned_user : !job.assigned_user)) &&
    [job.job_id, job.assigned_user, job.warehouse, job.client].some(value => value.toLowerCase().includes(query.trim().toLowerCase())));
  return (
    <Card title="Reconciliation Job IDs & Status" subtitle="Latest reported jobs from the last 7 days. Names come from submitted User KPI assignments.">
      <div className="flex flex-wrap gap-3 mb-4">
        <input aria-label="Search reconciliation jobs" placeholder="Search job, user, warehouse or client" value={query} onChange={e => setQuery(e.target.value)} className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 flex-1 min-w-56" />
        <select aria-label="Reconciliation status" value={status} onChange={e => setStatus(e.target.value)} className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100">
          <option value="all">All statuses</option>{['Pending', 'In Progress', 'Completed', 'Unknown'].map(s => <option key={s}>{s}</option>)}
        </select>
        <select aria-label="Assignment" value={assignment} onChange={e => setAssignment(e.target.value)} className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100">
          <option value="all">All assignments</option><option value="assigned">Assigned</option><option value="unassigned">Unassigned</option>
        </select>
      </div>
      {error && <p role="alert" className="text-red-400 mb-4">Could not refresh jobs: {error}. Previously loaded rows may be out of date.</p>}
      <p className="text-xs text-slate-400 mb-4">Jobs update while an updated desktop app has its reconciliation console open. Check “Portal updated” for freshness.</p>
      {loading ? <p role="status" className="text-slate-400">Loading reconciliation jobs…</p> :
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="text-slate-400 border-b border-slate-800"><tr>{['Assigned User', 'Job ID', 'Warehouse', 'Client', 'Reconciliation Status', 'Portal updated', 'Reporting device'].map(h => <th key={h} className="px-3 py-3 whitespace-nowrap">{h}</th>)}</tr></thead>
          <tbody>{filtered.map(job => <tr key={`${job.warehouse}:${job.job_id}`} className="border-b border-slate-800/60 text-slate-200">
            <td className="px-3 py-3">{job.assigned_user || <span className="text-slate-500">Unassigned</span>}</td>
            <td className="px-3 py-3 font-mono whitespace-nowrap">{job.job_id}</td><td className="px-3 py-3">{job.warehouse || '—'}</td><td className="px-3 py-3">{job.client || '—'}</td>
            <td className={`px-3 py-3 whitespace-nowrap ${job.status === 'Completed' ? 'text-emerald-400' : job.status === 'In Progress' ? 'text-amber-400' : job.status === 'Pending' ? 'text-red-400' : 'text-slate-400'}`}>{job.status}</td>
            <td className="px-3 py-3 whitespace-nowrap">{formatDateTime(job.observed_at)}</td><td className="px-3 py-3">{job.device_name}</td>
          </tr>)}</tbody>
        </table>{filtered.length === 0 && <p className="text-slate-400 py-8 text-center">{jobs.length ? 'No jobs match these filters.' : 'No reconciliation jobs have been reported yet.'}</p>}</div>}
      <p className="text-xs text-slate-500 mt-4">{filtered.length} of {jobs.length} jobs</p>
    </Card>
  );
};
