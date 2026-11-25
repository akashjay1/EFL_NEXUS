import { SessionEvent } from '../types';

const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim() : null);

/** Plain-English description and colour for a telemetry event. */
export function describeEvent(ev: SessionEvent): { text: string; dot: string } {
  const m = ev.metadata ?? {};
  switch (ev.event_type) {
    case 'started':
      return { text: 'started a session', dot: 'bg-[#16a34a]' };
    case 'module_changed': {
      const to = str(m.to_module) ?? str(m.module);
      return { text: to ? `opened ${to}` : 'switched module', dot: 'bg-[#2563eb]' };
    }
    case 'operator_changed': {
      const who = str(m.operator_name);
      return { text: who ? `signed in as ${who}` : 'changed operator', dot: 'bg-[#7c3aed]' };
    }
    case 'closed':
      return { text: 'closed EFL NEXUS', dot: 'bg-[#98a2b3]' };
    case 'unclean':
      return { text: 'ended unexpectedly', dot: 'bg-[#f04438]' };
    case 'disconnected':
      return { text: 'lost connection', dot: 'bg-[#f04438]' };
    case 'reconnected':
      return { text: 'reconnected', dot: 'bg-[#16a34a]' };
    case 'recording_gap': {
      const n = typeof m.dropped_events === 'number' ? m.dropped_events : null;
      return { text: n ? `had a recording gap (${n} events dropped)` : 'had a recording gap', dot: 'bg-[#d97706]' };
    }
    default:
      return { text: String(ev.event_type).replace(/_/g, ' '), dot: 'bg-[#98a2b3]' };
  }
}
