import { describe, it, expect } from 'vitest';
import {
  calculateOperatorStatus,
  getDisplayName,
  formatDuration,
  formatTimeAgo,
  formatBytes,
  DEFAULT_SETTINGS,
} from '../src/lib/status';
import { Session } from '../src/types';

describe('status and formatting helper tests', () => {
  const baseTime = Date.parse('2026-11-02T12:00:00Z');

  describe('calculateOperatorStatus', () => {
    const baseSession: Partial<Session> = {
      id: 'sess-1',
      device_id: 'dev-1',
      device_name_snapshot: 'OPERATOR-PC-01',
      operator_name_snapshot: 'Jane Doe',
      identity_source: 'KPI Profile',
      app_version: '3.12.0',
      active_module: 'Air Export',
      started_at: new Date(baseTime - 3600_000).toISOString(),
      last_seen_at: new Date(baseTime - 10_000).toISOString(),
      idle_seconds: 0,
      ended_at: null,
      end_reason: null,
    };

    it('returns revoked if revoked_at is present on device or session', () => {
      expect(calculateOperatorStatus({ ...baseSession, revoked_at: '2026-11-02T11:00:00Z' }, DEFAULT_SETTINGS, baseTime)).toBe('revoked');
      expect(calculateOperatorStatus({ ...baseSession, status: 'revoked' }, DEFAULT_SETTINGS, baseTime)).toBe('revoked');
    });

    it('returns closed if session has ended with closed reason', () => {
      expect(calculateOperatorStatus({
        ...baseSession,
        ended_at: new Date(baseTime - 100_000).toISOString(),
        end_reason: 'closed',
      }, DEFAULT_SETTINGS, baseTime)).toBe('closed');
    });

    it('returns offline if session has ended with unclean reason or null end_reason', () => {
      expect(calculateOperatorStatus({
        ...baseSession,
        ended_at: new Date(baseTime - 100_000).toISOString(),
        end_reason: 'unclean',
      }, DEFAULT_SETTINGS, baseTime)).toBe('offline');
      // Snapshot contract omits ended_at; retain its authoritative terminal status.
      expect(calculateOperatorStatus({
        ...baseSession, status: 'offline', last_seen_at: null,
      }, DEFAULT_SETTINGS, baseTime)).toBe('offline');
    });

    it('returns disconnected if last_seen_at is missing', () => {
      expect(calculateOperatorStatus({ ...baseSession, last_seen_at: null }, DEFAULT_SETTINGS, baseTime)).toBe('disconnected');
    });

    it('returns disconnected if last_seen_at exceeds disconnected_seconds threshold (180s)', () => {
      const staleTime = new Date(baseTime - 181_000).toISOString();
      expect(calculateOperatorStatus({ ...baseSession, last_seen_at: staleTime }, DEFAULT_SETTINGS, baseTime)).toBe('disconnected');
    });

    it('returns idle if idle_seconds exceeds idle threshold (300s)', () => {
      expect(calculateOperatorStatus({ ...baseSession, idle_seconds: 300 }, DEFAULT_SETTINGS, baseTime)).toBe('idle');
      expect(calculateOperatorStatus({ ...baseSession, idle_seconds: 450 }, DEFAULT_SETTINGS, baseTime)).toBe('idle');
    });

    it('returns active if last_seen_at is recent and idle_seconds is low', () => {
      expect(calculateOperatorStatus({ ...baseSession, idle_seconds: 45 }, DEFAULT_SETTINGS, baseTime)).toBe('active');
    });
  });

  describe('getDisplayName (Zero-Touch Operator Resolution)', () => {
    it('returns verified KPI operator name when identity_source is KPI Profile', () => {
      const res = getDisplayName('Alice Smith', 'DESKTOP-ABC', 'KPI Profile');
      expect(res.name).toBe('Alice Smith');
      expect(res.isFallback).toBe(false);
    });

    it('falls back to device name if identity_source is Device Fallback', () => {
      const res = getDisplayName(null, 'DESKTOP-ABC', 'Device Fallback');
      expect(res.name).toBe('DESKTOP-ABC');
      expect(res.isFallback).toBe(true);
    });

    it('falls back to device name if KPI operator name is whitespace or empty', () => {
      const res1 = getDisplayName('   ', 'WAREHOUSE-PC-02', 'KPI Profile');
      expect(res1.name).toBe('WAREHOUSE-PC-02');
      expect(res1.isFallback).toBe(true);

      const res2 = getDisplayName(null, 'WAREHOUSE-PC-02', 'KPI Profile');
      expect(res2.name).toBe('WAREHOUSE-PC-02');
      expect(res2.isFallback).toBe(true);
    });
  });

  describe('formatDuration', () => {
    it('formats seconds, minutes, and hours cleanly', () => {
      expect(formatDuration(0)).toBe('0s');
      expect(formatDuration(45)).toBe('45s');
      expect(formatDuration(65)).toBe('1m 5s');
      expect(formatDuration(3665)).toBe('1h 1m');
      expect(formatDuration(90000)).toBe('25h 0m');
    });
  });

  describe('formatTimeAgo', () => {
    it('formats relative elapsed time accurately', () => {
      expect(formatTimeAgo(new Date(baseTime - 2000).toISOString(), baseTime)).toBe('Just now');
      expect(formatTimeAgo(new Date(baseTime - 45_000).toISOString(), baseTime)).toBe('45s ago');
      expect(formatTimeAgo(new Date(baseTime - 120_000).toISOString(), baseTime)).toBe('2m ago');
      expect(formatTimeAgo(new Date(baseTime - 7200_000).toISOString(), baseTime)).toBe('2h ago');
      expect(formatTimeAgo(new Date(baseTime - 172800_000).toISOString(), baseTime)).toBe('2d ago');
      expect(formatTimeAgo(null, baseTime)).toBe('Never');
      expect(formatTimeAgo('invalid date', baseTime)).toBe('—');
    });
  });

  describe('formatBytes', () => {
    it('formats file sizes with units', () => {
      expect(formatBytes(0)).toBe('0 B');
      expect(formatBytes(1024)).toBe('1.0 KB');
      expect(formatBytes(1048576)).toBe('1.0 MB');
    });
  });
});
