import React, { useState } from 'react';
import { Card } from '../components/common/Card';
import { useAuth } from '../context/AuthContext';
import { SUPABASE_URL } from '../lib/supabase';
import {
  Settings,
  Clock,
  Globe,
  Database,
  Shield,
  Activity,
  CheckCircle2,
  Server,
} from 'lucide-react';

interface SettingsPageProps {
  refreshInterval: number;
  onUpdateRefreshInterval: (interval: number) => void;
}

export const SettingsPage: React.FC<SettingsPageProps> = ({
  refreshInterval,
  onUpdateRefreshInterval,
}) => {
  const { adminProfile, aalLevel } = useAuth();
  const [selectedTimezone, setSelectedTimezone] = useState<'local' | 'utc' | 'Asia/Colombo'>(() => {
    return (localStorage.getItem('efl_nexus_timezone') as 'local' | 'utc' | 'Asia/Colombo') || 'local';
  });

  const handleTimezoneChange = (tz: 'local' | 'utc' | 'Asia/Colombo') => {
    setSelectedTimezone(tz);
    localStorage.setItem('efl_nexus_timezone', tz);
  };

  return (
    <div className="space-y-6">
      {/* Dashboard Preferences */}
      <Card
        title="Dashboard Polling & Refresh"
        subtitle="Configure live monitoring polling intervals while dashboard is visible"
        icon={<Clock className="w-4 h-4" />}
      >
        <div className="space-y-4 text-xs">
          <div>
            <label className="block font-semibold text-slate-300 uppercase tracking-wider mb-2">
              Live Status Refresh Interval
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[10, 15, 30, 60].map((interval) => (
                <button
                  key={interval}
                  onClick={() => onUpdateRefreshInterval(interval)}
                  className={`p-3 rounded-xl border text-center font-medium transition-all ${
                    refreshInterval === interval
                      ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                  }`}
                >
                  <span className="block text-sm font-bold text-slate-200">{interval}s</span>
                  <span className="text-[10px] text-slate-500 mt-0.5 block">
                    {interval === 10 ? 'Default (Recommended)' : 'Custom Interval'}
                  </span>
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-500 mt-2">
              Note: The database also broadcasts live updates via Supabase Realtime when state transitions occur.
            </p>
          </div>

          <div className="pt-4 border-t border-slate-800">
            <label className="block font-semibold text-slate-300 uppercase tracking-wider mb-2">
              Timestamp Presentation
            </label>
            <div className="flex flex-col sm:flex-row gap-4">
              <label className="flex items-center gap-2 cursor-pointer text-slate-300">
                <input
                  type="radio"
                  name="timezone"
                  value="local"
                  checked={selectedTimezone === 'local'}
                  onChange={() => handleTimezoneChange('local')}
                  className="text-blue-600 focus:ring-blue-500"
                />
                <span>Local Browser Timezone ({Intl.DateTimeFormat().resolvedOptions().timeZone})</span>
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-slate-300">
                <input
                  type="radio"
                  name="timezone"
                  value="Asia/Colombo"
                  checked={selectedTimezone === 'Asia/Colombo'}
                  onChange={() => handleTimezoneChange('Asia/Colombo')}
                  className="text-blue-600 focus:ring-blue-500"
                />
                <span>Asia/Colombo (SLST, UTC+05:30)</span>
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-slate-300">
                <input
                  type="radio"
                  name="timezone"
                  value="utc"
                  checked={selectedTimezone === 'utc'}
                  onChange={() => handleTimezoneChange('utc')}
                  className="text-blue-600 focus:ring-blue-500"
                />
                <span>UTC (Coordinated Universal Time)</span>
              </label>
            </div>
          </div>
        </div>
      </Card>

      {/* Cloud & Endpoint Diagnostics */}
      <Card
        title="Cloud Telemetry Infrastructure"
        subtitle="Supabase PostgreSQL and Edge Function endpoint diagnostics"
        icon={<Database className="w-4 h-4" />}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-500 block text-[10px] uppercase font-semibold">
              Supabase Project URL
            </span>
            <span className="font-mono text-slate-300 break-all">{SUPABASE_URL}</span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-500 block text-[10px] uppercase font-semibold">
              Database Region
            </span>
            <span className="font-semibold text-emerald-400 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" />
              eu-west-1 (Ireland) • PostgreSQL 17.11
            </span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-500 block text-[10px] uppercase font-semibold">
              Backend Handlers (Edge Functions)
            </span>
            <span className="text-slate-300 block font-mono text-[11px]">
              /device-enroll • /device-telemetry • /admin-control
            </span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-500 block text-[10px] uppercase font-semibold">
              Realtime Channel
            </span>
            <span className="text-slate-300 block font-mono text-[11px]">
              nexus:monitoring (private broadcast)
            </span>
          </div>
        </div>
      </Card>

      {/* Administrator Profile Card */}
      <Card
        title="Administrator Profile"
        subtitle="Current authenticated identity"
        icon={<Shield className="w-4 h-4" />}
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-500 block text-[10px] uppercase font-semibold">
              Email Address
            </span>
            <span className="font-medium text-slate-200">{adminProfile?.email || '—'}</span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-500 block text-[10px] uppercase font-semibold">
              Administrative Role
            </span>
            <span className="font-bold text-blue-400 uppercase">{adminProfile?.role || 'admin'}</span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1">
            <span className="text-slate-500 block text-[10px] uppercase font-semibold">
              MFA Assurance Level
            </span>
            <span
              className={`font-bold ${
                aalLevel === 'aal2' ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {aalLevel ? aalLevel.toUpperCase() : 'AAL1'}
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
};
