"""Application-owned WebView2 lifecycle, embedding, and watchdog (Tk thread)."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

from whatsapp_gdn import GDNInboxStore
from whatsapp_grn import GRNInboxStore


BROWSER_TITLE = "EFL NEXUS - WhatsApp Browser"
RETRY_DELAYS = (2, 5, 15)


def helper_command(db_path, run_id, parent_pid):
    args = ["--whatsapp-browser", str(db_path), run_id, str(parent_pid)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(Path(__file__).with_name("whatsapp_monitor.py")), *args]


def native_window(pid):
    if os.name != "nt":
        raise RuntimeError("Embedded WhatsApp requires Windows WebView2.")
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    matches = []

    @callback_type
    def collect(hwnd, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(hwnd, title, len(title))
            if title.value == BROWSER_TITLE:
                matches.append(hwnd)
        return True

    user.EnumWindows(collect, 0)
    return matches[0] if matches else None


def attach_window(hwnd, host):
    """Same HWND reparenting approach used by Pending Jobs, isolated from its state."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowLongW.restype = ctypes.c_long
    user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user.SetParent.restype = wintypes.HWND
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user.ShowWindow(hwnd, 0)
    chrome = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000 | 0x80000000 | 0x01000000
    style = user.GetWindowLongW(hwnd, -16)
    user.SetWindowLongW(hwnd, -16, (style & ~chrome) | 0x40000000)
    user.SetWindowLongW(hwnd, -20, 0)
    user.SetWindowLongW(host, -16, user.GetWindowLongW(host, -16) | 0x02000000)
    user.SetParent(hwnd, host)
    if user.GetParent(hwnd) != host:
        raise OSError("Windows could not attach the WhatsApp browser to NEXUS.")
    user.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)



class WhatsAppController:
    def __init__(self, root, db_path=None, on_change=None, autostart=True):
        self.root = root
        self.store = GRNInboxStore(db_path)
        self.on_change = on_change
        self.process = None
        self.run_id = None
        self.hwnd = None
        self.host = None
        self.visible = False
        self.closed = False
        self.wanted = False
        self.retry_index = 0
        self.restart_at = None
        self.started_at = 0
        self.healthy_since = None
        self.after_id = None
        self.log_handle = None
        self.state = "Paused" if self.store.setting("group") else "Setup required"
        self.detail = "Open WhatsApp to sign in and choose your GDN group."
        self.new_count = self.store.counts()[1]
        self.grn_new_count = self.store.db.execute("SELECT count(*) FROM grn_documents WHERE action='New'").fetchone()[0]
        self.gap = self.store.setting("capture_gap", False)
        self.listeners = []
        self._last_notice = None
        self._destroy_binding = root.bind("<Destroy>", self._root_destroyed, add="+")
        if autostart and self.store.setting("enabled", False) and self.store.setting("group"):
            self.start()
        self.after_id = root.after(250, self._tick)

    def _root_destroyed(self, event):
        if event.widget is self.root:
            self.shutdown()

    def start(self):
        if self.closed:
            return
        self.wanted = True
        if self.process is not None and self.process.poll() is None:
            return
        self.retry_index = 0
        self.restart_at = None
        self._launch()

    def _launch(self):
        self.run_id = uuid.uuid4().hex
        self.started_at = time.monotonic()
        self.healthy_since = None
        self.state, self.detail = "Starting", "Opening the internal WhatsApp browser..."
        self.hwnd = None
        try:
            self.store.report(self.run_id, self.state, self.detail)
            if self.log_handle:
                self.log_handle.close()
            self.log_handle = open(self.store.path.parent / "browser.log", "w", encoding="utf-8")
            self.process = subprocess.Popen(
                helper_command(self.store.path, self.run_id, os.getpid()),
                stdout=self.log_handle, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, sqlite3.Error) as exc:
            self.process = None
            self._failed(f"Could not launch WhatsApp ({type(exc).__name__}). Check browser.log and WebView2 installation.")

    def select_group(self, import_visible=False):
        if self.store.setting("group") and self.store.setting("enabled", False):
            self.detail = "Pause monitoring before selecting or replacing the group."
            self._notify()
            return
        self.start()
        self.store.command(self.run_id, "select", import_visible=bool(import_visible))

    def pause(self):
        self.store.set_settings(enabled=False)
        if self.process is not None and self.process.poll() is None:
            self.store.command(self.run_id, "pause")
        self.state, self.detail = "Paused", "Monitoring is paused until you choose Resume."
        self._notify()

    def resume(self):
        if not self.store.setting("group"):
            self.state, self.detail = "Group selection required", "Sign in, open the group, then choose Use Open Group."
            self._notify()
            return
        self.store.set_settings(enabled=True)
        self.start()
        self.store.command(self.run_id, "resume")

    def reload(self):
        self.start()
        self.store.command(self.run_id, "reload")

    def acknowledge_gap(self):
        self.store.set_settings(capture_gap=False)
        self.gap = False
        if self.process is not None and self.process.poll() is None:
            self.store.command(self.run_id, "acknowledge_gap")
        self._notify()

    def set_host(self, host):
        self.host = host
        host.bind("<Configure>", lambda event: self.resize(), add="+")
        self._embed()

    def set_visible(self, visible):
        self.visible = bool(visible)
        if self.hwnd:
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user.ShowWindow(self.hwnd, 5 if self.visible else 0)
            if self.visible:
                self.resize()

    def resize(self):
        if self.hwnd and self.host is not None and self.host.winfo_exists():
            width, height = self.host.winfo_width(), self.host.winfo_height()
            if width < 300 or height < 200:
                return  # Unmapped tabs report 1x1; retain a useful background viewport.
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
            user.MoveWindow(self.hwnd, 0, 0, width, height, True)

    def _embed(self):
        if self.process is None or self.host is None or self.hwnd:
            return
        runtime = self.store.runtime(self.run_id)
        if not runtime or runtime["state"] in ("Starting", "Failed"):
            return  # Do not reparent WebView2 while its controller initializes.
        hwnd = native_window(self.process.pid)
        if hwnd:
            self.host.update_idletasks()
            attach_window(hwnd, int(self.host.winfo_id()))
            self.hwnd = hwnd
            self.resize()
            self.set_visible(self.visible)

    def _terminate(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process = None
        self.hwnd = None

    def _failed(self, detail):
        self._terminate()
        self.healthy_since = None
        if self.wanted and self.retry_index < len(RETRY_DELAYS):
            delay = RETRY_DELAYS[self.retry_index]
            self.retry_index += 1
            self.restart_at = time.monotonic() + delay
            self.state = "Reconnecting"
            self.detail = f"{detail} Retrying in {delay}s ({self.retry_index}/3)."
        else:
            self.restart_at = None
            self.state, self.detail = "Failed", detail + " Choose Reconnect to try again."

    def _notify(self):
        notice = (self.state, self.detail, self.new_count, self.grn_new_count, self.gap)
        if notice != self._last_notice:
            self._last_notice = notice
            if self.on_change:
                self.on_change(self)
            for listener in tuple(self.listeners):
                listener(self)

    def _tick(self):
        if self.closed:
            return
        try:
            self.new_count = self.store.counts()[1]
            self.grn_new_count = self.store.db.execute("SELECT count(*) FROM grn_documents WHERE action='New'").fetchone()[0]
            self.gap = self.store.setting("capture_gap", False)
            if self.restart_at is not None and time.monotonic() >= self.restart_at:
                self.restart_at = None
                self._launch()
            if self.process is not None:
                if self.process.poll() is not None:
                    self._failed("The internal WhatsApp browser closed unexpectedly.")
                else:
                    runtime = self.store.runtime(self.run_id)
                    if runtime:
                        self.state, self.detail = runtime["state"], runtime["detail"]
                        age = time.time() - runtime["heartbeat"]
                        grace = 60 if self.state == "Starting" else 15
                        if age > grace or (self.state == "Starting" and time.monotonic() - self.started_at > 60):
                            self._failed("The WhatsApp browser stopped responding.")
                        elif self.state == "Monitoring":
                            if self.healthy_since is None:
                                self.healthy_since = time.monotonic()
                            elif time.monotonic() - self.healthy_since >= 60:
                                self.retry_index = 0
                        else:
                            self.healthy_since = None
                    self._embed()
            self._notify()
        except (OSError, sqlite3.Error, RuntimeError) as exc:
            self.state, self.detail = "Unavailable", f"WhatsApp needs attention ({type(exc).__name__}). Open the WhatsApp page."
            self._notify()
        finally:
            if not self.closed:
                self.after_id = self.root.after(750, self._tick)

    def shutdown(self):
        if self.closed:
            return
        self.closed, self.wanted = True, False
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        try:
            if self.process is not None and self.process.poll() is None:
                self.store.command(self.run_id, "shutdown")
                deadline = time.monotonic() + 5
                # WinForms can send synchronous messages to its Tk parent while
                # closing. Keep Tk pumping rather than blocking it in wait().
                while self.process.poll() is None and time.monotonic() < deadline:
                    try:
                        self.root.update()
                    except Exception:
                        pass  # Parent may already be destroying its widgets.
                    time.sleep(.05)
                if self.process.poll() is None:
                    self._terminate()
        finally:
            if self.process is not None and self.process.poll() is None:
                self._terminate()
            self.store.close()
            if self.log_handle:
                self.log_handle.close()
            self.listeners.clear()
