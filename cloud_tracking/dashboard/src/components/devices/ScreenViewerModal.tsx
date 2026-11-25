import React, { useEffect, useId, useRef, useState } from 'react';
import { supabase, callAdminAction } from '../../lib/supabase';
import { Device } from '../../types';
import { X, Maximize2, Minimize2, Camera, Loader2, AlertCircle, Monitor, RefreshCw, ShieldCheck } from 'lucide-react';

interface ScreenViewerModalProps {
  device: Device | null;
  isOpen: boolean;
  onClose: () => void;
}

export const VIEW_REASONS = ['Operator asked for help', 'Troubleshooting a job', 'Checking a reported problem', 'Other'] as const;

/** Extracts the SHA-256 DTLS fingerprint from an SDP blob, upper-cased ("AB:CD:..."). */
export function sdpFingerprint(sdp: string | undefined): string | null {
  const m = /a=fingerprint:sha-256\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){31})/.exec(sdp ?? '');
  return m ? m[1].toUpperCase() : null;
}

type Phase = 'reason' | 'connecting' | 'negotiating' | 'streaming' | 'failed';

export const ScreenViewerModal: React.FC<ScreenViewerModalProps> = ({ device, isOpen, onClose }) => {
  const titleId = useId();
  const [phase, setPhase] = useState<Phase>('reason');
  const [reasonChoice, setReasonChoice] = useState<string>(VIEW_REASONS[0]);
  const [reasonOther, setReasonOther] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [fps, setFps] = useState(0);
  const [resolution, setResolution] = useState('—');
  const [isFullscreen, setIsFullscreen] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const channelRef = useRef<ReturnType<typeof supabase.channel> | null>(null);
  const viewIdRef = useRef<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamingRef = useRef(false);
  const frameCountRef = useRef(0);
  const lastFpsTimeRef = useRef(performance.now());
  const animFrameRef = useRef<number | null>(null);

  const reason = reasonChoice === 'Other' ? reasonOther.trim() : reasonChoice;

  // Reset to the reason step every time the viewer opens for a device.
  useEffect(() => {
    if (isOpen) {
      setPhase('reason');
      setErrorMessage(null);
      setAttempt(0);
    }
  }, [isOpen, device?.id]);

  useEffect(() => {
    if (!isOpen || !device || attempt === 0) return;

    let alive = true;
    streamingRef.current = false;
    setPhase('connecting');
    setErrorMessage(null);
    setFps(0);
    setResolution('—');

    const fail = (msg: string) => {
      if (!alive) return;
      streamingRef.current = false;
      setErrorMessage(msg);
      setPhase('failed');
    };

    const channel = supabase.channel(`nexus:screen:${device.id}`, { config: { broadcast: { self: false } } });
    channelRef.current = channel;

    const pc = new RTCPeerConnection({
      iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
      ],
    });
    pcRef.current = pc;

    const markStreaming = () => {
      streamingRef.current = true;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      if (alive) setPhase('streaming');
    };

    pc.ontrack = (event) => {
      if (videoRef.current && event.streams[0]) {
        videoRef.current.srcObject = event.streams[0];
        videoRef.current.play().catch(() => {});
        markStreaming();
      }
    };
    pc.onicecandidate = (event) => {
      if (event.candidate) {
        channel.send({
          type: 'broadcast',
          event: 'screen:ice_candidate',
          payload: {
            candidate: event.candidate.candidate,
            sdpMid: event.candidate.sdpMid,
            sdpMLineIndex: event.candidate.sdpMLineIndex,
            view_id: viewIdRef.current,
          },
        });
      }
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'connected') markStreaming();
      else if (pc.connectionState === 'failed') fail('A direct connection to this workstation could not be made.');
    };

    // The desktop may send ICE candidates before its answer: hold them until the answer is applied.
    const pendingIce: RTCIceCandidateInit[] = [];
    const addIce = async (c: RTCIceCandidateInit) => {
      try {
        await pc.addIceCandidate(new RTCIceCandidate(c));
      } catch {
        /* ignore stray candidates */
      }
    };

    channel
      .on('broadcast', { event: 'screen:answer' }, async ({ payload }) => {
        if (!alive || pc.signalingState !== 'have-local-offer') return;
        try {
          setPhase('negotiating');
          await pc.setRemoteDescription(new RTCSessionDescription(payload));
          for (const c of pendingIce.splice(0)) await addIce(c);
        } catch {
          fail('The workstation sent a video format this browser could not use.');
        }
      })
      .on('broadcast', { event: 'screen:ice_candidate' }, async ({ payload }) => {
        if (!alive || !payload?.candidate || payload.view_id) return; // skip our own echoed candidates
        if (!pc.remoteDescription) pendingIce.push(payload);
        else await addIce(payload);
      })
      .subscribe(async (subStatus) => {
        if (!alive || subStatus !== 'SUBSCRIBED') return;
        try {
          pc.addTransceiver('video', { direction: 'recvonly' });
          const offer = await pc.createOffer();
          await pc.setLocalDescription(offer);
          const fingerprint = sdpFingerprint(offer.sdp);
          if (!fingerprint) return fail('This browser did not produce a secure (DTLS SHA-256) offer.');

          // Ask the backend for a single-use view ticket bound to this browser's fingerprint.
          // The desktop only answers offers the backend confirms. This is also the audit record.
          const { data, error } = await callAdminAction<{ result: { view_id: string } }>('start_screen_view', {
            device_id: device.id,
            reason,
            fingerprint,
          });
          if (!alive) return;
          if (error || !data?.result?.view_id) {
            return fail(
              error?.startsWith('AAL2_REQUIRED')
                ? 'Two-factor sign-in is required to view screens. Turn it on under Admins & security.'
                : 'The screen view could not be authorised. Check the device is still enrolled and try again.'
            );
          }
          viewIdRef.current = data.result.view_id;
          await channel.send({
            type: 'broadcast',
            event: 'screen:request_offer',
            payload: { sdp: offer.sdp, type: offer.type, view_id: data.result.view_id },
          });
        } catch {
          fail('This browser could not start a video connection.');
        }
      });

    timeoutRef.current = setTimeout(() => {
      if (alive && !streamingRef.current) {
        fail('The workstation did not respond. Check it is online and running EFL NEXUS 1.1 or later.');
      }
    }, 20000);

    return () => {
      alive = false;
      teardown();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt, isOpen, device?.id]);

  // FPS / resolution readout while streaming.
  useEffect(() => {
    if (phase !== 'streaming') return;
    const tick = () => {
      const video = videoRef.current;
      if (video?.videoWidth) {
        setResolution(`${video.videoWidth} × ${video.videoHeight}`);
        frameCountRef.current++;
        const now = performance.now();
        const elapsed = now - lastFpsTimeRef.current;
        if (elapsed >= 1000) {
          setFps(Math.round((frameCountRef.current * 1000) / elapsed));
          frameCountRef.current = 0;
          lastFpsTimeRef.current = now;
        }
      }
      animFrameRef.current = requestAnimationFrame(tick);
    };
    animFrameRef.current = requestAnimationFrame(tick);
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [phase]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  function teardown() {
    streamingRef.current = false;
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    const viewId = viewIdRef.current;
    viewIdRef.current = null;
    if (channelRef.current) {
      try {
        channelRef.current.send({ type: 'broadcast', event: 'screen:stop_stream', payload: { view_id: viewId } });
      } catch {
        /* closing anyway */
      }
      supabase.removeChannel(channelRef.current);
      channelRef.current = null;
    }
    if (viewId) void callAdminAction('end_screen_view', { view_id: viewId });
    pcRef.current?.close();
    pcRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
  }

  const captureSnapshot = () => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')?.drawImage(video, 0, 0);
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = `screen-${device?.device_name || 'workstation'}-${new Date().toISOString().replace(/[:.]/g, '-')}.png`;
    a.click();
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {});
    }
  };

  if (!isOpen || !device) return null;

  const live = phase === 'streaming';

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="fixed inset-0 bg-[#101828]/55 backdrop-blur-[2px]" onClick={onClose} />
      <div className="flex min-h-full items-center justify-center p-3 sm:p-5">
        <div
          ref={containerRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          className={`w-full ${phase === 'reason' ? 'max-w-lg' : 'max-w-6xl'} overflow-hidden rounded-2xl bg-surface border border-line shadow-[0_24px_48px_rgba(16,24,40,0.2)] relative z-10 flex flex-col max-h-[94vh]`}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="p-2 rounded-xl bg-accent-soft text-accent">
                <Monitor className="w-5 h-5" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h3 id={titleId} className="text-base font-semibold text-ink truncate">
                    {device.device_name}
                  </h3>
                  {live && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-[#fee4e2] px-2 py-0.5 text-[11px] font-bold text-[#b42318]">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#f04438] motion-safe:animate-pulse" aria-hidden="true" />
                      LIVE · LOGGED
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted mt-0.5">
                  {phase === 'reason' ? 'Live screen view' : `Reason: ${reason} · ${resolution}`}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              {phase !== 'reason' && (
                <>
                  <button onClick={captureSnapshot} disabled={!live} className="btn btn-sm" title="Download a PNG snapshot">
                    <Camera className="w-4 h-4" aria-hidden="true" />
                    <span className="hidden sm:inline">Snapshot</span>
                  </button>
                  <button
                    onClick={toggleFullscreen}
                    className="p-2 rounded-lg text-muted hover:bg-canvas"
                    aria-label={isFullscreen ? 'Exit full screen' : 'Full screen'}
                  >
                    {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                  </button>
                </>
              )}
              <button onClick={onClose} className="p-2 rounded-lg text-muted hover:bg-canvas" aria-label="Close screen viewer">
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {phase === 'reason' ? (
            <form
              className="p-5 space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                if (reason.length >= 3) setAttempt((a) => a + 1);
              }}
            >
              <p className="flex gap-2 rounded-xl border border-[#b2ddff] bg-[#eff8ff] p-3 text-sm text-[#175cd3]">
                <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
                The operator sees a red banner while you watch, and this view is recorded in the audit log with your reason.
              </p>
              <div>
                <label htmlFor={`${titleId}-reason`} className="block text-sm font-semibold text-ink mb-1.5">
                  Reason for viewing
                </label>
                <select
                  id={`${titleId}-reason`}
                  value={reasonChoice}
                  onChange={(e) => setReasonChoice(e.target.value)}
                  className="field"
                >
                  {VIEW_REASONS.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </div>
              {reasonChoice === 'Other' && (
                <div>
                  <label htmlFor={`${titleId}-other`} className="block text-sm font-semibold text-ink mb-1.5">
                    Describe the reason
                  </label>
                  <input
                    id={`${titleId}-other`}
                    value={reasonOther}
                    onChange={(e) => setReasonOther(e.target.value)}
                    maxLength={200}
                    className="field"
                    placeholder="At least 3 characters"
                  />
                </div>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={onClose} className="btn">
                  Cancel
                </button>
                <button type="submit" disabled={reason.length < 3} className="btn btn-primary">
                  Start viewing
                </button>
              </div>
            </form>
          ) : (
            <>
              <div className="relative flex-1 bg-[#0b1220] flex items-center justify-center overflow-hidden min-h-[360px] max-h-[75vh]">
                <video ref={videoRef} autoPlay playsInline muted className={`w-full h-full object-contain ${live ? 'block' : 'hidden'}`} />
                {(phase === 'connecting' || phase === 'negotiating') && (
                  <div role="status" className="flex flex-col items-center gap-3 p-8 text-center text-[#d0d5dd]">
                    <Loader2 className="w-8 h-8 animate-spin text-[#84adff]" aria-hidden="true" />
                    <p className="text-sm font-semibold text-white">
                      {phase === 'connecting' ? 'Contacting the workstation…' : 'Starting the video…'}
                    </p>
                    <p className="text-xs max-w-sm">The workstation checks this request with the cloud before it shares its screen.</p>
                  </div>
                )}
                {phase === 'failed' && (
                  <div role="alert" className="flex flex-col items-center gap-3 p-8 text-center max-w-md">
                    <AlertCircle className="w-9 h-9 text-[#fda29b]" aria-hidden="true" />
                    <p className="text-sm font-semibold text-white">The screen view could not start</p>
                    <p className="text-sm text-[#d0d5dd]">{errorMessage}</p>
                    <button onClick={() => setAttempt((a) => a + 1)} className="btn btn-sm mt-1">
                      <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" /> Try again
                    </button>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 text-xs text-muted">
                <span className="flex items-center gap-1.5">
                  <span
                    aria-hidden="true"
                    className={`w-2 h-2 rounded-full ${live ? 'bg-[#16a34a]' : phase === 'failed' ? 'bg-[#f04438]' : 'bg-[#d97706]'}`}
                  />
                  {live ? `Streaming · ${fps} fps` : phase === 'failed' ? 'Stopped' : 'Connecting'} · Encrypted peer-to-peer
                </span>
                <button onClick={onClose} className="btn btn-sm btn-danger">
                  Stop viewing
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
