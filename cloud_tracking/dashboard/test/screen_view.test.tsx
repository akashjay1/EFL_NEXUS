import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { ScreenViewerModal, sdpFingerprint } from '../src/components/devices/ScreenViewerModal';
import * as SupabaseLib from '../src/lib/supabase';
import { tabFromHash } from '../src/App';
import { Device } from '../src/types';

const FP = Array.from({ length: 32 }, (_, i) => i.toString(16).padStart(2, '0')).join(':');
const OFFER_SDP = `v=0\r\na=fingerprint:sha-256 ${FP}\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n`;

const device: Device = {
  id: 'dev-1',
  installation_uuid: '11111111-1111-4111-8111-111111111111',
  device_name: 'OFFICE-PC-01',
  created_at: '2026-11-02T08:00:00Z',
  revoked_at: null,
};

class FakePeerConnection {
  signalingState = 'stable';
  connectionState = 'new';
  remoteDescription = null;
  ontrack: unknown = null;
  onicecandidate: unknown = null;
  onconnectionstatechange: unknown = null;
  addTransceiver = vi.fn();
  createOffer = vi.fn(async () => ({ type: 'offer', sdp: OFFER_SDP }));
  setLocalDescription = vi.fn(async () => {
    this.signalingState = 'have-local-offer';
  });
  close = vi.fn();
}

describe('secure screen viewing', () => {
  let sent: { event: string; payload: Record<string, unknown> }[];

  beforeEach(() => {
    sent = [];
    vi.stubGlobal('RTCPeerConnection', FakePeerConnection);
    const channel: any = {
      on: vi.fn(() => channel),
      subscribe: vi.fn((cb: (s: string) => void) => {
        cb('SUBSCRIBED');
        return channel;
      }),
      send: vi.fn(async (msg: { event: string; payload: Record<string, unknown> }) => {
        sent.push(msg);
      }),
    };
    vi.spyOn(SupabaseLib.supabase, 'channel').mockReturnValue(channel);
    vi.spyOn(SupabaseLib.supabase, 'removeChannel').mockResolvedValue('ok' as any);
  });

  afterEach(() => {
    cleanup(); // unmount (and tear down the channel) while the mocks still exist
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('extracts the SHA-256 DTLS fingerprint from SDP', () => {
    expect(sdpFingerprint(OFFER_SDP)).toBe(FP.toUpperCase());
    expect(sdpFingerprint('v=0\r\n')).toBeNull();
  });

  it('asks for a reason, gets a view ticket bound to the offer fingerprint, and only then sends the offer', async () => {
    const callAdmin = vi
      .spyOn(SupabaseLib, 'callAdminAction')
      .mockResolvedValue({ data: { result: { view_id: 'view-123' } } } as any);

    render(<ScreenViewerModal device={device} isOpen onClose={vi.fn()} />);

    // Nothing is requested before the admin gives a reason.
    expect(screen.getByLabelText(/reason for viewing/i)).toBeDefined();
    expect(callAdmin).not.toHaveBeenCalled();
    expect(sent).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: /start viewing/i }));

    await waitFor(() => {
      expect(callAdmin).toHaveBeenCalledWith('start_screen_view', {
        device_id: 'dev-1',
        reason: 'Operator asked for help',
        fingerprint: FP.toUpperCase(),
      });
      const offer = sent.find((m) => m.event === 'screen:request_offer');
      expect(offer?.payload.view_id).toBe('view-123');
      expect(offer?.payload.sdp).toBe(OFFER_SDP);
    });
  });

  it('does not send an offer when the backend refuses the view', async () => {
    vi.spyOn(SupabaseLib, 'callAdminAction').mockResolvedValue({ error: 'AAL2_REQUIRED: Two-factor' });

    render(<ScreenViewerModal device={device} isOpen onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /start viewing/i }));

    expect(await screen.findByText(/two-factor sign-in is required to view screens/i)).toBeDefined();
    expect(sent.find((m) => m.event === 'screen:request_offer')).toBeUndefined();
  });

  it('requires a typed reason when "Other" is chosen', () => {
    render(<ScreenViewerModal device={device} isOpen onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/reason for viewing/i), { target: { value: 'Other' } });
    const start = screen.getByRole('button', { name: /start viewing/i }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/describe the reason/i), { target: { value: 'Audit spot check' } });
    expect(start.disabled).toBe(false);
  });
});

describe('navigation', () => {
  it('maps old bookmarks to the merged pages', () => {
    expect(tabFromHash('#operators')).toBe('overview');
    expect(tabFromHash('#events')).toBe('sessions');
    expect(tabFromHash('#mfa')).toBe('admins');
    expect(tabFromHash('#devices')).toBe('devices');
    expect(tabFromHash('#nonsense')).toBe('overview');
  });
});
