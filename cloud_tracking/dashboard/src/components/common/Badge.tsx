import React from 'react';
import { OperatorStatus, IdentitySource } from '../../types';

type Tone = { label: string; pill: string; dot: string; pulse?: boolean };

const STATUS_TONES: Record<string, Tone> = {
  active: { label: 'Active', pill: 'bg-[#dcfce7] text-[#166534]', dot: 'bg-[#16a34a]', pulse: true },
  idle: { label: 'Idle', pill: 'bg-[#fef3c7] text-[#92400e]', dot: 'bg-[#d97706]' },
  disconnected: { label: 'Disconnected', pill: 'bg-[#fee4e2] text-[#b42318]', dot: 'bg-[#f04438]' },
  closed: { label: 'Closed', pill: 'bg-[#eff4ff] text-[#1e40af]', dot: 'bg-[#2563eb]' },
  revoked: { label: 'Revoked', pill: 'bg-[#f2f4f7] text-[#475467]', dot: 'bg-[#98a2b3]' },
  offline: { label: 'Offline', pill: 'bg-[#f2f4f7] text-[#475467]', dot: 'bg-[#98a2b3]' },
};

export function statusTone(status: OperatorStatus | string): Tone {
  const key = status.toLowerCase();
  if (key === 'online') return STATUS_TONES.active;
  return STATUS_TONES[key] ?? STATUS_TONES.offline;
}

export const StatusDot: React.FC<{ status: OperatorStatus | string; className?: string }> = ({ status, className = '' }) => {
  const tone = statusTone(status);
  return <span aria-hidden="true" className={`inline-block w-2 h-2 rounded-full ${tone.dot} ${className}`} />;
};

export const StatusBadge: React.FC<{ status: OperatorStatus | string }> = ({ status }) => {
  const tone = statusTone(status);
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold whitespace-nowrap ${tone.pill}`}>
      <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${tone.dot} ${tone.pulse ? 'motion-safe:animate-pulse' : ''}`} />
      {tone.label}
    </span>
  );
};

export const IdentityBadge: React.FC<{ source: IdentitySource | string; compact?: boolean }> = ({
  source,
  compact = false,
}) => {
  const size = compact ? 'text-[11px] px-1.5' : 'text-xs px-2';
  if (source === 'KPI Profile') {
    return (
      <span
        title="Name taken from the operator's KPI profile on the desktop"
        className={`inline-flex items-center gap-1 py-0.5 rounded-md font-medium bg-[#eef2ff] text-[#3730a3] ${size}`}
      >
        KPI Profile
      </span>
    );
  }
  return (
    <span
      title="No KPI profile on this PC: the Windows device name is shown instead"
      className={`inline-flex items-center gap-1 py-0.5 rounded-md font-medium bg-[#f2f4f7] text-[#475467] ${size}`}
    >
      Device Fallback
    </span>
  );
};
