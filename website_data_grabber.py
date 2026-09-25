"""Tool 6: extract job IDs from an authorised reconciliation web page.

Credentials are deliberately kept in the Tk variables only; this module never
writes them to disk or logs them.  Selenium opens a visible browser so an
operator can complete SSO/MFA when a portal requires it.
"""

from __future__ import annotations

import csv
import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any


_HEADER_WORDS = ("job id", "jobid", "job number", "job no", "job #")

# Confirmed from the authorised portal screenshots supplied for this tool.
DEFAULT_LOGIN_URL = "https://active.efl3plofc.com/login"
DEFAULT_RECONCILIATION_URL = "https://active.efl3plofc.com/clerk-dashboard?job_type=OUTBOUND"
DEFAULT_REFRESH_SECONDS = 5
WINDOWS_CREDENTIAL_TARGET = "EFL_NEXUS:WebsiteDataGrabber"
DEFAULT_SOUND_FILE = Path(__file__).resolve().parent / "assets" / "pending_alert.mp3"


def play_notification_sound(sound_path: str | Path | None = None) -> bool:
    """Plays an alert sound (MP3, WAV, etc.) asynchronously using Windows MCI.

    Falls back to winsound.PlaySound or winsound.MessageBeep if MCI fails.
    Never blocks the caller and suppresses playback errors.
    """
    if sys.platform != "win32":
        return False

    def _worker():
        try:
            target: Path | None = None
            if sound_path:
                candidate = Path(sound_path)
                if candidate.is_file():
                    target = candidate
            if target is None and DEFAULT_SOUND_FILE.is_file():
                target = DEFAULT_SOUND_FILE

            if target and target.is_file():
                abs_str = str(target.resolve())
                winmm = ctypes.windll.winmm
                # Stop and close any previous alias to avoid device busy errors
                winmm.mciSendStringW("stop nexus_pending_alert", None, 0, 0)
                winmm.mciSendStringW("close nexus_pending_alert", None, 0, 0)

                # Attempt opening with type mpegvideo for mp3/wav
                cmd = f'open "{abs_str}" type mpegvideo alias nexus_pending_alert'
                ret = winmm.mciSendStringW(cmd, None, 0, 0)
                if ret != 0:
                    cmd = f'open "{abs_str}" alias nexus_pending_alert'
                    ret = winmm.mciSendStringW(cmd, None, 0, 0)

                if ret == 0:
                    winmm.mciSendStringW("play nexus_pending_alert from 0", None, 0, 0)
                    return

            # Fallback to system notification chime if audio file playback was not possible
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        except Exception as exc:
            print(f"[WebsiteDataGrabber] Sound playback exception: {exc}")

    threading.Thread(target=_worker, daemon=True).start()
    return True


def parse_refresh_seconds(value: Any, default: int = DEFAULT_REFRESH_SECONDS) -> int:
    """Parse auto-refresh seconds from user input, config, or presets.

    Returns 0 when disabled ('Off', 'manual', '0', etc.), or positive integer seconds.
    """
    if value is None:
        return default
    cleaned = str(value).strip().casefold()
    if cleaned in ("off", "manual", "none", "disable", "disabled", "0"):
        return 0
    digits = re.sub(r"[^\d]", "", cleaned)
    if not digits:
        return default
    try:
        return max(0, int(digits))
    except ValueError:
        return default


def _load_saved_password() -> str:
    """Read the Tool 6 password from the current user's Windows vault."""
    try:
        import win32cred
        credential = win32cred.CredRead(WINDOWS_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
        blob = credential.get("CredentialBlob", b"")
        return blob.decode("utf-16-le") if isinstance(blob, bytes) else str(blob)
    except Exception:
        return ""


def _save_password(password: str, username: str) -> None:
    """Store the password in Windows Credential Manager, never config.json."""
    import win32cred
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": WINDOWS_CREDENTIAL_TARGET,
        "UserName": username,
        "CredentialBlob": password,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "EFL NEXUS Tool 6 Website Data Grabber",
        "Attributes": [],
    }, 0)


def _clear_saved_password() -> None:
    try:
        import win32cred
        win32cred.CredDelete(WINDOWS_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception:
        pass


def _result_file() -> Path:
    """Return the local, non-secret hand-off file used by the WebView helper."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "EFL_NEXUS" / "website_grabber_results.json"


def _browser_log_file() -> Path:
    """Return the diagnostic log file for the internal browser subprocess."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "EFL_NEXUS" / "website_grabber_browser.log"


def _command_file() -> Path:
    """Return the IPC command file used to send actions from Tool 6 UI to the browser helper."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "EFL_NEXUS" / "website_grabber_command.json"


def _download_event_file() -> Path:
    """Return the local IPC file used to notify Tool 6 UI of downloaded files."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "EFL_NEXUS" / "website_grabber_downloads.json"


def _loading_history_event_file() -> Path:
    """Return the IPC file for Loading History requests made on a job-detail page."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "EFL_NEXUS" / "website_grabber_loading_history.json"


def _loading_history_command_file() -> Path:
    """Return the IPC command file used to send actions from Tool 6 / reconciliation to Loading History browser."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "EFL_NEXUS" / "loading_history_command.json"


def _job_map_file() -> Path:
    """Return the persistent job mapping file that remembers warf_id -> job details across sessions."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "EFL_NEXUS" / "website_grabber_job_map.json"


def load_persisted_job_map(custom_path: Path | None = None) -> dict[str, dict[str, str]]:
    """Load persistent dictionary mapping job_id and warf_id to job records."""
    p = custom_path or _job_map_file()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def update_persisted_job_map(records: list[dict[str, Any]], custom_path: Path | None = None) -> None:
    """Persist job metadata across sessions so warf_id routes map to real job identifiers."""
    if not records:
        return
    p = custom_path or _job_map_file()
    existing = load_persisted_job_map(p)
    changed = False
    for r in records:
        if not isinstance(r, dict):
            continue
        jid = str(r.get("job_id") or "").strip()
        wid = str(r.get("warf_id") or "").strip()
        gp = str(r.get("gatepass") or "").strip()
        cli = str(r.get("client") or "").strip()
        item = {
            "job_id": jid,
            "warf_id": wid,
            "gatepass": gp,
            "client": cli,
            "status": str(r.get("status") or "").strip(),
            "warehouse": str(r.get("warehouse") or "").strip(),
        }
        if jid:
            existing[jid.casefold()] = item
            changed = True
        if wid:
            existing[wid.casefold()] = item
            changed = True
    if changed:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except Exception:
            pass


def get_downloads_folder() -> Path:
    """Return the user's standard Windows Downloads directory."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ) as key:
                downloads = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
                p = Path(downloads)
                if p.is_dir():
                    return p
        except Exception:
            pass
    fallback = Path.home() / "Downloads"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_job_download_folder(
    job_id: str = "",
    gatepass: str = "",
    client: str = "",
    base_folder: Path | None = None,
) -> Path:
    """Return the destination subfolder under the Downloads directory for a job.

    Naming format: {job_id}_{gatepass}_{client}
    Example: OUT_0000007081_728069_KTI
    Gracefully falls back when gatepass or client is missing, or falls back
    to base_downloads if no job ID is specified.
    """
    base_downloads = base_folder or get_downloads_folder()

    def _clean_component(val: Any) -> str:
        s = str(val or "").strip()
        # Remove characters forbidden in Windows directories: < > : " / \\ | ? * and control chars
        s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
        # Collapse whitespace and repeated underscores
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"_+", "_", s)
        # Strip leading/trailing dots, spaces, underscores
        s = s.strip(" ._")
        return s

    clean_job = _clean_component(job_id)
    clean_gp = _clean_component(gatepass)
    clean_client = _clean_component(client)

    # If clean_job is purely numeric (e.g. portal route 16561), attempt resolution from job map
    if clean_job and re.fullmatch(r"\d+", clean_job):
        job_map = load_persisted_job_map()
        mapped = job_map.get(clean_job.casefold())
        if mapped:
            real_j = _clean_component(mapped.get("job_id", ""))
            if real_j and not re.fullmatch(r"\d+", real_j):
                clean_job = real_j
            if not clean_gp or clean_gp.upper() in ("NA", "N_A", "NONE", "-", "_"):
                clean_gp = _clean_component(mapped.get("gatepass", ""))
            if not clean_client or clean_client.upper() in ("NA", "N_A", "NONE", "-", "_"):
                clean_client = _clean_component(mapped.get("client", ""))

    parts: list[str] = []
    if clean_job:
        if re.fullmatch(r"\d+", clean_job) and not clean_gp and not clean_client:
            parts.append(f"JOB_{clean_job}")
        else:
            parts.append(clean_job)

    if clean_gp and clean_gp.upper() not in ("NA", "N_A", "NONE", "-", "_"):
        parts.append(clean_gp)

    if clean_client and clean_client.upper() not in ("NA", "N_A", "NONE", "-", "_"):
        parts.append(clean_client)

    if parts:
        folder_name = "_".join(parts)
        target_dir = base_downloads / folder_name
    else:
        target_dir = base_downloads

    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def get_unique_download_path(filename: str, folder: Path | None = None) -> Path:
    """Return a non-colliding file path in the target folder by appending (1), (2), etc."""
    target_folder = folder or get_downloads_folder()
    target_folder.mkdir(parents=True, exist_ok=True)
    clean_name = re.sub(r'[<>:"/\\|?*]', '_', filename or "").strip()
    if not clean_name:
        clean_name = "downloaded_file"
    base = Path(clean_name).stem
    suffix = Path(clean_name).suffix
    candidate = target_folder / clean_name
    counter = 1
    while candidate.exists():
        candidate = target_folder / f"{base} ({counter}){suffix}"
        counter += 1
    return candidate


def _write_results(path: Path, job_ids: list[str], records: list[dict[str, str]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"job_ids": job_ids}
    if records:
        payload["records"] = records
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle)
        temporary_name = handle.name
    temp_p = Path(temporary_name)
    for attempt in range(5):
        try:
            temp_p.replace(path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            import time
            time.sleep(0.05)


class ResultsBridge:
    """JS-to-Python bridge exposed to the embedded WebView2 browser."""

    def __init__(self, cmd_path: Path, result_path: Path | None = None):
        self.cmd_path = cmd_path
        self.result_path = result_path
        self._known_records: dict[str, dict[str, str]] = {}
        for k, v in load_persisted_job_map().items():
            if isinstance(v, dict):
                self._known_records[k.casefold()] = v

    def save_job_ids(self, values):
        records: list[dict[str, str]] = []
        unique_ids: list[str] = []
        seen: set[str] = set()
        for item in values if isinstance(values, list) else []:
            if isinstance(item, dict):
                raw_id = _clean(str(item.get("job_id", "")))
                raw_client = _clean(str(item.get("client", "")))
                raw_status = _clean(str(item.get("status", "")))
                raw_wh = _clean(str(item.get("warehouse", "")))
                raw_gp = _clean(str(item.get("gatepass", "")))
                raw_seal = _clean(str(item.get("seal", "")))
                raw_deliv = _clean(str(item.get("delivery_location", "")))
                raw_warf = _clean(str(item.get("warf_id", "")))
            else:
                raw_id = _clean(str(item))
                raw_client = ""
                raw_status = ""
                raw_wh = ""
                raw_gp = ""
                raw_seal = ""
                raw_deliv = ""
                raw_warf = ""
            if not raw_id:
                continue
            key = raw_id.casefold()
            if key in seen:
                continue
            seen.add(key)
            norm_status = normalize_reconciliation_status(raw_status)
            rec = {
                "job_id": raw_id,
                "client": raw_client,
                "status": norm_status,
                "warehouse": raw_wh,
                "gatepass": raw_gp,
                "seal": raw_seal,
                "delivery_location": raw_deliv,
                "warf_id": raw_warf,
            }
            records.append(rec)
            self._known_records[key] = rec
            if raw_warf:
                self._known_records[raw_warf.casefold()] = rec
            unique_ids.append(raw_id)
        if self.result_path:
            _write_results(self.result_path, unique_ids, records)
        update_persisted_job_map(records)
        print(f"\n[WebsiteDataGrabber] Bridge received {len(values) if isinstance(values, list) else 0} raw item(s), parsed {len(unique_ids)} unique Job ID(s): {', '.join(unique_ids[:5])}{'...' if len(unique_ids) > 5 else ''}", flush=True)
        for r in records[:10]:
            print(f"  [WebsiteDataGrabber] Job: {r.get('job_id')} | Client: {r.get('client', '')} | Gatepass: {r.get('gatepass', '')} | Status: {r.get('status', '')}", flush=True)
        if len(records) > 10:
            print(f"  [WebsiteDataGrabber] ... and {len(records) - 10} more jobs.", flush=True)
        return {"count": len(unique_ids)}

    def _lookup_job_record(self, key_or_id: str) -> dict[str, str] | None:
        """Lookup full record by Job ID or numeric Warf ID from memory or disk cache."""
        if not key_or_id:
            return None
        target = str(key_or_id).strip().casefold()
        if target in self._known_records:
            return self._known_records[target]
        persisted = load_persisted_job_map()
        if target in persisted:
            self._known_records[target] = persisted[target]
            return persisted[target]
        for path_candidate in (self.result_path, _result_file()):
            if path_candidate and path_candidate.exists():
                try:
                    payload = json.loads(path_candidate.read_text(encoding="utf-8"))
                    recs = payload.get("records")
                    if isinstance(recs, list):
                        for r in recs:
                            if isinstance(r, dict):
                                jid = str(r.get("job_id") or "").strip().casefold()
                                wid = str(r.get("warf_id") or "").strip().casefold()
                                if jid:
                                    self._known_records[jid] = r
                                if wid:
                                    self._known_records[wid] = r
                                if target and (target == jid or target == wid):
                                    return r
                except Exception:
                    pass
        return None

    def lookup_warf_job(self, warf_id: str) -> dict[str, str]:
        """Allow the browser JavaScript to resolve job context for a warf route."""
        rec = self._lookup_job_record(warf_id)
        if rec:
            return {
                "job_id": str(rec.get("job_id") or "").strip(),
                "gatepass": str(rec.get("gatepass") or "").strip(),
                "client": str(rec.get("client") or "").strip(),
            }
        return {"job_id": "", "gatepass": "", "client": ""}

    def _lookup_job_metadata(self, job_id: str) -> tuple[str, str]:
        """Return (gatepass, client) for the given job_id from memory or disk cache."""
        rec = self._lookup_job_record(job_id)
        if rec:
            return (str(rec.get("gatepass") or "").strip(), str(rec.get("client") or "").strip())
        return ("", "")

    def save_downloaded_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        import base64
        from urllib.parse import unquote, urlparse
        try:
            raw_filename = str(payload.get("filename") or "").strip()
            b64_data = payload.get("data") or ""
            url = str(payload.get("url") or "")
            raw_job_id = str(payload.get("job_id") or "").strip()
            gatepass = str(payload.get("gatepass") or "").strip()
            client = str(payload.get("client") or "").strip()

            if isinstance(b64_data, str):
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                file_bytes = base64.b64decode(b64_data)
            elif isinstance(b64_data, bytes):
                file_bytes = b64_data
            else:
                return {"success": False, "error": "Invalid data format"}

            job_id = raw_job_id
            rec = self._lookup_job_record(raw_job_id)
            if rec:
                real_job_id = str(rec.get("job_id") or "").strip()
                if real_job_id:
                    job_id = real_job_id
                if not gatepass:
                    gatepass = str(rec.get("gatepass") or "").strip()
                if not client:
                    client = str(rec.get("client") or "").strip()
            elif job_id and (not gatepass or not client):
                found_gp, found_cli = self._lookup_job_metadata(job_id)
                if not gatepass:
                    gatepass = found_gp
                if not client:
                    client = found_cli

            # Intelligent fallback: inspect Excel metadata if job_id is still numeric or gatepass/client missing
            if (not gatepass or not client or re.fullmatch(r"\d+", job_id)) and file_bytes and file_bytes.startswith(b"PK\x03\x04"):
                try:
                    import io, openpyxl
                    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
                    ws = wb.active
                    r_iter = ws.iter_rows(values_only=True)
                    hdr = [str(h or "").strip().lower() for h in next(r_iter, [])]
                    first_row = next(r_iter, None)
                    if first_row:
                        r_vals = [str(v or "").strip() for v in first_row]
                        gp_idx = next((i for i, h in enumerate(hdr) if "gate" in h and "pass" in h), None)
                        if gp_idx is not None and gp_idx < len(r_vals) and not gatepass:
                            gatepass = r_vals[gp_idx]
                        cli_idx = next((i for i, h in enumerate(hdr) if any(k in h for k in ("cust", "client", "customer"))), None)
                        if cli_idx is not None and cli_idx < len(r_vals) and not client:
                            client = r_vals[cli_idx]
                except Exception:
                    pass

            target_folder = get_job_download_folder(job_id=job_id, gatepass=gatepass, client=client)

            if not raw_filename or raw_filename.lower() in ("download", "file", ""):
                if url:
                    parsed = unquote(urlparse(url).path.split("/")[-1])
                    if parsed:
                        raw_filename = parsed
            if not raw_filename:
                raw_filename = f"job_{job_id}_file.xlsx" if job_id else "downloaded_file"

            raw_filename = raw_filename.split("?")[0].split("#")[0].strip()
            target_path = get_unique_download_path(raw_filename, folder=target_folder)
            target_path.write_bytes(file_bytes)

            try:
                dl_event_file = _download_event_file()
                dl_event_file.parent.mkdir(parents=True, exist_ok=True)
                dl_event_file.write_text(json.dumps({
                    "action": "file_downloaded",
                    "filename": target_path.name,
                    "path": str(target_path.resolve()),
                    "folder": target_path.parent.name,
                    "folder_path": str(target_path.parent.resolve()),
                    "size": len(file_bytes),
                    "time": time.time(),
                    "job_id": job_id,
                    "gatepass": gatepass,
                    "client": client,
                }), encoding="utf-8")
            except Exception:
                pass

            return {
                "success": True,
                "filename": target_path.name,
                "path": str(target_path.resolve()),
                "folder": target_path.parent.name,
                "folder_path": str(target_path.parent.resolve()),
                "size": len(file_bytes),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def request_loading_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Pass the current job-detail context to the parent Tool 6 window and Loading History."""
        try:
            context = payload if isinstance(payload, dict) else {}
            event_file = _loading_history_event_file()
            event_file.parent.mkdir(parents=True, exist_ok=True)
            jid = _clean(str(context.get("job_id") or ""))
            gp = _clean(str(context.get("gatepass") or ""))
            cli = _clean(str(context.get("client") or ""))
            if not gp and jid:
                rec = self._lookup_job_record(jid)
                if rec:
                    gp = _clean(str(rec.get("gatepass") or ""))
                    if not cli:
                        cli = _clean(str(rec.get("client") or ""))
            if not gp and jid:
                persisted = load_persisted_job_map()
                mapped = persisted.get(jid.casefold())
                if mapped:
                    gp = _clean(str(mapped.get("gatepass") or ""))
                    if not cli:
                        cli = _clean(str(mapped.get("client") or ""))
            if not gp:
                try:
                    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                    res_file = base / "EFL_NEXUS" / "website_grabber_results.json"
                    if res_file.exists():
                        res_data = json.loads(res_file.read_text(encoding="utf-8"))
                        records = res_data.get("records") if isinstance(res_data, dict) else res_data
                        if isinstance(records, list):
                            for item in reversed(records):
                                item_jid = _clean(str(item.get("job_id") or ""))
                                item_gp = _clean(str(item.get("gatepass") or ""))
                                item_cli = _clean(str(item.get("client") or ""))
                                if (jid and item_jid.casefold() == jid.casefold()) or not jid:
                                    if not gp and item_gp:
                                        gp = item_gp
                                    if not jid and item_jid:
                                        jid = item_jid
                                    if not cli and item_cli:
                                        cli = item_cli
                                    if gp:
                                        break
                except Exception:
                    pass

            event_file.write_text(json.dumps({
                "action": "open_loading_history",
                "time": time.time(),
                "job_id": jid,
                "gatepass": gp,
                "client": cli,
            }), encoding="utf-8")

            if gp:
                try:
                    cmd_file = _loading_history_command_file()
                    cmd_file.parent.mkdir(parents=True, exist_ok=True)
                    cmd_file.write_text(json.dumps({
                        "action": "query_and_export",
                        "time": time.time(),
                        "job_id": jid,
                        "gatepass": gp,
                        "client": cli,
                    }), encoding="utf-8")
                except Exception:
                    pass

            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_pending_command(self):
        try:
            if self.cmd_path.exists():
                text = self.cmd_path.read_text(encoding="utf-8")
                self.cmd_path.unlink(missing_ok=True)
                return json.loads(text)
        except Exception:
            pass
        return None


def run_internal_browser(result_path: Path, start_url: str = DEFAULT_LOGIN_URL) -> None:
    """Run an application-owned Edge WebView2 browser for Tool 6.

    This function is started in a separate process because WebView2 and Tk
    each own their UI event loop. pywebview's Edge backend uses the installed
    WebView2 runtime and private mode by default.
    """
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception as err:
        sys.stderr.write(f"Failed to import 'webview' in internal browser helper: {err}\n")
        sys.stderr.flush()
        raise

    start_url = start_url or DEFAULT_LOGIN_URL
    username = os.environ.pop("EFL_NEXUS_GRABBER_USER", "")
    password = os.environ.pop("EFL_NEXUS_GRABBER_PASS", "")
    reconciliation_url = os.environ.pop("EFL_NEXUS_GRABBER_RECON_URL", DEFAULT_RECONCILIATION_URL)
    try:
        refresh_seconds = parse_refresh_seconds(os.environ.pop("EFL_NEXUS_GRABBER_REFRESH_SECONDS", str(DEFAULT_REFRESH_SECONDS)), default=DEFAULT_REFRESH_SECONDS)
    except Exception:
        refresh_seconds = DEFAULT_REFRESH_SECONDS

    bridge = ResultsBridge(_command_file(), result_path=result_path)
    window = webview.create_window(
        "EFL NEXUS — Reconciliation Browser",
        start_url,
        js_api=bridge,
        width=1560,
        height=920,
        min_size=(1000, 680),
        zoomable=True,
    )

    def add_extract_button():
        recon_url_js = json.dumps(reconciliation_url or DEFAULT_RECONCILIATION_URL)
        window.run_js(f"""
            (() => {{
              const reconUrl = {recon_url_js};
              const isReconciliationPage = () => {{
                try {{
                  const path = (location.pathname || '').toLowerCase();
                  const href = (location.href || '').toLowerCase();
                  if (path.includes('login') || path.includes('/warf/start')) return false;
                  if (path.includes('clerk-dashboard') || href.includes('clerk-dashboard') ||
                      path.includes('reconciliation') || href.includes('reconciliation') ||
                      path.includes('dashboard') || href.includes('dashboard') ||
                      href.includes('job_type=outbound') || href.includes('job_type=') ||
                      path.includes('pending') || href.includes('pending')) return true;
                  const allTables = [...document.querySelectorAll('table')];
                  return allTables.some(t => {{
                    const txt = (t.textContent || '').toLowerCase().replace(/[^a-z0-9]/g, '');
                    if (txt.includes('jobid') || txt.includes('jobnumber') || txt.includes('jobno')) return true;
                    return /\b(?:out|in)_[a-z0-9_-]+/i.test(t.textContent || '');
                  }});
                }} catch (e) {{
                  return false;
                }}
              }};

              const extractJobRecords = () => {{
                const allTables = [...document.querySelectorAll('table')];
                const getHeaders = (table) => {{
                  let ths = [...table.querySelectorAll('thead th')];
                  if (!ths.length) ths = [...table.querySelectorAll('tr th')];
                  if (!ths.length) {{
                    const firstRow = table.querySelector('tr');
                    if (firstRow) ths = [...firstRow.querySelectorAll('th, td')];
                  }}
                  return ths.map(h => h.textContent.trim().toLowerCase().replace(/[^a-z0-9]/g, ''));
                }};
                let targetTable = null;
                let jobColIndex = -1;
                let clientColIndex = -1;
                let statusColIndex = -1;
                let whColIndex = -1;
                let gatepassColIndex = -1;
                let sealColIndex = -1;
                let deliveryColIndex = -1;
                for (const t of allTables) {{
                  const headers = getHeaders(t);
                  let jIdx = headers.findIndex(h => ['jobid', 'jobnumber', 'jobno', 'job', 'job#'].includes(h) || h.includes('jobid'));
                  let rows = [...t.querySelectorAll('tbody tr')];
                  if (!rows.length) {{
                    const allTrs = [...t.querySelectorAll('tr')];
                    rows = allTrs.length > 1 ? allTrs.slice(1) : allTrs;
                  }}
                  // Resilient fallback: if headers don't clearly state Job ID, inspect cell values for OUT_ or IN_
                  if (jIdx < 0 && rows.length > 0) {{
                    const sampleRows = rows.slice(0, 10);
                    const colMatches = {{}};
                    sampleRows.forEach(row => {{
                      const cells = [...row.querySelectorAll('td, th')];
                      cells.forEach((cell, cIdx) => {{
                        const val = cell.textContent.trim();
                        if (/\b(?:OUT|IN)_[A-Za-z0-9_-]+\b/i.test(val)) {{
                          colMatches[cIdx] = (colMatches[cIdx] || 0) + 1;
                        }}
                      }});
                    }});
                    const bestCol = Object.entries(colMatches).sort((a, b) => b[1] - a[1])[0];
                    if (bestCol && bestCol[1] > 0) {{
                      jIdx = parseInt(bestCol[0], 10);
                    }}
                  }}
                  if (jIdx >= 0) {{
                    targetTable = t;
                    jobColIndex = jIdx;
                    whColIndex = headers.findIndex(h => ['wh', 'warehouse', 'warehouseid', 'whid'].includes(h) || h === 'wh' || h.startsWith('wh'));
                    clientColIndex = headers.findIndex(h => ['client', 'customer', 'clientname', 'account', 'clientid'].includes(h) || h.includes('client'));
                    statusColIndex = headers.findIndex(h => ['reconciliationstatus', 'status', 'reconstatus', 'jobstatus', 'state'].includes(h) || h.includes('reconciliation') || h.includes('status'));
                    gatepassColIndex = headers.findIndex(h => ['gatepass', 'gatepassno', 'gatepassnumber', 'gatepassid', 'gp', 'gpno'].includes(h) || h.includes('gatepass'));
                    sealColIndex = headers.findIndex(h => ['sealnumber', 'sealno', 'seal', 'seal#'].includes(h) || h.includes('seal'));
                    deliveryColIndex = headers.findIndex(h => ['deliverylocation', 'delivery', 'destination', 'deliveryto'].includes(h) || h.includes('delivery'));
                    break;
                  }}
                }}
                if (!targetTable || jobColIndex < 0) return null;
                let rows = [...targetTable.querySelectorAll('tbody tr')];
                if (!rows.length) {{
                  const allTrs = [...targetTable.querySelectorAll('tr')];
                  rows = allTrs.length > 1 ? allTrs.slice(1) : allTrs;
                }}
                const values = [];
                for (const row of rows) {{
                  const cells = row.querySelectorAll('td, th');
                  if (jobColIndex >= cells.length) continue;
                  const jobVal = cells[jobColIndex] ? cells[jobColIndex].textContent.trim() : '';
                  if (!jobVal) continue;
                  let clientVal = '';
                  if (clientColIndex >= 0 && clientColIndex < cells.length && cells[clientColIndex]) {{
                    clientVal = cells[clientColIndex].textContent.trim();
                  }}
                  let stVal = '';
                  if (statusColIndex >= 0 && statusColIndex < cells.length && cells[statusColIndex]) {{
                    stVal = cells[statusColIndex].textContent.trim();
                  }}
                  if (!stVal) {{
                    const statusCell = [...cells].find(cell => /\\b(?:pending|(?:on\\s+|in\\s+)?progress)\\b/i.test(cell.textContent || ''));
                    if (statusCell) stVal = statusCell.textContent.trim();
                  }}
                  let whVal = '';
                  if (whColIndex >= 0 && whColIndex < cells.length && cells[whColIndex]) {{
                    whVal = cells[whColIndex].textContent.trim();
                  }}
                  let gatepassVal = '';
                  if (gatepassColIndex >= 0 && gatepassColIndex < cells.length && cells[gatepassColIndex]) {{
                    gatepassVal = cells[gatepassColIndex].textContent.trim();
                  }}
                  let sealVal = '';
                  if (sealColIndex >= 0 && sealColIndex < cells.length && cells[sealColIndex]) {{
                    sealVal = cells[sealColIndex].textContent.trim();
                  }}
                  let deliveryVal = '';
                  if (deliveryColIndex >= 0 && deliveryColIndex < cells.length && cells[deliveryColIndex]) {{
                    deliveryVal = cells[deliveryColIndex].textContent.trim();
                  }}
                  let warfId = '';
                  const warfForm = row.querySelector("form[action*='/warf/start'], a[href*='/warf/start'], form[action*='/warf/'], a[href*='/warf/'], form[action*='/warf']");
                  if (warfForm) {{
                    const act = warfForm.getAttribute('action') || warfForm.getAttribute('href') || '';
                    const m = act.match(/\\/warf\\/(?:start\\/)?(\\d+)/i);
                    if (m && m[1]) warfId = m[1];
                  }}
                  if (warfId && jobVal) {{
                    try {{
                      localStorage.setItem('nexus_warf_' + warfId, JSON.stringify({{
                        job_id: jobVal,
                        gatepass: gatepassVal,
                        client: clientVal,
                      }}));
                    }} catch (e) {{}}
                  }}
                  const startBtn = row.querySelector("button.btn-start, button[type='submit'], form button");
                  if (startBtn && !startBtn.hasAttribute('data-nexus-bound')) {{
                    startBtn.setAttribute('data-nexus-bound', '1');
                    startBtn.addEventListener('click', () => {{
                      try {{
                        sessionStorage.setItem('nexus_active_job_id', jobVal);
                        sessionStorage.setItem('nexus_active_gatepass', gatepassVal);
                        sessionStorage.setItem('nexus_active_client', clientVal);
                        sessionStorage.setItem('nexus_active_warf_id', warfId);
                        localStorage.setItem('nexus_active_job_id', jobVal);
                        localStorage.setItem('nexus_active_gatepass', gatepassVal);
                        localStorage.setItem('nexus_active_client', clientVal);
                        localStorage.setItem('nexus_active_warf_id', warfId);
                      }} catch (e) {{}}
                    }});
                  }}
                  values.push({{
                    job_id: jobVal,
                    client: clientVal,
                    status: stVal,
                    warehouse: whVal,
                    gatepass: gatepassVal,
                    seal: sealVal,
                    delivery_location: deliveryVal,
                    warf_id: warfId
                  }});
                }}
                return values;
              }};

              let lastExportSignature = '';
              let isExporting = false;

              const autoExportJobIds = async (isManual = false) => {{
                if (isExporting || !isReconciliationPage()) return false;
                if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.save_job_ids !== 'function') {{
                  if (isManual) alert('Connection to Tool 6 is initializing. Please wait a moment and click again.');
                  return false;
                }}
                const records = extractJobRecords();
                if (!records) {{
                  if (isManual) alert('No table with a recognizable Job ID column was found on this page.');
                  return false;
                }}
                const signature = JSON.stringify(records);
                if (!isManual && signature === lastExportSignature) return true;
                isExporting = true;
                try {{
                  const resp = await window.pywebview.api.save_job_ids(records);
                  lastExportSignature = signature;
                  const count = resp && resp.count !== undefined ? resp.count : records.length;
                  const btn = document.getElementById('efl-nexus-extract-job-ids');
                  if (btn) {{
                    const syncLabel = (refreshInterval > 0) ? `Auto: ${{refreshInterval}}s` : 'Manual';
                    btn.textContent = `✓ Synced ${{count}} Jobs (${{syncLabel}})`;
                  }}
                  return true;
                }} catch (e) {{
                  if (isManual) alert('Error sending Job IDs to Tool 6: ' + e);
                  return false;
                }} finally {{
                  isExporting = false;
                }}
              }};

              let refreshInterval = {refresh_seconds};
              let refreshSeconds = refreshInterval;
              let autoRefreshPaused = refreshInterval <= 0;

              // ---------------- Zoom Control for Full Table View ----------------
              let reconZoom = parseFloat(localStorage.getItem('nexus_recon_zoom') || '0.85');
              if (isNaN(reconZoom) || reconZoom < 0.5 || reconZoom > 1.5) {{
                reconZoom = 0.85;
              }}

              const applyReconZoom = () => {{
                try {{
                  const onRecon = isReconciliationPage();
                  if (document.body) {{
                    if (onRecon) {{
                      document.body.style.setProperty('zoom', reconZoom.toString(), 'important');
                    }} else if (document.body.style.zoom && document.body.style.zoom !== '1') {{
                      document.body.style.removeProperty('zoom');
                    }}
                  }}
                  const zoomLabel = document.getElementById('efl-nexus-zoom-level');
                  if (zoomLabel) {{
                    zoomLabel.textContent = `${{Math.round(reconZoom * 100)}}%`;
                  }}
                  const zoomWidget = document.getElementById('efl-nexus-zoom-widget');
                  if (zoomWidget) {{
                    zoomWidget.style.display = onRecon ? 'flex' : 'none';
                  }}
                }} catch (e) {{}}
              }};

              const setReconZoom = (newZoom) => {{
                reconZoom = Math.min(Math.max(Math.round(newZoom * 100) / 100, 0.5), 1.5);
                try {{
                  localStorage.setItem('nexus_recon_zoom', reconZoom.toString());
                }} catch (e) {{}}
                applyReconZoom();
              }};

              window.addEventListener('keydown', (e) => {{
                if (!e.ctrlKey && !e.metaKey) return;
                if (e.key === '=' || e.key === '+' || e.keyCode === 187 || e.keyCode === 107) {{
                  e.preventDefault();
                  setReconZoom(reconZoom + 0.05);
                }} else if (e.key === '-' || e.key === '_' || e.keyCode === 189 || e.keyCode === 109) {{
                  e.preventDefault();
                  setReconZoom(reconZoom - 0.05);
                }} else if (e.key === '0' || e.keyCode === 96 || e.keyCode === 48) {{
                  e.preventDefault();
                  setReconZoom(0.85);
                }}
              }}, {{ passive: false }});

              window.addEventListener('wheel', (e) => {{
                if (!e.ctrlKey && !e.metaKey) return;
                e.preventDefault();
                if (e.deltaY < 0) {{
                  setReconZoom(reconZoom + 0.05);
                }} else if (e.deltaY > 0) {{
                  setReconZoom(reconZoom - 0.05);
                }}
              }}, {{ passive: false }});

              // ---------------- Center Web Portal & Content ----------------
              const centerPortal = () => {{
                try {{
                  applyReconZoom();
                  let style = document.getElementById('efl-nexus-center-portal');
                  if (!style) {{
                    style = document.createElement('style');
                    style.id = 'efl-nexus-center-portal';
                    style.textContent = `
                      /* Always keep web portal content and tables horizontally centered */
                      html, body {{
                        margin: 0 auto !important;
                        padding-bottom: 50px !important;
                        display: flex !important;
                        flex-direction: column !important;
                        align-items: center !important;
                        width: 100% !important;
                      }}
                      .container, .container-fluid, .content, main, .main-content, .card, .wrapper, .app-content {{
                        margin-left: auto !important;
                        margin-right: auto !important;
                        max-width: 98% !important;
                        width: auto !important;
                        float: none !important;
                      }}
                      .table-responsive {{
                        display: block !important;
                        width: 100% !important;
                        overflow-x: auto !important;
                      }}
                      table {{
                        margin-left: auto !important;
                        margin-right: auto !important;
                      }}
                      /* Ensure action column with Start buttons is neatly aligned */
                      table th:last-child, table td:last-child {{
                        text-align: center !important;
                      }}
                    `;
                    if (document.head) document.head.appendChild(style);
                  }}
                  const allTables = document.querySelectorAll('table');
                  allTables.forEach(t => {{
                    t.style.marginLeft = 'auto';
                    t.style.marginRight = 'auto';
                    if (t.parentElement) {{
                      t.parentElement.style.marginLeft = 'auto';
                      t.parentElement.style.marginRight = 'auto';
                      if (t.parentElement.classList.contains('table-responsive')) {{
                        t.parentElement.style.display = 'block';
                        t.parentElement.style.overflowX = 'auto';
                      }}
                    }}
                  }});
                  const containers = document.querySelectorAll('.container, .container-fluid, .row');
                  containers.forEach(c => {{
                    c.style.marginLeft = 'auto';
                    c.style.marginRight = 'auto';
                    c.style.float = 'none';
                  }});
                }} catch (e) {{}}
              }};
              centerPortal();
              setInterval(centerPortal, 1000);

              const attachButton = () => {{
                if (document.getElementById('efl-nexus-extract-job-ids')) return;
                const button = document.createElement('button');
                button.id = 'efl-nexus-extract-job-ids';
                button.type = 'button';
                button.textContent = (refreshInterval > 0) ? `Auto-Sync: ${{refreshInterval}}s | Export Job IDs` : 'Auto-Sync: Off | Export Job IDs';
                Object.assign(button.style, {{
                  position: 'fixed', right: '16px', bottom: '8px', zIndex: 2147483647,
                  border: '0', borderRadius: '5px', padding: '6px 12px', cursor: 'pointer',
                  background: '#0d1b2a', color: '#ffffff', fontWeight: '700', fontSize: '11px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.88',
                  transition: 'opacity 0.2s, background 0.2s'
                }});
                button.onmouseenter = () => {{ button.style.opacity = '1'; }};
                button.onmouseleave = () => {{ button.style.opacity = '0.88'; }};
                button.addEventListener('click', () => autoExportJobIds(true));
                if (document.body) document.body.appendChild(button);
              }};
              attachButton();
              setInterval(attachButton, 1000);

              // Auto-export periodically while on reconciliation page
              const pollAutoExport = () => {{
                if (isReconciliationPage()) {{
                  autoExportJobIds(false);
                }}
              }};
              setInterval(pollAutoExport, 1500);
              setTimeout(pollAutoExport, 500);
              setTimeout(pollAutoExport, 1000);

              // Auto-Refresh timer when in reconciliation page
              const tickCountdown = () => {{
                if (!isReconciliationPage() || autoRefreshPaused || refreshInterval <= 0) {{
                  refreshSeconds = refreshInterval;
                  const btn = document.getElementById('efl-nexus-extract-job-ids');
                  if (btn) {{
                    if (!isReconciliationPage()) {{
                      btn.style.display = 'none';
                    }} else {{
                      btn.style.display = 'block';
                      btn.textContent = 'Auto-Sync: Off | Export Job IDs';
                    }}
                  }}
                  return;
                }}
                const btn = document.getElementById('efl-nexus-extract-job-ids');
                if (btn) {{
                  btn.style.display = 'block';
                }}
                refreshSeconds--;
                if (btn && refreshSeconds > 0) {{
                  btn.textContent = `Auto-Sync Active (Refresh in ${{refreshSeconds}}s)`;
                }}
                if (refreshSeconds <= 0) {{
                  refreshSeconds = refreshInterval;
                  if (btn) btn.textContent = 'Refreshing...';
                  autoExportJobIds(false).finally(() => {{
                    if (isReconciliationPage() && !autoRefreshPaused && refreshInterval > 0) {{
                      location.reload();
                    }}
                  }});
                }}
              }};
              setInterval(tickCountdown, 1000);

              // Floating Go Back button in web page
              const attachBackButton = () => {{
                if (document.getElementById('efl-nexus-go-back')) return;
                const backBtn = document.createElement('button');
                backBtn.id = 'efl-nexus-go-back';
                backBtn.type = 'button';
                backBtn.textContent = '◀ Go Back';
                Object.assign(backBtn.style, {{
                  position: 'fixed', left: '16px', bottom: '8px', zIndex: 2147483647,
                  border: '0', borderRadius: '5px', padding: '6px 12px', cursor: 'pointer',
                  background: '#0d1b2a', color: '#ffffff', fontWeight: '700', fontSize: '11px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.88',
                  transition: 'opacity 0.2s, background 0.2s'
                }});
                backBtn.onmouseenter = () => {{ backBtn.style.opacity = '1'; }};
                backBtn.onmouseleave = () => {{ backBtn.style.opacity = '0.88'; }};
                backBtn.addEventListener('click', () => {{
                  if (window.history.length > 1) {{
                    window.history.back();
                  }} else {{
                    location.assign(reconUrl);
                  }}
                }});
                if (document.body) document.body.appendChild(backBtn);
              }};
              attachBackButton();
              setInterval(attachBackButton, 1000);

              // Floating Zoom Controls widget next to Go Back button
              const attachZoomControls = () => {{
                if (document.getElementById('efl-nexus-zoom-widget')) return;
                const widget = document.createElement('div');
                widget.id = 'efl-nexus-zoom-widget';
                Object.assign(widget.style, {{
                  position: 'fixed', left: '105px', bottom: '8px', zIndex: 2147483647,
                  display: isReconciliationPage() ? 'flex' : 'none', alignItems: 'center', gap: '4px',
                  background: '#0d1b2a', borderRadius: '5px', padding: '4px 8px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.88',
                  fontFamily: 'Segoe UI, sans-serif', fontSize: '11px', fontWeight: '700',
                  color: '#ffffff', userSelect: 'none', transition: 'opacity 0.2s'
                }});
                widget.onmouseenter = () => {{ widget.style.opacity = '1'; }};
                widget.onmouseleave = () => {{ widget.style.opacity = '0.88'; }};

                const btnMinus = document.createElement('button');
                btnMinus.type = 'button';
                btnMinus.textContent = '−';
                btnMinus.title = 'Zoom Out (Ctrl + -)';
                Object.assign(btnMinus.style, {{
                  background: '#1b2a4a', color: '#fff', border: '0', borderRadius: '3px',
                  width: '18px', height: '18px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px',
                  lineHeight: '1', display: 'flex', alignItems: 'center', justifyContent: 'center'
                }});
                btnMinus.onclick = () => setReconZoom(reconZoom - 0.05);

                const label = document.createElement('span');
                label.id = 'efl-nexus-zoom-level';
                label.textContent = `${{Math.round(reconZoom * 100)}}%`;
                label.title = 'Current Zoom (Click to reset to 85% | Ctrl + 0)';
                Object.assign(label.style, {{
                  padding: '0 4px', cursor: 'pointer', minWidth: '32px', textAlign: 'center'
                }});
                label.onclick = () => setReconZoom(0.85);

                const btnPlus = document.createElement('button');
                btnPlus.type = 'button';
                btnPlus.textContent = '+';
                btnPlus.title = 'Zoom In (Ctrl + +)';
                Object.assign(btnPlus.style, {{
                  background: '#1b2a4a', color: '#fff', border: '0', borderRadius: '3px',
                  width: '18px', height: '18px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px',
                  lineHeight: '1', display: 'flex', alignItems: 'center', justifyContent: 'center'
                }});
                btnPlus.onclick = () => setReconZoom(reconZoom + 0.05);

                widget.appendChild(btnMinus);
                widget.appendChild(label);
                widget.appendChild(btnPlus);
                if (document.body) document.body.appendChild(widget);
              }};
              attachZoomControls();
              setInterval(attachZoomControls, 1000);

              // ---------------- Download & Attachment Handling ----------------
              const isJobDetailsPage = () => {{
                try {{
                  const path = (location.pathname || '').toLowerCase();
                  if (path.includes('/warf/start') || path.includes('/warf/')) return true;
                  const headings = [...document.querySelectorAll('h1, h2, h3, h4, h5')];
                  return headings.some(h => (h.textContent || '').toLowerCase().includes('job id -'));
                }} catch (e) {{
                  return false;
                }}
              }};

              window.__nexusJobContext = window.__nexusJobContext || {{ job_id: '', gatepass: '', client: '' }};

              const getCurrentJobId = () => {{
                if (window.__nexusJobContext && window.__nexusJobContext.job_id) {{
                  const c = String(window.__nexusJobContext.job_id).trim();
                  if (!/^\\d+$/.test(c)) return c;
                }}
                try {{
                  // 1. Direct regex on whole page innerText
                  const bodyText = document.body ? (document.body.innerText || '') : '';
                  const directMatch = bodyText.match(/\\b((?:OUT|IN)_[A-Za-z0-9_-]+)\\b/i);
                  if (directMatch && directMatch[1]) {{
                    return directMatch[1].trim();
                  }}

                  // 2. Search DOM headings, headers, cards, badges, breadcrumbs, td, th for real Job ID
                  const candidateElements = [
                    ...document.querySelectorAll('h1, h2, h3, h4, h5, header, .card-title, [class*="header"], strong, b, .badge, .breadcrumb, div, span, p, td, th')
                  ];
                  for (const el of candidateElements) {{
                    const txt = (el.textContent || '').trim();
                    const m = txt.match(/Job\\s*ID\\s*[-:]\\s*([A-Za-z0-9_-]+)/i) || txt.match(/Job\\s*(?:No|Number|#)\\s*[-:]\\s*([A-Za-z0-9_-]+)/i);
                    if (m && m[1] && !/^\\d+$/.test(m[1].trim())) {{
                      return m[1].trim();
                    }}
                  }}

                  // 3. Check sessionStorage and localStorage from row click
                  const saved = sessionStorage.getItem('nexus_active_job_id') || localStorage.getItem('nexus_active_job_id');
                  if (saved && !/^\\d+$/.test(saved)) return saved;

                  // 4. If URL has warf route, check if we stored this warfId in localStorage
                  const m = (location.pathname || '').match(/\\/warf\\/(?:start\\/)?([^\\/?#]+)/i);
                  if (m && m[1]) {{
                    const warfData = localStorage.getItem('nexus_warf_' + m[1]);
                    if (warfData) {{
                      try {{
                        const parsed = JSON.parse(warfData);
                        if (parsed && parsed.job_id && !/^\\d+$/.test(parsed.job_id)) return parsed.job_id;
                      }} catch (e) {{}}
                    }}
                    return m[1];
                  }}
                }} catch (e) {{}}
                return '';
              }};

              const getCurrentGatepass = () => {{
                if (window.__nexusJobContext && window.__nexusJobContext.gatepass) {{
                  return window.__nexusJobContext.gatepass;
                }}
                try {{
                  const m = (location.pathname || '').match(/\\/warf\\/(?:start\\/)?([^\\/?#]+)/i);
                  if (m && m[1]) {{
                    const warfData = localStorage.getItem('nexus_warf_' + m[1]);
                    if (warfData) {{
                      try {{
                        const parsed = JSON.parse(warfData);
                        if (parsed && parsed.gatepass) return parsed.gatepass;
                      }} catch (e) {{}}
                    }}
                  }}
                  const ths = [...document.querySelectorAll('th, td, label, dt')];
                  for (let i = 0; i < ths.length; i++) {{
                    const txt = (ths[i].textContent || '').trim();
                    if (/^(?:Gate\\s*Pass(?:\\s*No|\\s*ID|\\s*Number)?|Gatepass(?:\\s*No|\\s*ID|\\s*Number)?)$/i.test(txt)) {{
                      const next = ths[i].nextElementSibling;
                      if (next && next.textContent.trim()) return next.textContent.trim();
                    }}
                  }}
                  const elements = [...document.querySelectorAll('h1, h2, h3, h4, h5, div, span, p, td, tr')];
                  for (const el of elements) {{
                    const m = (el.textContent || '').match(/Gate\\s*Pass(?:\\s*No|\\s*ID|\\s*Number)?\\s*[-:#]?\\s*([A-Za-z0-9_-]+)/i);
                    if (m && m[1]) return m[1].trim();
                  }}
                  const saved = sessionStorage.getItem('nexus_active_gatepass') || localStorage.getItem('nexus_active_gatepass');
                  if (saved) return saved;
                }} catch (e) {{}}
                return '';
              }};

              const getCurrentClient = () => {{
                if (window.__nexusJobContext && window.__nexusJobContext.client) {{
                  return window.__nexusJobContext.client;
                }}
                try {{
                  const m = (location.pathname || '').match(/\\/warf\\/(?:start\\/)?([^\\/?#]+)/i);
                  if (m && m[1]) {{
                    const warfData = localStorage.getItem('nexus_warf_' + m[1]);
                    if (warfData) {{
                      try {{
                        const parsed = JSON.parse(warfData);
                        if (parsed && parsed.client) return parsed.client;
                      }} catch (e) {{}}
                    }}
                  }}
                  const elements = [...document.querySelectorAll('h1, h2, h3, h4, h5, div, span, p, td, tr')];
                  for (const el of elements) {{
                    const m = (el.textContent || '').match(/(?:Client|Customer)(?:\\s*Name)?\\s*[-:]\\s*([A-Za-z0-9_-]+)/i);
                    if (m && m[1]) return m[1].trim();
                  }}
                  const saved = sessionStorage.getItem('nexus_active_client') || localStorage.getItem('nexus_active_client');
                  if (saved) return saved;
                }} catch (e) {{}}
                return '';
              }};

              const showDownloadToast = (msg, isError = false) => {{
                try {{
                  let toast = document.getElementById('efl-nexus-download-toast');
                  if (!toast) {{
                    toast = document.createElement('div');
                    toast.id = 'efl-nexus-download-toast';
                    Object.assign(toast.style, {{
                      position: 'fixed',
                      top: '20px',
                      right: '20px',
                      zIndex: '2147483647',
                      padding: '12px 20px',
                      borderRadius: '8px',
                      color: '#ffffff',
                      fontWeight: '700',
                      fontSize: '13px',
                      boxShadow: '0 4px 18px rgba(0,0,0,0.3)',
                      transition: 'opacity 0.3s, transform 0.3s',
                      maxWidth: '480px',
                      wordBreak: 'break-word',
                    }});
                    if (document.body) document.body.appendChild(toast);
                  }}
                  toast.style.background = isError ? '#dc2626' : '#16a34a';
                  toast.textContent = msg;
                  toast.style.display = 'block';
                  toast.style.opacity = '1';
                  toast.style.transform = 'translateY(0)';
                  clearTimeout(toast._timeout);
                  toast._timeout = setTimeout(() => {{
                    toast.style.opacity = '0';
                    toast.style.transform = 'translateY(-10px)';
                    setTimeout(() => {{ if (toast.style.opacity === '0') toast.style.display = 'none'; }}, 300);
                  }}, 4000);
                }} catch (e) {{}}
              }};

              let reconciliationReturnTimer = null;
              const scheduleReturnToReconciliation = () => {{
                if (reconciliationReturnTimer) clearTimeout(reconciliationReturnTimer);
                showDownloadToast('Download saved. Returning to Reconciliation in 5 seconds...');
                reconciliationReturnTimer = setTimeout(() => {{
                  location.assign(reconUrl);
                }}, 5000);
              }};

              const fetchAndSaveFile = async (url, suggestedName, statusEl = null, returnAfterSuccess = false) => {{
                if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.save_downloaded_file !== 'function') {{
                  showDownloadToast('Connection initializing... please click again in a moment.', true);
                  return false;
                }}
                const originalText = statusEl ? statusEl.textContent : '';
                if (statusEl) {{
                  statusEl.textContent = '⏳ Downloading...';
                  statusEl.disabled = true;
                }}
                showDownloadToast('Downloading: ' + (suggestedName || 'file') + '...');
                try {{
                  const response = await fetch(url, {{ credentials: 'include' }});
                  if (!response.ok) throw new Error('HTTP ' + response.status + ': ' + response.statusText);
                  const blob = await response.blob();
                  return new Promise((resolve) => {{
                    const reader = new FileReader();
                    reader.onloadend = async () => {{
                      try {{
                        const base64Data = reader.result;
                        let activeJob = getCurrentJobId();
                        let activeGp = getCurrentGatepass();
                        let activeCli = getCurrentClient();
                        if (/^\\d+$/.test(activeJob) && window.pywebview && window.pywebview.api && typeof window.pywebview.api.lookup_warf_job === 'function') {{
                          try {{
                            const mapped = await window.pywebview.api.lookup_warf_job(activeJob);
                            if (mapped && mapped.job_id) {{
                              activeJob = mapped.job_id;
                              if (!activeGp) activeGp = mapped.gatepass || '';
                              if (!activeCli) activeCli = mapped.client || '';
                            }}
                          }} catch (e) {{}}
                        }}
                        const result = await window.pywebview.api.save_downloaded_file({{
                          filename: suggestedName || url.split('/').pop().split('?')[0] || 'downloaded_file',
                          data: base64Data,
                          url: url,
                          job_id: activeJob,
                          gatepass: activeGp,
                          client: activeCli,
                        }});
                        if (result && result.success) {{
                          const locName = result.folder ? 'folder ' + result.folder : 'Downloads folder';
                          showDownloadToast('✓ Saved: ' + result.filename + ' in ' + locName + '!');
                          if (statusEl) statusEl.textContent = '✓ Downloaded';
                          if (returnAfterSuccess) scheduleReturnToReconciliation();
                          resolve(result);
                        }} else {{
                          throw new Error(result && result.error ? result.error : 'Save failed');
                        }}
                      }} catch (err) {{
                        showDownloadToast('Save failed: ' + err.message, true);
                        if (statusEl) statusEl.textContent = originalText;
                        resolve(false);
                      }} finally {{
                        if (statusEl) {{
                          statusEl.disabled = false;
                          setTimeout(() => {{ statusEl.textContent = originalText; }}, 3500);
                        }}
                      }}
                    }};
                    reader.onerror = () => {{
                      showDownloadToast('Failed to read file response', true);
                      if (statusEl) {{
                        statusEl.textContent = originalText;
                        statusEl.disabled = false;
                      }}
                      resolve(false);
                    }};
                    reader.readAsDataURL(blob);
                  }});
                }} catch (err) {{
                  showDownloadToast('Download error: ' + err.message, true);
                  if (statusEl) {{
                    statusEl.textContent = originalText;
                    statusEl.disabled = false;
                  }}
                  return false;
                }}
              }};

              const isDownloadableLink = (el) => {{
                if (!el || el.tagName !== 'A') return false;
                if (el.classList.contains('btn-download') || el.hasAttribute('download')) return true;
                const href = (el.getAttribute('href') || '').toLowerCase();
                if (!href || href.startsWith('#') || href.startsWith('javascript:')) return false;
                const fileExts = ['.xlsx', '.xls', '.csv', '.pdf', '.docx', '.doc', '.zip', '.png', '.jpg', '.jpeg'];
                return fileExts.some(ext => href.includes(ext)) || href.includes('/storage/app/public/uploads/');
              }};

              // Intercept direct clicks on download buttons / file links
              document.addEventListener('click', (e) => {{
                const link = e.target && e.target.closest ? e.target.closest('a') : null;
                if (link && isDownloadableLink(link)) {{
                  e.preventDefault();
                  e.stopPropagation();
                  const url = link.href || link.getAttribute('href');
                  const filename = link.getAttribute('download') || link.textContent.trim() || url.split('/').pop().split('?')[0];
                  fetchAndSaveFile(url, filename, link, true);
                }}
              }}, true);

              // Enhance Evidence Image Cards with quick download buttons
              const enhanceEvidenceCards = () => {{
                const cards = document.querySelectorAll('.evidence-card:not([data-nexus-enhanced])');
                cards.forEach(card => {{
                  card.setAttribute('data-nexus-enhanced', '1');
                  const imgUrl = card.getAttribute('data-img');
                  if (!imgUrl) return;
                  const dlBtn = document.createElement('button');
                  dlBtn.type = 'button';
                  dlBtn.textContent = '💾 Save Image';
                  Object.assign(dlBtn.style, {{
                    marginTop: '6px',
                    width: '100%',
                    fontSize: '11px',
                    padding: '3px 6px',
                    background: '#f08b08',
                    color: '#ffffff',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontWeight: 'bold',
                  }});
                  dlBtn.addEventListener('click', (ev) => {{
                    ev.preventDefault();
                    ev.stopPropagation();
                    const stack = card.getAttribute('data-stack') || 'evidence';
                    const filename = `Job_${{getCurrentJobId() || 'job'}}_Stack_${{stack}}_${{imgUrl.split('/').pop().split('?')[0]}}`;
                    fetchAndSaveFile(imgUrl, filename, dlBtn, true);
                  }});
                  card.appendChild(dlBtn);
                }});

                const modal = document.getElementById('imageModal');
                if (modal && !document.getElementById('efl-nexus-modal-dl-btn')) {{
                  const modalHeader = modal.querySelector('.modal-header');
                  if (modalHeader) {{
                    const modalDlBtn = document.createElement('button');
                    modalDlBtn.id = 'efl-nexus-modal-dl-btn';
                    modalDlBtn.type = 'button';
                    modalDlBtn.className = 'btn btn-sm btn-warning me-2';
                    modalDlBtn.textContent = '💾 Download Image';
                    modalDlBtn.addEventListener('click', () => {{
                      const modalImg = document.getElementById('modalImage');
                      if (modalImg && modalImg.src) {{
                        const stack = document.getElementById('modalStack')?.textContent || '';
                        const filename = `Job_${{getCurrentJobId() || 'job'}}_${{stack.replace(/[^a-z0-9]/gi, '_')}}_evidence.jpg`;
                        fetchAndSaveFile(modalImg.src, filename, modalDlBtn, true);
                      }}
                    }});
                    const closeBtn = modalHeader.querySelector('.btn-close');
                    if (closeBtn) {{
                      modalHeader.insertBefore(modalDlBtn, closeBtn);
                    }} else {{
                      modalHeader.appendChild(modalDlBtn);
                    }}
                  }}
                }}
              }};
              setInterval(enhanceEvidenceCards, 1000);

              const getAllJobDownloadItems = () => {{
                const items = [];
                const links = document.querySelectorAll("a.btn-download, a[download], table a[href*='/storage/'], table a[href*='uploads']");
                links.forEach(l => {{
                  const href = l.href || l.getAttribute('href');
                  if (href && !items.some(it => it.url === href)) {{
                    const name = l.getAttribute('download') || l.textContent.trim() || href.split('/').pop().split('?')[0];
                    items.push({{ url: href, filename: name }});
                  }}
                }});
                const cards = document.querySelectorAll('.evidence-card[data-img]');
                cards.forEach((c, idx) => {{
                  const imgUrl = c.getAttribute('data-img');
                  if (imgUrl && !items.some(it => it.url === imgUrl)) {{
                    const stack = c.getAttribute('data-stack') || String(idx + 1);
                    const name = `Job_${{getCurrentJobId() || 'job'}}_Stack_${{stack}}_${{imgUrl.split('/').pop().split('?')[0]}}`;
                    items.push({{ url: imgUrl, filename: name }});
                  }}
                }});
                return items;
              }};

              const downloadAllJobFiles = async (returnAfterSuccess = false) => {{
                const items = getAllJobDownloadItems();
                if (!items.length) {{
                  showDownloadToast('No downloadable files or evidence images found on this page.', true);
                  return;
                }}
                showDownloadToast('Starting download of ' + items.length + ' file(s)...');
                const allBtn = document.getElementById('efl-nexus-download-all');
                if (allBtn) {{
                  allBtn.disabled = true;
                  allBtn.textContent = '⏳ Downloading (0/' + items.length + ')...';
                }}
                let successCount = 0;
                let lastFolder = '';
                for (let i = 0; i < items.length; i++) {{
                  if (allBtn) allBtn.textContent = '⏳ Downloading (' + (i + 1) + '/' + items.length + ')...';
                  const res = await fetchAndSaveFile(items[i].url, items[i].filename);
                  if (res) {{
                    successCount++;
                    if (res.folder) lastFolder = res.folder;
                  }}
                }}
                if (allBtn) {{
                  allBtn.disabled = false;
                  allBtn.textContent = '✓ Downloaded ' + successCount + '/' + items.length + ' Files';
                  setTimeout(() => {{
                    allBtn.textContent = '📥 Download All Files';
                  }}, 4000);
                }}
                const destMsg = lastFolder ? 'folder ' + lastFolder : 'Downloads folder';
                showDownloadToast('✓ Finished: ' + successCount + ' of ' + items.length + ' file(s) saved to ' + destMsg + '!');
                if (returnAfterSuccess && successCount > 0) scheduleReturnToReconciliation();
              }};

              const attachDownloadAllButton = () => {{
                if (!isJobDetailsPage()) {{
                  const btn = document.getElementById('efl-nexus-download-all');
                  if (btn) btn.style.display = 'none';
                  return;
                }}
                let btn = document.getElementById('efl-nexus-download-all');
                if (!btn) {{
                  btn = document.createElement('button');
                  btn.id = 'efl-nexus-download-all';
                  btn.type = 'button';
                  btn.textContent = '📥 Download All Files';
                  Object.assign(btn.style, {{
                    position: 'fixed',
                    left: '105px',
                    bottom: '8px',
                    zIndex: 2147483647,
                    border: '0',
                    borderRadius: '5px',
                    padding: '6px 12px',
                    cursor: 'pointer',
                    background: '#16a34a',
                    color: '#ffffff',
                    fontWeight: '700',
                    fontSize: '11px',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
                    opacity: '0.9',
                    transition: 'opacity 0.2s, background 0.2s',
                  }});
                  btn.onmouseenter = () => {{ btn.style.opacity = '1'; }};
                  btn.onmouseleave = () => {{ btn.style.opacity = '0.9'; }};
                  btn.addEventListener('click', () => downloadAllJobFiles(true));
                  if (document.body) document.body.appendChild(btn);
                }} else {{
                  btn.style.display = 'block';
                }}
              }};
              attachDownloadAllButton();
              setInterval(attachDownloadAllButton, 1000);

              const attachLoadingHistoryButton = () => {{
                let btn = document.getElementById('efl-nexus-loading-history');
                if (!isJobDetailsPage()) {{
                  if (btn) btn.style.display = 'none';
                  return;
                }}
                if (!btn) {{
                  btn = document.createElement('button');
                  btn.id = 'efl-nexus-loading-history';
                  btn.type = 'button';
                  btn.textContent = 'Download Loading History';
                  Object.assign(btn.style, {{
                    position: 'fixed', left: '260px', bottom: '8px', zIndex: 2147483647,
                    border: '0', borderRadius: '5px', padding: '6px 12px', cursor: 'pointer',
                    background: '#2563eb', color: '#ffffff', fontWeight: '700', fontSize: '11px',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.9',
                  }});
                  btn.addEventListener('click', async () => {{
                    if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.request_loading_history !== 'function') {{
                      showDownloadToast('Connection initializing... please try again.', true);
                      return;
                    }}
                    btn.disabled = true;
                    try {{
                      const activeGp = getCurrentGatepass();
                      const result = await window.pywebview.api.request_loading_history({{
                        job_id: getCurrentJobId(), gatepass: activeGp, client: getCurrentClient(),
                      }});
                      if (result && result.success) {{
                        const gpMsg = activeGp ? ' for Gate Pass ' + activeGp : '';
                        showDownloadToast('Querying and exporting Loading History' + gpMsg + '...');
                      }} else {{
                        showDownloadToast('Could not open Loading History.', true);
                      }}
                    }} catch (e) {{
                      showDownloadToast('Could not open Loading History.', true);
                    }} finally {{
                      btn.disabled = false;
                    }}
                  }});
                  if (document.body) document.body.appendChild(btn);
                }} else {{
                  btn.style.display = 'block';
                }}
              }};
              attachLoadingHistoryButton();
              setInterval(attachLoadingHistoryButton, 1000);

              // Command listener: executes "Start" action for a selected job in the web portal
              const executeStartJob = (jobId) => {{
                const targetClean = String(jobId || '').trim().toLowerCase().replace(/[^a-z0-9]/g, '');
                if (!targetClean) return;
                const tables = [...document.querySelectorAll('table')];
                for (const table of tables) {{
                  const rows = [...table.querySelectorAll('tbody tr, tr')];
                  for (const row of rows) {{
                    const cells = [...row.querySelectorAll('td, th')];
                    const match = cells.some(c => {{
                      const txt = c.textContent.trim().toLowerCase().replace(/[^a-z0-9]/g, '');
                      return txt === targetClean;
                    }});
                    if (match) {{
                      const startBtn = row.querySelector("button.btn-start, form[action*='/warf/start'] button, button");
                      const form = row.querySelector("form[action*='/warf/start']");
                      if (startBtn) {{
                        startBtn.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                        startBtn.click();
                        return true;
                      }} else if (form) {{
                        form.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                        if (typeof form.requestSubmit === 'function') {{
                          form.requestSubmit();
                        }} else {{
                          form.submit();
                        }}
                        return true;
                      }}
                    }}
                  }}
                }}
                alert('Job ID ' + jobId + ' could not be found in the active portal table.');
                return false;
              }};

              const pollCommands = async () => {{
                if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.get_pending_command !== 'function') return;
                try {{
                  const cmd = await window.pywebview.api.get_pending_command();
                  if (cmd && cmd.action === 'start_job' && cmd.job_id) {{
                    try {{
                      sessionStorage.setItem('nexus_active_job_id', cmd.job_id);
                      localStorage.setItem('nexus_active_job_id', cmd.job_id);
                      if (cmd.gatepass) {{
                        sessionStorage.setItem('nexus_active_gatepass', cmd.gatepass);
                        localStorage.setItem('nexus_active_gatepass', cmd.gatepass);
                      }}
                      if (cmd.client) {{
                        sessionStorage.setItem('nexus_active_client', cmd.client);
                        localStorage.setItem('nexus_active_client', cmd.client);
                      }}
                    }} catch (e) {{}}
                    executeStartJob(cmd.job_id);
                  }} else if (cmd && (cmd.action === 'grab_data_now' || cmd.action === 'force_export')) {{
                    lastExportSignature = '';
                    autoExportJobIds(true);
                  }} else if (cmd && cmd.action === 'download_job_files') {{
                    if (cmd.job_id) {{
                      window.__nexusJobContext = {{
                        job_id: cmd.job_id,
                        gatepass: cmd.gatepass || '',
                        client: cmd.client || '',
                      }};
                    }}
                    downloadAllJobFiles();
                  }} else if (cmd && cmd.action === 'set_refresh_interval') {{
                    const newSec = Math.max(0, parseInt(cmd.seconds, 10) || 0);
                    refreshInterval = newSec;
                    refreshSeconds = newSec;
                    autoRefreshPaused = newSec <= 0;
                    const btn = document.getElementById('efl-nexus-extract-job-ids');
                    if (btn) {{
                      if (autoRefreshPaused || refreshInterval <= 0) {{
                        btn.textContent = 'Auto-Sync: Off | Export Job IDs';
                      }} else {{
                        btn.textContent = `Auto-Sync Active (Refresh in ${{refreshSeconds}}s)`;
                      }}
                    }}
                  }} else if (cmd && cmd.action === 'go_back') {{
                    if (window.history.length > 1) {{
                      window.history.back();
                    }} else {{
                      location.assign(reconUrl);
                    }}
                  }} else if (cmd && cmd.action === 'reload') {{
                    location.reload();
                  }} else if (cmd && cmd.action === 'go_home') {{
                    location.assign(cmd.url || reconUrl);
                  }}
                }} catch (e) {{}}
              }};
              setInterval(pollCommands, 400);
            }})();
        """)

    def automate_portal_flow():
        """Fill the login form, then route a successful session to reconciliation.

        The portal's login form uses #email and #password and posts to
        /post-login. A semantic fallback keeps the flow resilient to minor
        markup changes. It deliberately submits only once; a failed login
        remains available for the operator to correct in the embedded browser.
        """
        if not username or not password:
            return
        user_value = json.dumps(username)
        password_value = json.dumps(password)
        recon_url = json.dumps(reconciliation_url or DEFAULT_RECONCILIATION_URL)
        window.run_js(f"""
            (() => {{
              const onLoginPage = new URL(location.href).pathname.replace(new RegExp('/$'), '') === '/login';
              if (!onLoginPage) {{
                if (!sessionStorage.getItem('eflNexusReconciliationOpened')) {{
                  sessionStorage.setItem('eflNexusReconciliationOpened', '1');
                  location.assign({recon_url});
                }}
                return;
              }}
              if (sessionStorage.getItem('eflNexusLoginSubmitted')) return;

              let attempts = 0;
              const tryFillAndSubmit = () => {{
                attempts++;
                const inputs = [...document.querySelectorAll('input')].filter(input => !input.disabled);
                const password = document.querySelector('#password') || inputs.find(input => (input.type || '').toLowerCase() === 'password');
                const username = document.querySelector('#email') || inputs.find(input => input !== password &&
                  /user|email|login/.test([input.name, input.id, input.autocomplete, input.type].filter(Boolean).join(' ').toLowerCase()))
                  || inputs.find(input => input !== password && ['text', 'email'].includes((input.type || 'text').toLowerCase()));
                if (!username || !password) {{
                  if (attempts < 20) setTimeout(tryFillAndSubmit, 200);
                  return;
                }}
                const setValue = (input, value) => {{
                  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                  setter.call(input, value);
                  input.dispatchEvent(new Event('input', {{bubbles: true}}));
                  input.dispatchEvent(new Event('change', {{bubbles: true}}));
                }};
                setValue(username, {user_value});
                setValue(password, {password_value});
                sessionStorage.setItem('eflNexusLoginSubmitted', '1');
                const form = document.querySelector("form[action$='/post-login']") || password.closest('form') || username.closest('form');
                if (form && typeof form.requestSubmit === 'function') form.requestSubmit();
                else if (form) form.submit();
                else password.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', code: 'Enter', bubbles: true}}));
              }};
              tryFillAndSubmit();
            }})();
        """)

    window.events.loaded += add_extract_button
    window.events.loaded += automate_portal_flow
    webview.start(gui="edgechromium", private_mode=True)


def run_loading_history_browser(
    start_url: str,
    gatepass: str = "",
    job_id: str = "",
    client: str = "",
) -> None:
    """Run a minimal Körber WebView2 window for Loading History downloads."""
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True
        # The report export uses target=_blank. Keep it in this authenticated
        # WebView; the user's regular browser does not have its auth ticket.
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    except Exception as err:
        sys.stderr.write(f"Failed to import 'webview' for Loading History: {err}\n")
        sys.stderr.flush()
        raise

    username = os.environ.pop("EFL_NEXUS_KORBER_USER", "")
    password = os.environ.pop("EFL_NEXUS_KORBER_PASS", "")
    stop_at_gatepass = os.environ.pop("EFL_NEXUS_LOADING_HISTORY_STOP_AT_GATEPASS", "") == "1"
    gatepass = _clean(str(gatepass or os.environ.pop("EFL_NEXUS_KORBER_GATEPASS", "") or ""))
    job_id = _clean(str(job_id or os.environ.pop("EFL_NEXUS_KORBER_JOB_ID", "") or ""))
    client = _clean(str(client or os.environ.pop("EFL_NEXUS_KORBER_CLIENT", "") or ""))

    # Resolve persisted values only when NOT in manual stop-at-gatepass mode
    if not stop_at_gatepass:
        # 1. Resolve from loading history event file
        event_file = _loading_history_event_file()
        if event_file.exists():
            try:
                ev_data = json.loads(event_file.read_text(encoding="utf-8"))
                if not gatepass:
                    gatepass = _clean(str(ev_data.get("gatepass") or ev_data.get("active_gatepass") or ""))
                if not job_id:
                    job_id = _clean(str(ev_data.get("job_id") or ""))
                if not client:
                    client = _clean(str(ev_data.get("client") or ""))
            except Exception:
                pass

        # 2. Resolve from persisted job map
        persisted = load_persisted_job_map()
        if job_id and job_id.casefold() in persisted:
            mapped = persisted[job_id.casefold()]
            if not gatepass:
                gatepass = _clean(str(mapped.get("gatepass") or ""))
            if not client:
                client = _clean(str(mapped.get("client") or ""))
        elif gatepass:
            for mapped in persisted.values():
                if _clean(str(mapped.get("gatepass", ""))) == gatepass:
                    if not job_id:
                        job_id = _clean(str(mapped.get("job_id") or ""))
                    if not client:
                        client = _clean(str(mapped.get("client") or ""))
                    break

        # 3. Resolve from website_grabber_results.json
        if not job_id or not client or not gatepass:
            try:
                base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                res_file = base / "EFL_NEXUS" / "website_grabber_results.json"
                if res_file.exists():
                    res_data = json.loads(res_file.read_text(encoding="utf-8"))
                    records = res_data.get("records") if isinstance(res_data, dict) else res_data
                    if isinstance(records, list):
                        for item in reversed(records):
                            item_gp = _clean(str(item.get("gatepass") or ""))
                            item_jid = _clean(str(item.get("job_id") or ""))
                            item_cli = _clean(str(item.get("client") or ""))
                            if gatepass and item_gp == gatepass:
                                if not job_id:
                                    job_id = item_jid
                                if not client:
                                    client = item_cli
                                break
                            elif job_id and item_jid == job_id:
                                if not gatepass:
                                    gatepass = item_gp
                                if not client:
                                    client = item_cli
                                break
            except Exception:
                pass
    else:
        gatepass = ""
        job_id = ""
        client = ""

    if not start_url or not username or not password:
        raise ValueError("Körber URL, username, and password are required for Loading History.")

    class LoadingHistoryBridge:
        def __init__(self, gp: str, jid: str = "", cli: str = ""):
            self._gatepass = gp
            self._job_id = jid
            self._client = cli

        def get_pending_command(self) -> dict[str, Any] | None:
            cmd_file = _loading_history_command_file()
            try:
                if cmd_file.exists():
                    text = cmd_file.read_text(encoding="utf-8")
                    cmd_file.unlink(missing_ok=True)
                    data = json.loads(text)
                    if isinstance(data, dict):
                        gp = _clean(str(data.get("gatepass") or ""))
                        jid = _clean(str(data.get("job_id") or ""))
                        cli = _clean(str(data.get("client") or ""))
                        if gp:
                            self._gatepass = gp
                        if jid:
                            self._job_id = jid
                        if cli:
                            self._client = cli
                    return data
            except Exception:
                pass
            return None

        def report_gatepass(self, val: str) -> None:
            c = _clean(str(val or ""))
            if c:
                self._gatepass = c

        def get_gatepass(self) -> str:
            if self._gatepass:
                return self._gatepass
            if stop_at_gatepass:
                return ""
            ev = _loading_history_event_file()
            if ev.exists():
                try:
                    d = json.loads(ev.read_text(encoding="utf-8"))
                    self._gatepass = _clean(str(d.get("gatepass") or d.get("active_gatepass") or ""))
                except Exception:
                    pass
            if not self._gatepass:
                try:
                    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                    res_file = base / "EFL_NEXUS" / "website_grabber_results.json"
                    if res_file.exists():
                        res_data = json.loads(res_file.read_text(encoding="utf-8"))
                        records = res_data.get("records") if isinstance(res_data, dict) else res_data
                        if isinstance(records, list):
                            for item in reversed(records):
                                gp = _clean(str(item.get("gatepass") or ""))
                                if gp:
                                    self._gatepass = gp
                                    break
                except Exception:
                    pass
            return self._gatepass

        def get_job_id(self) -> str:
            return self._job_id

        def get_client(self) -> str:
            return self._client

        def save_downloaded_file(self, payload: dict[str, Any]) -> dict[str, Any]:
            import base64
            from urllib.parse import unquote, urlparse
            try:
                raw_filename = str(payload.get("filename") or "").strip()
                b64_data = payload.get("data") or ""
                url = str(payload.get("url") or "")
                gp = _clean(str(payload.get("gatepass") or self.get_gatepass() or ""))
                jid = _clean(str(payload.get("job_id") or self.get_job_id() or ""))
                cli = _clean(str(payload.get("client") or self.get_client() or ""))

                if isinstance(b64_data, str):
                    if "," in b64_data:
                        b64_data = b64_data.split(",", 1)[1]
                    file_bytes = base64.b64decode(b64_data)
                elif isinstance(b64_data, bytes):
                    file_bytes = b64_data
                else:
                    return {"success": False, "error": "Invalid data format"}

                dest_folder = get_job_download_folder(job_id=jid, gatepass=gp, client=cli)
                if not raw_filename or raw_filename.lower() in ("download", "file", ""):
                    if url:
                        parsed = unquote(urlparse(url).path.split("/")[-1])
                        if parsed:
                            raw_filename = parsed
                if not raw_filename:
                    raw_filename = "Loading_History_Report.xlsx"

                raw_filename = raw_filename.split("?")[0].split("#")[0].strip()
                target_path = get_unique_download_path(raw_filename, folder=dest_folder)
                target_path.write_bytes(file_bytes)

                try:
                    dl_event_file = _download_event_file()
                    dl_event_file.parent.mkdir(parents=True, exist_ok=True)
                    dl_event_file.write_text(json.dumps({
                        "action": "file_downloaded",
                        "filename": target_path.name,
                        "path": str(target_path.resolve()),
                        "folder": target_path.parent.name,
                        "folder_path": str(target_path.parent.resolve()),
                        "size": len(file_bytes),
                        "time": time.time(),
                        "job_id": jid,
                        "gatepass": gp,
                        "client": cli,
                    }), encoding="utf-8")
                except Exception:
                    pass

                return {
                    "success": True,
                    "filename": target_path.name,
                    "path": str(target_path.resolve()),
                    "folder": target_path.parent.name,
                    "folder_path": str(target_path.parent.resolve()),
                    "size": len(file_bytes),
                }
            except Exception as exc:
                return {"success": False, "error": str(exc)}

    bridge = LoadingHistoryBridge(gatepass, job_id, client)
    window = webview.create_window(
        "EFL NEXUS — Loading History",
        start_url,
        js_api=bridge,
        width=1100,
        height=760,
        min_size=(800, 600),
    )
    user_value = json.dumps(username)
    password_value = json.dumps(password)
    gatepass_value = json.dumps(gatepass)
    stop_at_gatepass_value = "true" if stop_at_gatepass else "false"

    def automate_loading_history() -> None:
        window.run_js(f"""
            (() => {{
              if (window.__eflNexusLoadingHistoryAutomation) return;
              window.__eflNexusLoadingHistoryAutomation = true;
              const log = (message) => console.info('[Loading History] ' + message);
              const setValue = (input, value) => {{
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(input, value);
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
              }};

              let activeGatepass = {gatepass_value};
              const stopAtGatepass = {stop_at_gatepass_value};
              let manualStopBypassed = false;

              const resolveGatepass = async () => {{
                if (activeGatepass) return activeGatepass;
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_gatepass === 'function') {{
                  try {{
                    const res = await window.pywebview.api.get_gatepass();
                    if (res) activeGatepass = String(res).trim();
                  }} catch (e) {{}}
                }}
                return activeGatepass;
              }};

              const findGatepassInput = () => {{
                const searchInDoc = (doc) => {{
                  if (!doc || typeof doc.querySelectorAll !== 'function') return null;
                  try {{
                    const win = doc.defaultView || (typeof window !== 'undefined' ? window : null);
                    const allInputs = [...doc.querySelectorAll('hj-textbox input, input.k-textbox, input[type="text"], input:not([type])')];
                    const visible = allInputs.filter(input => {{
                      if (!input || input.type === 'hidden' || input.disabled || input.readOnly) return false;
                      const tid = input.getAttribute('data-hj-test-id') || (input.parentElement ? input.parentElement.getAttribute('data-hj-test-id') : '') || '';
                      if (tid === 'username' || tid === 'password' || tid === 'menuSearchTextBox') return false;
                      const ph = (input.placeholder || '').toLowerCase();
                      if (ph.includes('user name') || ph.includes('password') || ph.includes('search')) return false;
                      return input.getClientRects ? (input.getClientRects().length > 0) : true;
                    }});
                    if (!visible.length) return null;

                    // 1. Direct label-to-row matching: find label/heading matching "Gate Pass" (not Order/Load)
                    const candidateLabels = [...doc.querySelectorAll('label, span, div, td, th, p, strong, b, hj-field')].filter(el => {{
                      if (!el || (el.children && el.children.length > 2)) return false;
                      const txt = (el.textContent || '').trim();
                      return /^(?:Gate\\s*Pass(?:\\s*ID)?|Gatepass(?:\\s*ID)?)$/i.test(txt) ||
                             (/\\bgate\\s*pass\\b/i.test(txt) && !/order\\s*number|load\\s*id/i.test(txt));
                    }});

                    for (const lbl of candidateLabels) {{
                      const forAttr = lbl.getAttribute && lbl.getAttribute('for');
                      if (forAttr) {{
                        const direct = doc.getElementById(forAttr);
                        if (direct && visible.includes(direct)) return direct;
                        if (direct) {{
                          const childInp = direct.querySelector && direct.querySelector('input');
                          if (childInp && visible.includes(childInp)) return childInp;
                        }}
                      }}
                      let curr = lbl.parentElement;
                      while (curr && curr !== doc.body && curr.tagName !== 'FORM') {{
                        const inps = visible.filter(inp => {{
                          let p = inp;
                          while (p) {{
                            if (p === curr) return true;
                            p = p.parentElement;
                          }}
                          return false;
                        }});
                        const cText = curr.textContent || '';
                        const hasOthers = /order\\s*number|load\\s*id/i.test(cText);
                        if (inps.length > 0 && !hasOthers) {{
                          return inps[0];
                        }}
                        curr = curr.parentElement;
                      }}
                    }}

                    // 2. Reverse ancestor check from visible inputs:
                    // Ancestor must contain "Gate Pass" and must NOT contain "Order Number" or "Load ID"
                    for (const inp of visible) {{
                      let curr = inp.parentElement;
                      while (curr && curr !== doc.body && curr.tagName !== 'FORM') {{
                        const txt = curr.textContent || '';
                        if (/\\bgate\\s*pass\\b/i.test(txt) && !/order\\s*number|load\\s*id/i.test(txt)) {{
                          return inp;
                        }}
                        curr = curr.parentElement;
                      }}
                    }}

                    // 3. Knockout field metadata inspection on parent <hj-textbox>
                    if (win && win.ko) {{
                      for (const inp of visible) {{
                        const parentHj = inp.closest ? inp.closest('hj-textbox') : (inp.parentElement && inp.parentElement.tagName === 'HJ-TEXTBOX' ? inp.parentElement : null);
                        if (parentHj) {{
                          try {{
                            const ctx = (win.ko.contextFor && win.ko.contextFor(parentHj)) || (win.ko.dataFor && win.ko.dataFor(parentHj));
                            const f = ctx ? (ctx.field || (ctx.$data && ctx.$data.field) || ctx.$data) : null;
                            if (f) {{
                              const meta = JSON.stringify({{
                                name: typeof f.name === 'function' ? f.name() : f.name,
                                label: typeof f.label === 'function' ? f.label() : f.label,
                                caption: typeof f.caption === 'function' ? f.caption() : f.caption,
                                id: typeof f.id === 'function' ? f.id() : f.id,
                              }}).toLowerCase();
                              if (meta.includes('gate') && meta.includes('pass')) return inp;
                            }}
                          }} catch (e) {{}}
                        }}
                      }}
                    }}

                    // 4. Input / Component attributes matching gate pass
                    for (const inp of visible) {{
                      const parentHj = inp.closest ? inp.closest('hj-textbox') : (inp.parentElement && inp.parentElement.tagName === 'HJ-TEXTBOX' ? inp.parentElement : null);
                      const idStr = ((inp.id || '') + ' ' + (inp.name || '') + ' ' + (inp.getAttribute('data-bind') || '')).toLowerCase();
                      const hjStr = parentHj ? ((parentHj.id || '') + ' ' + (parentHj.getAttribute('params') || '') + ' ' + (parentHj.getAttribute('data-hj-test-id') || '')).toLowerCase() : '';
                      if ((idStr.includes('gate') && idStr.includes('pass')) || (hjStr.includes('gate') && hjStr.includes('pass'))) {{
                        return inp;
                      }}
                    }}

                    // 5. In Loading History Report (menu 1992), exactly 3 textbox inputs exist:
                    // Index 0 = Order Number, Index 1 = Load ID, Index 2 = Gate Pass ID
                    if (visible.length === 3) {{
                      return visible[2];
                    }}

                    // 6. If an input is currently active/focused, use it
                    if (doc.activeElement && visible.includes(doc.activeElement)) {{
                      return doc.activeElement;
                    }}

                    // 7. Last visible input among multiple inputs (Gate Pass ID is at the bottom of the parameter list)
                    if (visible.length >= 2) {{
                      return visible[visible.length - 1];
                    }}

                    return visible[0] || null;
                  }} catch (e) {{
                    return null;
                  }}
                }};

                let target = searchInDoc(document);
                if (target) return target;
                try {{
                  const iframes = [...document.querySelectorAll('iframe')];
                  for (const iframe of iframes) {{
                    try {{
                      const idoc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
                      if (idoc) {{
                        target = searchInDoc(idoc);
                        if (target) return target;
                      }}
                    }} catch (e) {{}}
                  }}
                }} catch (e) {{}}
                return null;
              }};

              const typeGatepassIntoInput = async (input, val) => {{
                if (!input || !val) return false;
                try {{
                  const win = input.ownerDocument && input.ownerDocument.defaultView ? input.ownerDocument.defaultView : window;
                  if (typeof input.focus === 'function') input.focus();
                  if (typeof input.click === 'function') input.click();
                  if (typeof input.select === 'function') input.select();

                  const proto = win.HTMLInputElement ? win.HTMLInputElement.prototype : HTMLInputElement.prototype;
                  const desc = Object.getOwnPropertyDescriptor(proto, 'value');

                  // Clear current value
                  if (desc && desc.set) {{
                    desc.set.call(input, '');
                  }} else {{
                    input.value = '';
                  }}

                  const Ev = win.Event || Event;
                  const KbEv = win.KeyboardEvent || KeyboardEvent || Ev;

                  // Character-by-character typing simulation
                  let current = '';
                  for (let i = 0; i < val.length; i++) {{
                    const ch = val[i];
                    current += ch;

                    try {{
                      input.dispatchEvent(new KbEv('keydown', {{ key: ch, bubbles: true, cancelable: true }}));
                    }} catch (e) {{}}
                    try {{
                      input.dispatchEvent(new KbEv('keypress', {{ key: ch, bubbles: true, cancelable: true }}));
                    }} catch (e) {{}}

                    if (desc && desc.set) {{
                      desc.set.call(input, current);
                    }} else {{
                      input.value = current;
                    }}

                    try {{
                      input.dispatchEvent(new (win.InputEvent || Ev)('input', {{ bubbles: true, data: ch, inputType: 'insertText' }}));
                    }} catch (e) {{
                      input.dispatchEvent(new Ev('input', {{ bubbles: true }}));
                    }}

                    try {{
                      input.dispatchEvent(new KbEv('keyup', {{ key: ch, bubbles: true, cancelable: true }}));
                    }} catch (e) {{}}

                    if (win.ko && typeof win.ko.dataFor === 'function') {{
                      try {{
                        const inner = win.ko.dataFor(input);
                        if (inner && typeof inner._value === 'function') {{
                          inner._value(current);
                          if (typeof inner._value.valueHasMutated === 'function') inner._value.valueHasMutated();
                        }}
                      }} catch (e) {{}}
                    }}

                    await new Promise(r => setTimeout(r, 20));
                  }}

                  // Final property assignment to guarantee correctness
                  if (desc && desc.set) {{
                    desc.set.call(input, val);
                  }} else {{
                    input.value = val;
                  }}

                  // Sync Knockout observables
                  if (win.ko) {{
                    try {{
                      if (typeof win.ko.dataFor === 'function') {{
                        const inner = win.ko.dataFor(input);
                        if (inner && typeof inner._value === 'function') {{
                          inner._value(val);
                          if (typeof inner._value.valueHasMutated === 'function') inner._value.valueHasMutated();
                          log('Set inner Knockout observable _value: ' + val);
                        }}
                      }}
                      const hjParent = input.closest ? input.closest('hj-textbox') : (input.parentElement && input.parentElement.tagName === 'HJ-TEXTBOX' ? input.parentElement : null);
                      if (hjParent) {{
                        const parentCtx = (win.ko.contextFor && win.ko.contextFor(hjParent)) || (win.ko.dataFor && win.ko.dataFor(hjParent));
                        if (parentCtx) {{
                          const f = parentCtx.field || (parentCtx.$data && parentCtx.$data.field);
                          if (f && typeof f.value === 'function') {{
                            f.value(val);
                            if (typeof f.value.valueHasMutated === 'function') f.value.valueHasMutated();
                            log('Set outer Knockout observable field.value: ' + val);
                          }} else if (parentCtx.value && typeof parentCtx.value === 'function') {{
                            parentCtx.value(val);
                            if (typeof parentCtx.value.valueHasMutated === 'function') parentCtx.value.valueHasMutated();
                            log('Set outer Knockout observable value: ' + val);
                          }}
                        }}
                      }}
                    }} catch (e) {{}}
                  }}

                  input.dispatchEvent(new Ev('input', {{ bubbles: true }}));
                  input.dispatchEvent(new Ev('change', {{ bubbles: true }}));
                  try {{
                    input.dispatchEvent(new FocusEvent('blur', {{ bubbles: true }}));
                  }} catch (e) {{
                    input.dispatchEvent(new Ev('blur', {{ bubbles: true }}));
                  }}
                  if (typeof input.blur === 'function') input.blur();

                  input.setAttribute('data-efl-nexus-gatepass-typed', val);
                  log('Successfully typed gatepass into field: ' + val);
                  return true;
                }} catch (e) {{
                  log('Error typing gatepass: ' + e);
                  return false;
                }}
              }};

              const fillGatepassIntoInput = typeGatepassIntoInput;

              const findQueryButton = () => {{
                const searchInDoc = (doc) => {{
                  if (!doc || typeof doc.querySelectorAll !== 'function') return null;
                  try {{
                    // 1. Exact match by query.svg icon background in style attribute or background style
                    // User inspection: <div data-bind="style: sourceStyle" style="background: url(&quot;/resources/HighJump%20One%20Platform/query.svg&quot;);"></div>
                    const svgIcon = doc.querySelector("*[style*='query.svg' i], div[style*='query.svg' i], img[src*='query.svg' i], [data-bind*='sourceStyle'][style*='query' i]");
                    const svgSource = svgIcon
                      ? ((svgIcon.getAttribute('style') || '') + ' ' + (svgIcon.getAttribute('src') || '')).toLowerCase()
                      : '';
                    if (svgIcon && svgSource.includes('query')) {{
                      const btn = svgIcon.closest ? svgIcon.closest('a, button, [role="button"], hj-button') : (svgIcon.parentElement && (svgIcon.parentElement.tagName === 'A' || svgIcon.parentElement.tagName === 'BUTTON') ? svgIcon.parentElement : null);
                      if (btn) return btn;
                      return svgIcon;
                    }}

                    // 2. Exact match by span with observableText containing "Query"
                    // User inspection: <span data-bind="text: observableText">Query</span>
                    const observableSpans = [...doc.querySelectorAll("span[data-bind*='observableText'], *[data-bind*='observableText']")];
                    for (const sp of observableSpans) {{
                      if (/^Query$/i.test((sp.textContent || '').trim())) {{
                        const btn = sp.closest ? sp.closest('a, button, [role="button"], hj-button') : (sp.parentElement && (sp.parentElement.tagName === 'A' || sp.parentElement.tagName === 'BUTTON') ? sp.parentElement : null);
                        if (btn) return btn;
                        return sp;
                      }}
                    }}

                    // 3. Exact match by anchor/button with data-bind*='click: click' containing "Query"
                    // User inspection: <a href="#" data-bind="click: click, css: $data.cssClasses">
                    const clickAnchors = [...doc.querySelectorAll("a[data-bind*='click: click'], button[data-bind*='click: click'], a[data-bind*='click'], [data-bind*='click: click']")];
                    for (const a of clickAnchors) {{
                      const txt = (a.textContent || '').trim();
                      if (/^Query$/i.test(txt) || (a.innerHTML && /query\\.svg/i.test(a.innerHTML))) return a;
                    }}

                    // 4. Knockout inspection on links/buttons
                    const win = doc.defaultView || (typeof window !== 'undefined' ? window : null);
                    if (win && win.ko && typeof win.ko.dataFor === 'function') {{
                      const allLinks = [...doc.querySelectorAll('a, button, [role="button"], hj-button')];
                      for (const el of allLinks) {{
                        try {{
                          const data = win.ko.dataFor(el);
                          if (data) {{
                            const text = typeof data.observableText === 'function' ? data.observableText() : data.observableText;
                            const src = typeof data.sourceStyle === 'function' ? JSON.stringify(data.sourceStyle()) : JSON.stringify(data.sourceStyle || '');
                            if (String(text).trim().toLowerCase() === 'query' || (src && src.toLowerCase().includes('query.svg'))) return el;
                          }}
                        }} catch (e) {{}}
                      }}
                    }}

                    // 5. Explicit data-hj-test-id
                    const byTestId = doc.querySelector("[data-hj-test-id*='query' i], [data-hj-test-id*='Query']");
                    if (byTestId) return byTestId;

                    // 6. Clickable elements matching Query text or title/aria-label (excluding Reset)
                    const clickable = [...doc.querySelectorAll('button, a, hj-button, [role="button"], span, div')];
                    const match = clickable.find(el => {{
                      const txt = (el.textContent || '').trim();
                      if (/^(?:Query|Run Query)$/i.test(txt)) return true;
                      const title = (el.getAttribute('title') || '').trim();
                      const aria = (el.getAttribute('aria-label') || '').trim();
                      return /^Query$/i.test(title) || /^Query$/i.test(aria);
                    }});
                    if (match) {{
                      const btn = match.closest ? match.closest('button, a, [role="button"], hj-button') : null;
                      return btn || match;
                    }}

                    // 7. Toolbar items containing word "Query" without "Reset"
                    const toolbarItem = clickable.find(el => {{
                      const txt = (el.textContent || '').trim();
                      const words = txt.split(/\\s+/);
                      return words.some(w => /^query$/i.test(w)) && !words.some(w => /^reset$/i.test(w)) && txt.length <= 25;
                    }});
                    if (toolbarItem) {{
                      const btn = toolbarItem.closest ? toolbarItem.closest('button, a, [role="button"], hj-button') : null;
                      return btn || toolbarItem;
                    }}

                    return null;
                  }} catch (e) {{
                    return null;
                  }}
                }};

                const searchAllDocs = (rootDoc) => {{
                  if (!rootDoc) return null;
                  const res = searchInDoc(rootDoc);
                  if (res) return res;
                  try {{
                    const frames = [...rootDoc.querySelectorAll('iframe, frame')];
                    for (const frame of frames) {{
                      try {{
                        const cdoc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
                        if (cdoc) {{
                          const nested = searchAllDocs(cdoc);
                          if (nested) return nested;
                        }}
                      }} catch (e) {{}}
                    }}
                  }} catch (e) {{}}
                  return null;
                }};

                let target = searchAllDocs(document);
                if (target) return target;

                try {{
                  if (window.frames && window.frames.length > 0) {{
                    for (let i = 0; i < window.frames.length; i++) {{
                      try {{
                        const fdoc = window.frames[i].document;
                        if (fdoc) {{
                          target = searchAllDocs(fdoc);
                          if (target) return target;
                        }}
                      }} catch (e) {{}}
                    }}
                  }}
                }} catch (e) {{}}

                return null;
              }};

              const clickQueryButton = (btn) => {{
                if (!btn) return false;
                try {{
                  const doc = btn.ownerDocument || document;
                  const win = (doc && doc.defaultView) || (btn.ownerDocument && btn.ownerDocument.defaultView) || (typeof window !== 'undefined' ? window : null);
                  log('Clicking Query button to execute loading history report');

                  if (typeof btn.focus === 'function') {{
                    try {{ btn.focus(); }} catch (e) {{}}
                  }}

                  const span = btn.querySelector ? btn.querySelector("span[data-bind*='observableText'], span") : null;
                  const icon = btn.querySelector ? btn.querySelector("*[style*='query.svg' i], [data-bind*='sourceStyle']") : null;
                  const ko = (win && win.ko) || (typeof window !== 'undefined' && window.ko);
                  const vm = (ko && typeof ko.dataFor === 'function')
                    ? (ko.dataFor(btn) || (span ? ko.dataFor(span) : null) || (icon ? ko.dataFor(icon) : null))
                    : null;

                  // A single native click is important here. Combining native,
                  // synthetic, jQuery, and direct Knockout clicks submits the
                  // report several times and invalidates HighJump's export token.
                  let vmRan = false;
                  if (vm && typeof vm.click === 'function') {{
                    const origClick = vm.click;
                    vm.click = function(...args) {{
                      vmRan = true;
                      return origClick.apply(this, args);
                    }};
                  }}

                  if (typeof btn.click === 'function') {{
                    btn.click();
                  }} else {{
                    return false;
                  }}

                  // Minimal fallback for non-browser/synthetic environments in
                  // which Element.click() does not run the Knockout binding.
                  if (vm && typeof vm.click === 'function' && !vmRan) {{
                    const fakeEvt = (win && win.MouseEvent)
                      ? new win.MouseEvent('click', {{ bubbles: true, cancelable: true, view: win }})
                      : {{ type: 'click' }};
                    vm.click.call(vm, vm, fakeEvt);
                  }}

                  return true;
                }} catch (e) {{
                  log('Error clicking Query button: ' + e);
                  return false;
                }}
              }};

              const findExportButton = () => {{
                const searchInDoc = (doc) => {{
                  if (!doc || typeof doc.querySelectorAll !== 'function') return null;
                  try {{
                    // 1. Exact match by FontAwesome icon: fa-share-square-o or fa-share-square
                    // User inspection: <i data-bind="css: css" class="fa fa-fw fa-share-square-o"></i>
                    const icon = doc.querySelector("i.fa-share-square-o, i[class*='fa-share-square'], i[class*='share-square']");
                    if (icon) {{
                      const btn = icon.closest ? icon.closest('a, button, [role="button"], hj-button') : (icon.parentElement && (icon.parentElement.tagName === 'A' || icon.parentElement.tagName === 'BUTTON') ? icon.parentElement : null);
                      if (btn) return btn;
                      return icon;
                    }}

                    // 2. Exact match by span with observableText containing "Export"
                    // User inspection: <span data-bind="text: observableText">Export</span>
                    const observableSpans = [...doc.querySelectorAll("span[data-bind*='observableText'], *[data-bind*='observableText']")];
                    for (const sp of observableSpans) {{
                      if (/^Export$/i.test((sp.textContent || '').trim())) {{
                        const btn = sp.closest ? sp.closest('a, button, [role="button"], hj-button') : (sp.parentElement && (sp.parentElement.tagName === 'A' || sp.parentElement.tagName === 'BUTTON') ? sp.parentElement : null);
                        if (btn) return btn;
                        return sp;
                      }}
                    }}

                    // 3. Exact match by anchor/button with data-bind*='click: click' containing "Export"
                    // User inspection: <a href="#" data-bind="click: click, css: $data.cssClasses"> ... <span>Export</span></a>
                    const clickAnchors = [...doc.querySelectorAll("a[data-bind*='click: click'], button[data-bind*='click: click'], a[data-bind*='click'], [data-bind*='click: click']")];
                    for (const a of clickAnchors) {{
                      const txt = (a.textContent || '').trim();
                      if (/^Export$/i.test(txt) || (a.innerHTML && /fa-share-square/i.test(a.innerHTML))) return a;
                    }}

                    // 4. Knockout inspection on links/buttons
                    const win = doc.defaultView || (typeof window !== 'undefined' ? window : null);
                    if (win && win.ko && typeof win.ko.dataFor === 'function') {{
                      const allLinks = [...doc.querySelectorAll('a, button, [role="button"], hj-button')];
                      for (const el of allLinks) {{
                        try {{
                          const data = win.ko.dataFor(el);
                          if (data) {{
                            const text = typeof data.observableText === 'function' ? data.observableText() : data.observableText;
                            if (String(text).trim().toLowerCase() === 'export') return el;
                          }}
                        }} catch (e) {{}}
                      }}
                    }}

                    // 5. Explicit data-hj-test-id
                    const byTestId = doc.querySelector("[data-hj-test-id*='export' i], [data-hj-test-id*='Export']");
                    if (byTestId) return byTestId;

                    // 6. Clickable elements matching Export text or title/aria-label
                    const clickable = [...doc.querySelectorAll('button, a, hj-button, [role="button"], span, div')];
                    const match = clickable.find(el => {{
                      const txt = (el.textContent || '').trim();
                      if (/^(?:Export|Export Report)$/i.test(txt)) return true;
                      const title = (el.getAttribute('title') || '').trim();
                      const aria = (el.getAttribute('aria-label') || '').trim();
                      return /^Export$/i.test(title) || /^Export$/i.test(aria);
                    }});
                    if (match) {{
                      const btn = match.closest ? match.closest('button, a, [role="button"], hj-button') : null;
                      return btn || match;
                    }}

                    return null;
                  }} catch (e) {{
                    return null;
                  }}
                }};

                const searchAllDocs = (rootDoc) => {{
                  if (!rootDoc) return null;
                  const res = searchInDoc(rootDoc);
                  if (res) return res;
                  try {{
                    const frames = [...rootDoc.querySelectorAll('iframe, frame')];
                    for (const frame of frames) {{
                      try {{
                        const cdoc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
                        if (cdoc) {{
                          const nested = searchAllDocs(cdoc);
                          if (nested) return nested;
                        }}
                      }} catch (e) {{}}
                    }}
                  }} catch (e) {{}}
                  return null;
                }};

                let target = searchAllDocs(document);
                if (target) return target;

                try {{
                  if (window.frames && window.frames.length > 0) {{
                    for (let i = 0; i < window.frames.length; i++) {{
                      try {{
                        const fdoc = window.frames[i].document;
                        if (fdoc) {{
                          target = searchAllDocs(fdoc);
                          if (target) return target;
                        }}
                      }} catch (e) {{}}
                    }}
                  }}
                }} catch (e) {{}}

                return null;
              }};

              let exportSubmitted = false;
              const clickExportButton = (btn) => {{
                if (!btn || exportSubmitted) return false;
                try {{
                  exportSubmitted = true;
                  if (typeof sessionStorage !== 'undefined' && sessionStorage.setItem) {{
                    sessionStorage.setItem('eflNexusLoadingHistoryExportSubmitted', '1');
                  }}
                  log('Executing single clean click on Export button');

                  const doc = btn.ownerDocument || document;
                  const win = (doc && doc.defaultView) || (btn.ownerDocument && btn.ownerDocument.defaultView) || (typeof window !== 'undefined' ? window : null);

                  if (typeof btn.focus === 'function') {{
                    try {{ btn.focus(); }} catch (e) {{}}
                  }}

                  const ko = (win && win.ko) || (typeof window !== 'undefined' && window.ko);
                  const vm = (ko && typeof ko.dataFor === 'function')
                    ? (ko.dataFor(btn) || (btn.querySelector ? ko.dataFor(btn.querySelector('span')) : null) || (btn.querySelector ? ko.dataFor(btn.querySelector('i')) : null))
                    : null;

                  let vmRan = false;
                  if (vm && typeof vm.click === 'function') {{
                    const origClick = vm.click;
                    vm.click = function(...args) {{
                      vmRan = true;
                      return origClick.apply(this, args);
                    }};
                  }}

                  // 1. Native click on the button element (triggers Knockout data-bind="click: click" naturally)
                  if (typeof btn.click === 'function') {{
                    btn.click();
                  }}

                  // 2. If in a synthetic test/mock environment where addEventListener wasn't bound, invoke vm.click directly
                  if (vm && typeof vm.click === 'function' && !vmRan) {{
                    const fakeEvt = (win && win.MouseEvent)
                      ? new win.MouseEvent('click', {{ bubbles: true, cancelable: true, view: win }})
                      : {{ type: 'click' }};
                    vm.click.call(vm, vm, fakeEvt);
                  }}

                  return true;
                }} catch (e) {{
                  log('Error clicking Export button: ' + e);
                  return false;
                }}
              }};

              let attempts = 0;
              let lastMenuClick = 0;
              let searchEntered = false;
              let isTyping = false;
              let queryClickCount = 0;
              let lastQueryClickTime = 0;
              let lastQueriedGatepass = '';
              let exportClickCount = 0;
              let lastExportClickTime = 0;

              const automate = async () => {{
                attempts++;

                // Auto-Recovery: Check if the page is displaying HighJump ASP.NET Yellow Screen of Death error
                try {{
                  const checkTexts = [(document.body && document.body.textContent) || ''];
                  const iframes = [...document.querySelectorAll('iframe')];
                  for (const f of iframes) {{
                    try {{
                      const fdoc = f.contentDocument || (f.contentWindow && f.contentWindow.document);
                      if (fdoc && fdoc.body) checkTexts.push(fdoc.body.textContent || '');
                    }} catch (e) {{}}
                  }}
                  for (const txt of checkTexts) {{
                    if (txt.includes("Server Error in '/SupplyChainAdvantage'") || (txt.includes('Export [') && txt.includes('was not found'))) {{
                      log('Detected HighJump Server Error (Export was not found). Returning to rerun Query before exporting...');
                      if (typeof sessionStorage !== 'undefined' && sessionStorage.removeItem) {{
                        sessionStorage.setItem('eflNexusLoadingHistoryRecoveryNeeded', '1');
                        sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                        sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                      }}
                      exportSubmitted = false;
                      exportClickCount = 0;
                      queryClickCount = 0;
                      lastQueryClickTime = 0;
                      if (window.history && typeof window.history.back === 'function' && window.history.length > 1) {{
                        window.history.back();
                      }} else {{
                        window.location.reload();
                      }}
                      return;
                    }}
                  }}
                }} catch (e) {{}}

                // A failed export can restore this report from the browser's
                // back-forward cache without re-running the page-load hook.
                // Consume the recovery marker here so the restored page always
                // performs a fresh Query and obtains a valid export token.
                if (sessionStorage.getItem('eflNexusLoadingHistoryRecoveryNeeded') === '1') {{
                  sessionStorage.removeItem('eflNexusLoadingHistoryRecoveryNeeded');
                  sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                  sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                  queryClickCount = 0;
                  lastQueryClickTime = 0;
                  lastQueriedGatepass = '';
                  exportClickCount = 0;
                  lastExportClickTime = 0;
                  exportSubmitted = false;
                }}

                const username = document.querySelector("hj-textbox[data-hj-test-id='username'] input, input.k-textbox[placeholder='User Name']");
                const password = document.querySelector("hj-password-textbox[data-hj-test-id='password'] input, input[type='password']");
                if (username && password && username.getClientRects().length > 0 && password.getClientRects().length > 0) {{
                  const loginButton = document.querySelector("hj-button[data-hj-test-id='actionButton'] button")
                    || [...document.querySelectorAll('hj-button button, button')].find(button => button.textContent.trim() === 'Login');
                  if (loginButton && !sessionStorage.getItem('eflNexusKorberLoginSubmitted')) {{
                    setValue(username, {user_value});
                    setValue(password, {password_value});
                    log('Submitting login form');
                    loginButton.click();
                    sessionStorage.setItem('eflNexusKorberLoginSubmitted', '1');
                  }}
                  if (attempts < 240) setTimeout(automate, 250);
                  return;
                }}

                const menuToggle = document.querySelector("a#menuButtonToggle[data-hj-test-id='menuButtonToggle']");
                if (menuToggle && !sessionStorage.getItem('eflNexusLoadingHistoryReportOpened')) {{
                  const menuIsOpen = menuToggle.classList.contains('active') || menuToggle.getAttribute('aria-expanded') === 'true';
                  if (!menuIsOpen && Date.now() - lastMenuClick > 1000) {{
                    log('Clicking hamburger menu');
                    menuToggle.click();
                    lastMenuClick = Date.now();
                  }}
                  const searchBox = document.querySelector("input[data-hj-test-id='menuSearchTextBox']");
                  if (searchBox && searchBox.getClientRects().length > 0) {{
                    if (!searchEntered || searchBox.value !== '1992') {{
                      setValue(searchBox, '1992');
                      searchBox.dispatchEvent(new Event('keyup', {{ bubbles: true }}));
                      searchBox.focus();
                      searchEntered = true;
                      log('Entered menu code 1992');
                    }}
                    const title = [...document.querySelectorAll('a span.title')]
                      .find(span => span.textContent.trim() === 'Loading History Report' && span.getClientRects().length > 0);
                    const reportLink = title && title.closest('a');
                    if (reportLink && reportLink.getClientRects().length > 0) {{
                      log('Clicking Loading History Report');
                      // Do not carry a completed query/export state into a new
                      // report instance; those server-side tokens are per run.
                      if (typeof sessionStorage.removeItem === 'function') {{
                        sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                        sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                        sessionStorage.removeItem('eflNexusLoadingHistoryRecoveryNeeded');
                        sessionStorage.removeItem('eflNexusLoadingHistoryStoppedAtGatepass');
                      }}
                      reportLink.click();
                      sessionStorage.setItem('eflNexusLoadingHistoryReportOpened', '1');
                      setTimeout(automate, 250);
                      return;
                    }}
                  }}
                  if (attempts < 240) setTimeout(automate, 250);
                  else log('Timed out waiting for the Loading History Report menu item');
                  return;
                }}

                if (stopAtGatepass && typeof sessionStorage !== 'undefined' && sessionStorage.getItem('eflNexusLoadingHistoryStoppedAtGatepass') === '1') {{
                  if (!manualStopBypassed) {{
                    return;
                  }}
                }}

                const hasSubmittedQuery = queryClickCount > 0 || sessionStorage.getItem('eflNexusLoadingHistoryQuerySubmitted') === '1';

                // Step 1: Check for gatepass input and execute query (if not yet submitted)
                if (!hasSubmittedQuery) {{
                  const gpInput = findGatepassInput();
                  if (stopAtGatepass && gpInput) {{
                    if (!manualStopBypassed) {{
                      try {{
                        if (typeof gpInput.focus === 'function') gpInput.focus();
                        if (typeof gpInput.scrollIntoView === 'function') {{
                          gpInput.scrollIntoView({{ block: 'center', inline: 'center' }});
                        }}
                      }} catch (e) {{}}
                      log('Gate Pass entry page is ready; waiting for user input.');
                      sessionStorage.setItem('eflNexusLoadingHistoryStoppedAtGatepass', '1');
                      return;
                    }}
                  }}
                  if (gpInput && !isTyping) {{
                    let gp = activeGatepass;
                    if (!gp) gp = await resolveGatepass();
                    if (gp && gpInput.value !== gp && gpInput.getAttribute('data-efl-nexus-gatepass-typed') !== gp) {{
                      isTyping = true;
                      try {{
                        queryClickCount = 0;
                        lastQueryClickTime = 0;
                        lastQueriedGatepass = '';
                        exportClickCount = 0;
                        lastExportClickTime = 0;
                        exportSubmitted = false;
                        if (typeof sessionStorage.removeItem === 'function') {{
                          sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                          sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                        }}
                        await typeGatepassIntoInput(gpInput, gp);
                      }} finally {{
                        isTyping = false;
                      }}
                    }}
                  }}

                  // Click Query button once gatepass has been typed
                  const currentVal = (gpInput && gpInput.value ? gpInput.value.trim() : '') || (gpInput ? (gpInput.getAttribute('data-efl-nexus-gatepass-typed') || '') : '');
                  const targetGp = activeGatepass;
                  const isReadyToQuery = targetGp ? currentVal === targetGp : currentVal.length > 0;

                  if (isReadyToQuery && !isTyping) {{
                    const now = Date.now();
                    if (queryClickCount < 3 && (now - lastQueryClickTime > 2000)) {{
                      const queryBtn = findQueryButton();
                      if (queryBtn) {{
                        log('Found Query button (' + (queryBtn.tagName || 'ELEMENT') + '), executing query (attempt ' + (queryClickCount + 1) + ')');
                        const clicked = clickQueryButton(queryBtn);
                        if (clicked) {{
                          queryClickCount++;
                          lastQueryClickTime = now;
                          lastQueriedGatepass = currentVal;
                          sessionStorage.setItem('eflNexusLoadingHistoryQuerySubmitted', '1');
                          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.report_gatepass === 'function') {{
                            try {{ window.pywebview.api.report_gatepass(currentVal); }} catch (e) {{}}
                          }}
                        }}
                      }} else {{
                        log('Gatepass is ready (' + currentVal + '), searching for Query button across documents/iframes...');
                      }}
                    }}
                  }}
                }}

                // Step 2: Execute Export once Query has been submitted
                const hasExported = exportClickCount > 0 || exportSubmitted || sessionStorage.getItem('eflNexusLoadingHistoryExportSubmitted') === '1';
                if (hasSubmittedQuery && !hasExported) {{
                  const now = Date.now();
                  const timeSinceQuery = lastQueryClickTime > 0 ? (now - lastQueryClickTime) : 2500;
                  // Allow at least 2500ms after query click for server query roundtrip completion
                  if (timeSinceQuery >= 2500) {{
                    const exportBtn = findExportButton();
                    if (exportBtn) {{
                      const isDisabled = (exportBtn.classList && (exportBtn.classList.contains('k-state-disabled') || exportBtn.classList.contains('disabled'))) ||
                                         exportBtn.getAttribute('aria-disabled') === 'true' ||
                                         exportBtn.getAttribute('disabled') !== null;
                      let isMaskVisible = false;
                      try {{
                        const btnDoc = exportBtn.ownerDocument || document;
                        const mask = btnDoc.querySelector('.k-loading-mask, .k-loading-image, .k-i-loading') || document.querySelector('.k-loading-mask, .k-loading-image, .k-i-loading');
                        if (mask && (mask.offsetParent !== null || (mask.getClientRects && mask.getClientRects().length > 0))) {{
                          isMaskVisible = true;
                        }}
                      }} catch (e) {{}}

                      if (isDisabled || isMaskVisible) {{
                        log('Query in progress (grid loading / Export button disabled), waiting for data before export...');
                      }} else {{
                        log('Found active Export button (' + (exportBtn.tagName || 'ELEMENT') + '), executing single export click');
                        const clicked = clickExportButton(exportBtn);
                        if (clicked) {{
                          exportClickCount = 1;
                          lastExportClickTime = now;
                        }}
                      }}
                    }} else {{
                      log('Query submitted, searching for Export button across documents/iframes...');
                    }}
                  }}
                }}

                if (attempts < 240) setTimeout(automate, 250);
                else log('Timed out waiting for Loading History page elements');
              }};
              automate();

              const pollLoadingHistoryCommands = async () => {{
                if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.get_pending_command !== 'function') return;
                try {{
                  const cmd = await window.pywebview.api.get_pending_command();
                  if (cmd && (cmd.gatepass || cmd.action === 'query_and_export' || cmd.action === 'download_loading_history')) {{
                    const newGp = String(cmd.gatepass || '').trim();
                    log('Received command to query and export gatepass: ' + newGp);
                    activeGatepass = newGp;
                    manualStopBypassed = true;
                    try {{
                      sessionStorage.removeItem('eflNexusLoadingHistoryStoppedAtGatepass');
                      sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                      sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                    }} catch (e) {{}}
                    queryClickCount = 0;
                    lastQueryClickTime = 0;
                    lastQueriedGatepass = '';
                    exportClickCount = 0;
                    lastExportClickTime = 0;
                    exportSubmitted = false;
                    attempts = 0;
                    automate();
                  }}
                }} catch (e) {{}}
              }};
              if (typeof setInterval === 'function') {{
                setInterval(pollLoadingHistoryCommands, 500);
              }}
            }})();
        """)

    stop_watcher = threading.Event()

    def watch_downloads() -> None:
        import shutil
        downloads_dir = get_downloads_folder()
        try:
            initial_files = {p.resolve(): p.stat().st_mtime for p in downloads_dir.iterdir() if p.is_file()}
        except Exception:
            initial_files = {}

        moved_files: set[Path] = set()

        while not stop_watcher.is_set():
            time.sleep(0.5)
            try:
                for file_path in downloads_dir.iterdir():
                    if not file_path.is_file():
                        continue
                    suffix = file_path.suffix.lower()
                    if suffix not in (".xlsx", ".xls", ".csv"):
                        continue
                    resolved_file = file_path.resolve()
                    if resolved_file in moved_files:
                        continue
                    if resolved_file in initial_files:
                        try:
                            if file_path.stat().st_mtime <= initial_files[resolved_file]:
                                continue
                        except Exception:
                            continue

                    # Check for companion .crdownload
                    companion = file_path.with_name(file_path.name + ".crdownload")
                    if companion.exists():
                        continue

                    # Check for any active .crdownload matching stem
                    has_cr = any(cr.name.startswith(file_path.stem) for cr in downloads_dir.glob("*.crdownload"))
                    if has_cr:
                        continue

                    # Ensure file is completely written (not locked and size > 0)
                    try:
                        sz1 = file_path.stat().st_size
                        if sz1 == 0:
                            continue
                        time.sleep(0.3)
                        sz2 = file_path.stat().st_size
                        if sz1 != sz2:
                            continue
                        with open(file_path, "rb"):
                            pass
                    except (OSError, PermissionError):
                        continue

                    # Resolve destination folder
                    active_gp = bridge.get_gatepass() or gatepass
                    active_jid = bridge.get_job_id() or job_id
                    active_cli = bridge.get_client() or client
                    if not active_jid or not active_cli:
                        p_map = load_persisted_job_map()
                        if active_gp:
                            for m in p_map.values():
                                if _clean(str(m.get("gatepass", ""))) == active_gp:
                                    if not active_jid:
                                        active_jid = _clean(str(m.get("job_id", "")))
                                    if not active_cli:
                                        active_cli = _clean(str(m.get("client", "")))
                                    break

                    dest_folder = get_job_download_folder(job_id=active_jid, gatepass=active_gp, client=active_cli)
                    if dest_folder.resolve() == downloads_dir.resolve():
                        moved_files.add(resolved_file)
                        continue

                    dest_path = get_unique_download_path(file_path.name, folder=dest_folder)
                    try:
                        shutil.move(str(file_path), str(dest_path))
                        moved_files.add(dest_path.resolve())
                        print(f"[Loading History] Organized report file -> {dest_path.resolve()}", flush=True)

                        try:
                            dl_event_file = _download_event_file()
                            dl_event_file.parent.mkdir(parents=True, exist_ok=True)
                            dl_event_file.write_text(json.dumps({
                                "action": "file_downloaded",
                                "filename": dest_path.name,
                                "path": str(dest_path.resolve()),
                                "folder": dest_path.parent.name,
                                "folder_path": str(dest_path.parent.resolve()),
                                "size": dest_path.stat().st_size,
                                "time": time.time(),
                                "job_id": active_jid,
                                "gatepass": active_gp,
                                "client": active_cli,
                            }), encoding="utf-8")
                        except Exception:
                            pass
                    except Exception as move_err:
                        print(f"[Loading History] Error moving {file_path.name}: {move_err}", flush=True)
            except Exception:
                pass

    watcher_thread = threading.Thread(target=watch_downloads, daemon=True)
    watcher_thread.start()

    window.events.loaded += automate_loading_history
    try:
        webview.start(gui="edgechromium", private_mode=True)
    finally:
        stop_watcher.set()


def _clean(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _clean(value).casefold())


def normalize_reconciliation_status(raw: str) -> str:
    """Normalize portal reconciliation status strings.

    If status contains 'pending' -> 'Pending'.
    If status contains 'progress' (e.g. 'on Progress', 'in progress', 'InProgress') -> 'In Progress'.
    If status contains 'complete' or 'done' -> 'Completed'.
    If empty or unrecognized -> 'Unknown' (or title-cased if non-empty).
    """
    clean_val = _clean(raw)
    lowered = clean_val.casefold()
    if not lowered:
        return "Unknown"
    if "pending" in lowered:
        return "Pending"
    if "progress" in lowered:
        return "In Progress"
    if "complete" in lowered or "done" in lowered:
        return "Completed"
    return clean_val.title()


def extract_jobs_with_status(
    headers: list[str],
    rows: list[list[str]],
    requested_header: str = "",
    include_client: bool = False,
    include_details: bool = False,
) -> list[dict[str, str]]:
    """Return all unique Job IDs along with their normalized reconciliation status."""
    wanted = _normalise(requested_header)
    normal_headers = [_normalise(header) for header in headers]
    column = next((i for i, header in enumerate(normal_headers) if wanted and header == wanted), None)
    if column is None:
        column = next(
            (i for i, header in enumerate(normal_headers)
             if header in {"jobid", "jobnumber", "jobno", "job", "job#"}),
            None,
        )
    if column is None:
        return []
    client_column = next(
        (i for i, header in enumerate(normal_headers)
         if header in {"client", "customer", "clientname", "account"}
         or "client" in header),
        None,
    )
    wh_column = next(
        (i for i, header in enumerate(normal_headers)
         if header in {"wh", "warehouse", "warehouseid", "whid"} or header.startswith("wh")),
        None,
    )
    gatepass_column = next(
        (i for i, header in enumerate(normal_headers)
         if header in {"gatepass", "gatepassno", "gatepassnumber", "gatepassid", "gp", "gpno"}
         or "gatepass" in header),
        None,
    )
    seal_column = next(
        (i for i, header in enumerate(normal_headers)
         if header in {"sealnumber", "sealno", "seal", "seal#"} or "seal" in header),
        None,
    )
    delivery_column = next(
        (i for i, header in enumerate(normal_headers)
         if header in {"deliverylocation", "delivery", "destination", "deliveryto"} or "delivery" in header),
        None,
    )
    status_column = next(
        (i for i, header in enumerate(normal_headers)
         if header in {"reconciliationstatus", "status", "reconstatus", "jobstatus", "state"}
         or "reconciliation" in header or "status" in header),
        None,
    )
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if column >= len(row):
            continue
        value = _clean(row[column])
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        client_val = ""
        if client_column is not None and client_column < len(row):
            client_val = _clean(row[client_column])
        wh_val = ""
        if wh_column is not None and wh_column < len(row):
            wh_val = _clean(row[wh_column])
        gp_val = ""
        if gatepass_column is not None and gatepass_column < len(row):
            gp_val = _clean(row[gatepass_column])
        seal_val = ""
        if seal_column is not None and seal_column < len(row):
            seal_val = _clean(row[seal_column])
        deliv_val = ""
        if delivery_column is not None and delivery_column < len(row):
            deliv_val = _clean(row[delivery_column])
        raw_status = ""
        if status_column is not None and status_column < len(row):
            raw_status = row[status_column]
        if not _clean(raw_status):
            raw_status = next(
                (cell for cell in row if normalize_reconciliation_status(cell) in {"Pending", "In Progress"}),
                "",
            )
        rec = {
            "job_id": value,
            "status": normalize_reconciliation_status(raw_status),
        }
        if include_client or include_details:
            rec["client"] = client_val
        if include_details:
            rec["warehouse"] = wh_val
            rec["gatepass"] = gp_val
            rec["seal"] = seal_val
            rec["delivery_location"] = deliv_val
        records.append(rec)
    return records


def job_ids_from_rows(
    headers: list[str], rows: list[list[str]], requested_header: str = "", required_status: str | None = None,
) -> list[str]:
    """Return de-duplicated Job IDs, optionally limited to an exact row status."""
    wanted = _normalise(requested_header)
    normal_headers = [_normalise(header) for header in headers]
    column = next((i for i, header in enumerate(normal_headers) if wanted and header == wanted), None)
    if column is None:
        column = next(
            (i for i, header in enumerate(normal_headers)
             if header in {"jobid", "jobnumber", "jobno"}),
            None,
        )
    if column is None:
        return []
    status_column = None
    if required_status:
        status_column = next(
            (i for i, header in enumerate(normal_headers) if header == "reconciliationstatus"),
            None,
        )
        if status_column is None:
            return []
    found: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if column >= len(row) or (status_column is not None and status_column >= len(row)):
            continue
        if status_column is not None and _clean(row[status_column]).casefold() != required_status.casefold():
            continue
        value = _clean(row[column])
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            found.append(value)
    return found


class WebsiteDataGrabberApp:
    """Embedded Tk UI and visible Selenium runner for the authorised portal."""

    def __init__(
        self,
        root: tk.Misc,
        container=None,
        standalone=True,
        config_store=None,
        on_open_settings=None,
        on_job_started=None,
        on_create_gatepass=None,
    ):
        self.root = root
        self.container = container or root
        self.standalone = standalone
        if config_store is None:
            try:
                from outlook_email_gui import ConfigStore, CONFIG_JSON_PATH
                config_store = ConfigStore(CONFIG_JSON_PATH)
            except Exception:
                config_store = None
        self.config_store = config_store
        self.on_open_settings = on_open_settings
        # Optional callback: on_job_started(job_id) — invoked when the operator
        # clicks Start on a job row so other tools (e.g., User KPI) can react.
        self.on_job_started = on_job_started
        # Optional callback: on_create_gatepass(job_record) — invoked when the
        # operator clicks 'Create Gatepass' to send data to Korber Automation.
        self.on_create_gatepass = on_create_gatepass
        self.driver = None
        self.running = False
        self.job_ids: list[str] = []
        self.records: list[dict[str, str]] = []
        self.result_path = _result_file()
        # The result file persists across runs. Do not show it until the browser
        # opened by this app instance has written a newer live snapshot.
        self._live_result_baseline_mtime_ns = 0
        self.browser_log_path = _browser_log_file()
        self.download_event_path = _download_event_file()
        self.loading_history_event_path = _loading_history_event_file()
        self._last_loading_history_time = 0.0
        if self.loading_history_event_path.exists():
            try:
                event = json.loads(self.loading_history_event_path.read_text(encoding="utf-8"))
                self._last_loading_history_time = float(event.get("time", 0.0))
            except Exception:
                pass
        self._last_download_time = 0.0
        if self.download_event_path.exists():
            try:
                dl_data = json.loads(self.download_event_path.read_text(encoding="utf-8"))
                self._last_download_time = float(dl_data.get("time", 0.0))
            except Exception:
                pass
        self._browser_log_handle = None
        self.browser_process = None
        self.browser_hwnd = None
        self.loading_history_process = None
        self.loading_history_hwnd = None
        self._browser_embed_attempts = 0
        self._loading_history_embed_attempts = 0
        settings = getattr(self.config_store, "config", {}) if self.config_store is not None else {}
        self.login_url = tk.StringVar(value=settings.get("data_grabber_login_url", DEFAULT_LOGIN_URL))
        self.username = tk.StringVar(value=settings.get("data_grabber_user", ""))
        self.password = tk.StringVar(value=_load_saved_password())
        self.reconciliation_url = tk.StringVar(value=settings.get("data_grabber_reconciliation_url", DEFAULT_RECONCILIATION_URL))
        self.refresh_seconds = tk.StringVar(value=str(parse_refresh_seconds(settings.get("data_grabber_refresh_seconds", str(DEFAULT_REFRESH_SECONDS)), default=DEFAULT_REFRESH_SECONDS)))
        self.sound_enabled = tk.BooleanVar(value=bool(settings.get("data_grabber_sound_enabled", True)))
        self.sound_path = tk.StringVar(value=str(settings.get("data_grabber_sound_path", "")))
        self._seen_pending_ids: set[str] = set()
        self.reconciliation_link_text = tk.StringVar(value="Reconciliation")
        self.job_header = tk.StringVar(value="Job ID")
        initial_status = (
            "Ready. Click 'Open Both Browsers' to launch Reconciliation and Loading History."
            if self.username.get() and self.password.get()
            else "Enter portal credentials in Settings to automatically sign in and open Reconciliation."
        )
        self.status = tk.StringVar(value=initial_status)
        self._build()
        self.root.after(500, self._poll_internal_browser_results)

    def _build(self):
        page = tk.Frame(self.container, bg="#faf8f2", padx=16, pady=8)
        page.pack(fill="both", expand=True)

        # Compact single-row top banner to maximize vertical height for the browser
        header_bar = tk.Frame(page, bg="#faf8f2")
        header_bar.pack(fill="x", pady=(0, 6))

        tk.Label(header_bar, text="Pending Jobs", bg="#faf8f2", fg="#0f172a", font=("Segoe UI", 13, "bold")).pack(side="left")
        self.run_button = ttk.Button(header_bar, text="Open Both Browsers", command=self.start)
        self.run_button.pack(side="left", padx=(14, 0))
        self.restart_button = ttk.Button(header_bar, text="🔄 Restart Browser", command=self.restart_browser)
        self.restart_button.pack(side="left", padx=(6, 0))
        tk.Label(header_bar, textvariable=self.status, bg="#faf8f2", fg="#475569", font=("Segoe UI", 9)).pack(side="left", padx=10)

        if self.on_open_settings:
            ttk.Button(header_bar, text="⚙ Settings", command=self.on_open_settings).pack(side="right")

        results = tk.Frame(page, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=10, pady=6)
        results.pack(fill="both", expand=True)
        results.columnconfigure(0, weight=1)
        results.columnconfigure(1, weight=1)
        results.rowconfigure(0, weight=3, minsize=520)
        results.rowconfigure(1, weight=1, minsize=100)

        # ---------------- Top: Internal Reconciliation Browser ----------------
        browser_panel = tk.Frame(results, bg="#ffffff")
        browser_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 3), pady=(0, 6))
        browser_panel.columnconfigure(0, weight=1)
        browser_panel.rowconfigure(1, weight=1)

        browser_header = tk.Frame(browser_panel, bg="#ffffff")
        browser_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(browser_header, text="Internal Reconciliation Browser", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 10, "bold")).pack(side="left")
        
        # Live auto-refresh badge & inline interval selector
        self.auto_refresh_badge = tk.Label(browser_header, text="⚡ Auto-Refresh: 5s", bg="#ffffff", fg="#16a34a", font=("Segoe UI", 8, "bold"))
        self.auto_refresh_badge.pack(side="left", padx=(10, 8))

        tk.Label(browser_header, text="⏱ Interval:", bg="#ffffff", fg="#64748b", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(4, 2))
        self.refresh_combo = ttk.Combobox(
            browser_header,
            values=["5s", "10s", "15s", "30s", "60s", "120s", "Off"],
            width=6,
            font=("Segoe UI", 8),
        )
        self.refresh_combo.pack(side="left", padx=(0, 8))
        self.refresh_combo.bind("<<ComboboxSelected>>", self._on_refresh_interval_changed)
        self.refresh_combo.bind("<Return>", self._on_refresh_interval_changed)
        self.refresh_combo.bind("<FocusOut>", self._on_refresh_interval_changed)

        self.sound_button = tk.Button(
            browser_header,
            text="🔔 Sound: On" if self.sound_enabled.get() else "🔕 Sound: Off",
            command=self.toggle_sound,
            bg="#f1f5f9",
            fg="#16a34a" if self.sound_enabled.get() else "#64748b",
            activebackground="#e2e8f0",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=6,
            pady=1,
            cursor="hand2",
        )
        self.sound_button.pack(side="left", padx=(0, 8))

        self.home_button = ttk.Button(browser_header, text="🏠 Reconciliation", command=self.browser_go_home)
        self.home_button.pack(side="right", padx=(4, 0))
        self.reload_button = ttk.Button(browser_header, text="🔄 Reload", command=self.browser_reload)
        self.reload_button.pack(side="right", padx=(4, 0))
        self.back_button = ttk.Button(browser_header, text="◀ Go Back", command=self.browser_go_back)
        self.back_button.pack(side="right", padx=(4, 0))

        # Synchronize badge and combobox to initial refresh_seconds
        self.set_refresh_interval(self.refresh_seconds.get(), save=False)

        self.browser_host = tk.Frame(browser_panel, bg="#e2e8f0", highlightbackground="#cbd5e1", highlightthickness=1)
        self.browser_host.grid(row=1, column=0, sticky="nsew")
        self.browser_host.bind("<Configure>", self._resize_internal_browser)
        tk.Label(
            self.browser_host, text="The Reconciliation browser will appear here after you click Open Both Browsers.",
            bg="#e2e8f0", fg="#64748b", font=("Segoe UI", 10), wraplength=600,
        ).place(relx=0.5, rely=0.5, anchor="center")

        # ---------------- Top-right: Loading History Browser ----------------
        loading_panel = tk.Frame(results, bg="#ffffff")
        loading_panel.grid(row=0, column=1, sticky="nsew", padx=(3, 0), pady=(0, 6))
        loading_panel.columnconfigure(0, weight=1)
        loading_panel.rowconfigure(1, weight=1)

        loading_header = tk.Frame(loading_panel, bg="#ffffff")
        loading_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(
            loading_header,
            text="Loading History — enter Gate Pass manually",
            bg="#ffffff",
            fg="#0f172a",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")

        self.loading_history_host = tk.Frame(
            loading_panel,
            bg="#e2e8f0",
            highlightbackground="#cbd5e1",
            highlightthickness=1,
        )
        self.loading_history_host.grid(row=1, column=0, sticky="nsew")
        self.loading_history_host.bind("<Configure>", self._resize_loading_history_browser)
        tk.Label(
            self.loading_history_host,
            text="Loading History will open here and stop at the Gate Pass entry page.",
            bg="#e2e8f0",
            fg="#64748b",
            font=("Segoe UI", 10),
            wraplength=420,
        ).place(relx=0.5, rely=0.5, anchor="center")

        # ---------------- Bottom: Job Console (IDs, Status & Actions) ----------------
        console_panel = tk.Frame(results, bg="#ffffff")
        console_panel.grid(row=1, column=0, columnspan=2, sticky="nsew")
        console_panel.columnconfigure(0, weight=1)
        console_panel.rowconfigure(1, weight=1)

        console_header = tk.Frame(console_panel, bg="#ffffff")
        console_header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        tk.Label(console_header, text="Reconciliation Job IDs & Status", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 10, "bold")).pack(side="left")

        ttk.Button(console_header, text="📋 Copy", command=self.copy_results).pack(side="right", padx=(4, 0))
        ttk.Button(console_header, text="📄 Export CSV", command=self.export_csv).pack(side="right", padx=(4, 0))

        style = ttk.Style()
        try:
            if style.theme_use() in ("vista", "xpnative", "winnative"):
                style.theme_use("clam")
        except Exception:
            pass

        table_frame = tk.Frame(console_panel, bg="#ffffff")
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_frame, columns=("job_id", "client", "status", "action"), show="headings", selectmode="extended", height=4)
        self.tree.heading("job_id", text="Job ID", anchor="w")
        self.tree.heading("client", text="Client", anchor="w")
        self.tree.heading("status", text="Reconciliation Status", anchor="w")
        self.tree.heading("action", text="Action", anchor="center")
        self.tree.column("job_id", width=240, minwidth=140, stretch=True)
        self.tree.column("client", width=180, minwidth=110, stretch=True)
        self.tree.column("status", width=220, minwidth=130, stretch=True)
        self.tree.column("action", width=110, minwidth=85, stretch=False, anchor="center")
        self.tree.tag_configure("pending", background="#fee2e2", foreground="#b91c1c")
        self.tree.tag_configure("in_progress", background="#fef9c3", foreground="#b45309")
        self.tree.tag_configure("completed", background="#dcfce7", foreground="#15803d")
        self.tree.tag_configure("other", background="#f8fafc", foreground="#334155")
        self.tree.tag_configure("start_action", foreground="#ea580c")
        self.tree.bind("<Control-c>", self._on_tree_copy)
        self.tree.bind("<Control-C>", self._on_tree_copy)
        self.tree.bind("<Button-1>", self._on_tree_button_1)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release_1)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Return>", lambda _e: self.start_selected_job())

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.output = self.tree

        # Action bar below the table with Create Gatepass and Download Files buttons
        action_bar = tk.Frame(table_frame, bg="#ffffff")
        action_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.create_gatepass_btn = tk.Button(
            action_bar,
            text="Create Gatepass",
            command=self.create_gatepass_selected_job,
            bg="#dc2626",
            fg="#ffffff",
            activebackground="#b91c1c",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
        )
        self.create_gatepass_btn.pack(side="left")

        self.download_files_btn = tk.Button(
            action_bar,
            text="📥 Download Files",
            command=self.download_selected_job_files,
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
        )
        self.download_files_btn.pack(side="left", padx=(10, 0))

        self.download_loading_history_btn = tk.Button(
            action_bar,
            text="📥 Download Loading History",
            command=self.download_selected_job_loading_history,
            bg="#2563eb",
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
        )
        self.download_loading_history_btn.pack(side="left", padx=(10, 0))

        self.open_folder_btn = tk.Button(
            action_bar,
            text="📂 Open Folder",
            command=self.open_selected_job_folder,
            bg="#334155",
            fg="#ffffff",
            activebackground="#1e293b",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
        )
        self.open_folder_btn.pack(side="left", padx=(10, 0))

    def _on_refresh_interval_changed(self, _event=None):
        if hasattr(self, "refresh_combo"):
            val = self.refresh_combo.get()
            self.set_refresh_interval(val, save=True)

    def set_refresh_interval(self, seconds: int | str, save: bool = True):
        """Set the auto-refresh interval, update UI badge/combo, persist config, and notify browser."""
        parsed = parse_refresh_seconds(seconds, default=DEFAULT_REFRESH_SECONDS)
        self.refresh_seconds.set(str(parsed))

        display_text = f"{parsed}s" if parsed > 0 else "Off"
        if hasattr(self, "refresh_combo") and self.refresh_combo.get() != display_text:
            self.refresh_combo.set(display_text)

        if hasattr(self, "auto_refresh_badge"):
            if parsed > 0:
                self.auto_refresh_badge.config(text=f"⚡ Auto-Refresh: {parsed}s", fg="#16a34a")
            else:
                self.auto_refresh_badge.config(text="⏸ Auto-Refresh: Off", fg="#64748b")

        if save:
            saved_config = False
            if self.config_store is not None:
                try:
                    saved_config = bool(self.config_store.save(data_grabber_refresh_seconds=str(parsed)))
                except Exception:
                    saved_config = False
            if not saved_config:
                try:
                    from outlook_email_gui import CONFIG_JSON_PATH
                    cfg_path = Path(CONFIG_JSON_PATH)
                except Exception:
                    cfg_path = Path(__file__).resolve().parent / "config.json"
                try:
                    cfg_path.parent.mkdir(parents=True, exist_ok=True)
                    data = {}
                    if cfg_path.exists():
                        try:
                            data = json.loads(cfg_path.read_text(encoding="utf-8"))
                        except Exception:
                            data = {}
                    data["data_grabber_refresh_seconds"] = str(parsed)
                    cfg_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                except Exception:
                    pass

        # Send live update to running browser helper if active
        if self.browser_process is not None and self.browser_process.poll() is None:
            self._send_browser_command("set_refresh_interval", seconds=parsed)

    def toggle_sound(self):
        """Toggle notification sound on or off, updating UI and persisting setting."""
        new_val = not self.sound_enabled.get()
        self.set_sound_enabled(new_val, save=True)

    def set_sound_enabled(self, enabled: bool, save: bool = True):
        self.sound_enabled.set(bool(enabled))
        if hasattr(self, "sound_button"):
            if self.sound_enabled.get():
                self.sound_button.config(text="🔔 Sound: On", fg="#16a34a")
            else:
                self.sound_button.config(text="🔕 Sound: Off", fg="#64748b")
        if save:
            saved = False
            if self.config_store is not None:
                try:
                    saved = bool(self.config_store.save(data_grabber_sound_enabled=self.sound_enabled.get()))
                except Exception:
                    saved = False
            if not saved:
                try:
                    from outlook_email_gui import CONFIG_JSON_PATH
                    cfg_path = Path(CONFIG_JSON_PATH)
                except Exception:
                    cfg_path = Path(__file__).resolve().parent / "config.json"
                try:
                    cfg_path.parent.mkdir(parents=True, exist_ok=True)
                    data = {}
                    if cfg_path.exists():
                        try:
                            data = json.loads(cfg_path.read_text(encoding="utf-8"))
                        except Exception:
                            data = {}
                    data["data_grabber_sound_enabled"] = self.sound_enabled.get()
                    cfg_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                except Exception:
                    pass

    def play_alert(self):
        """Manually test or trigger the pending job notification sound."""
        custom_path = self.sound_path.get().strip() if hasattr(self, "sound_path") else ""
        play_notification_sound(custom_path or None)

    @staticmethod
    def _field(parent, row, label, variable, placeholder="", show=None):
        tk.Label(parent, text=f"{label}:", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 9, "bold"), width=18, anchor="w").grid(row=row, column=0, sticky="w", pady=5, padx=(0, 12))
        entry = ttk.Entry(parent, textvariable=variable, show=show or "", font=("Segoe UI", 9))
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        if placeholder:
            entry.insert(0, placeholder) if not variable.get() else None
            entry.bind("<FocusIn>", lambda _event, e=entry, v=variable, p=placeholder: (v.set("") if v.get() == p else None))

    def start(self):
        login_url = self.login_url.get().strip()
        if not login_url.startswith(("https://", "http://")):
            messagebox.showwarning("Login URL required", "Enter the full authorised login URL, including https://.")
            return
        username = self.username.get().strip()
        password = self.password.get()
        reconciliation_url = self.reconciliation_url.get().strip()
        refresh_seconds = str(parse_refresh_seconds(self.refresh_seconds.get().strip(), default=DEFAULT_REFRESH_SECONDS))
        if not username or not password:
            if self.on_open_settings and messagebox.askyesno(
                "Credentials required",
                "Tool 6 username/email and password are required. Would you like to open Settings now to configure them?",
            ):
                self.on_open_settings()
            else:
                messagebox.showwarning(
                    "Credentials required",
                    "Please configure the Tool 6 username/email and password in Settings before opening the browser.",
                )
            return
        # Best-effort persist credentials
        self.save_credentials(show_success=False)
        if self.browser_process is not None and self.browser_process.poll() is None:
            self.status.set("Both portal browsers are open side by side.")
            self.set_browser_visible(True)
            if self.loading_history_process is None or self.loading_history_process.poll() is not None:
                self.start_loading_history_browser({"stop_at_gatepass": True})
            else:
                self.set_loading_history_visible(True)
            return

        # Pre-flight check: ensure pywebview is available in the current runtime
        try:
            import webview  # noqa: F401
        except ImportError:
            messagebox.showerror(
                "pywebview Required",
                "Tool 6 requires 'pywebview' to run the embedded browser.\n\n"
                "Please run:\n"
                "  pip install pywebview\n"
                "or install packages from requirements.txt.",
            )
            self.status.set("pywebview is not installed in the current Python environment.")
            return

        try:
            # Result files persist across runs. Record the existing timestamp so
            # only a snapshot written by this newly started browser is displayed.
            try:
                self._live_result_baseline_mtime_ns = self.result_path.stat().st_mtime_ns
            except OSError:
                self._live_result_baseline_mtime_ns = 0
            self._clear_job_console()
            self.browser_log_path.parent.mkdir(parents=True, exist_ok=True)
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--internal-browser", str(self.result_path), login_url]
            else:
                command = [sys.executable, str(Path(__file__).resolve()), "--internal-browser", str(self.result_path), login_url]
            child_env = os.environ.copy()
            child_env["EFL_NEXUS_GRABBER_USER"] = username
            child_env["EFL_NEXUS_GRABBER_PASS"] = password
            child_env["EFL_NEXUS_GRABBER_RECON_URL"] = reconciliation_url
            child_env["EFL_NEXUS_GRABBER_REFRESH_SECONDS"] = refresh_seconds

            if self._browser_log_handle and not self._browser_log_handle.closed:
                try:
                    self._browser_log_handle.close()
                except Exception:
                    pass
            self._browser_log_handle = open(self.browser_log_path, "w", encoding="utf-8")
            self.browser_process = subprocess.Popen(
                command,
                env=child_env,
                stdout=self._browser_log_handle,
                stderr=subprocess.STDOUT,
            )
            child_env.pop("EFL_NEXUS_GRABBER_USER", None)
            child_env.pop("EFL_NEXUS_GRABBER_PASS", None)
            child_env.pop("EFL_NEXUS_GRABBER_RECON_URL", None)
            child_env.pop("EFL_NEXUS_GRABBER_REFRESH_SECONDS", None)
            self.status.set("Internal browser opened. Logging in and opening Reconciliation automatically…")
            self._browser_embed_attempts = 0
            self.root.after(100, self._find_and_embed_internal_browser)
            self.start_loading_history_browser({"stop_at_gatepass": True})
            self._poll_internal_browser_results()
        except Exception as exc:
            messagebox.showerror("Internal browser unavailable", f"Could not start the internal browser: {exc}")

    def save_credentials(self, show_success=True):
        """Save non-secret endpoints locally and the password in Windows Credential Manager."""
        login_url = self.login_url.get().strip()
        username = self.username.get().strip()
        password = self.password.get()
        if not login_url.startswith(("https://", "http://")) or not username or not password:
            if show_success:
                messagebox.showwarning("Incomplete credentials", "Enter a valid login URL, username/email, and password first.")
            return False
        try:
            _save_password(password, username)
        except Exception as exc:
            messagebox.showerror("Credential save failed", f"Windows Credential Manager could not save Tool 6 password: {exc}")
            return False

        # Persist non-secret settings with multiple fallbacks
        saved_config = False
        if self.config_store is None:
            try:
                from outlook_email_gui import ConfigStore, CONFIG_JSON_PATH
                self.config_store = ConfigStore(CONFIG_JSON_PATH)
            except Exception:
                pass

        if self.config_store is not None:
            try:
                saved_config = bool(self.config_store.save(
                    data_grabber_login_url=login_url,
                    data_grabber_user=username,
                    data_grabber_reconciliation_url=self.reconciliation_url.get().strip(),
                    data_grabber_refresh_seconds=self.refresh_seconds.get().strip(),
                ))
            except Exception:
                saved_config = False

        if not saved_config:
            try:
                from outlook_email_gui import CONFIG_JSON_PATH
                cfg_path = Path(CONFIG_JSON_PATH)
            except Exception:
                cfg_path = Path(__file__).resolve().parent / "config.json"
            try:
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                data = {}
                if cfg_path.exists():
                    try:
                        data = json.loads(cfg_path.read_text(encoding="utf-8"))
                    except Exception:
                        data = {}
                data["data_grabber_login_url"] = login_url
                data["data_grabber_user"] = username
                data["data_grabber_reconciliation_url"] = self.reconciliation_url.get().strip()
                data["data_grabber_refresh_seconds"] = self.refresh_seconds.get().strip()
                cfg_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                saved_config = True
            except Exception as exc:
                print(f"[WebsiteDataGrabber] Non-secret settings write warning: {exc}")

        if show_success:
            self.status.set("Credentials saved securely for this Windows user.")
        return True

    def clear_saved_credentials(self):
        if not messagebox.askyesno("Clear saved credentials", "Remove the saved Tool 6 username and password from this computer?"):
            return
        _clear_saved_password()
        self.username.set("")
        self.password.set("")
        if self.config_store:
            self.config_store.save(data_grabber_user="")
        self.status.set("Saved Tool 6 credentials removed.")

    def set_connection_settings(
        self,
        login_url: str,
        username: str,
        password: str,
        reconciliation_url: str,
        refresh_seconds: str = "5",
        sound_enabled: bool = True,
        sound_path: str = "",
    ):
        """Apply Settings-page changes to an already-open Tool 6 instance."""
        self.login_url.set(login_url)
        self.username.set(username)
        self.password.set(password)
        self.reconciliation_url.set(reconciliation_url)
        self.set_refresh_interval(refresh_seconds, save=False)
        self.set_sound_enabled(sound_enabled, save=False)
        if hasattr(self, "sound_path"):
            self.sound_path.set(sound_path)
        if username and password:
            self.status.set("Ready. Click 'Open Internal Browser' to launch the portal session.")
        else:
            self.status.set("Enter portal credentials in Settings to automatically sign in and open Reconciliation.")

    def _on_tree_copy(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        lines = []
        for item in selected:
            vals = self.tree.item(item, "values")
            if vals:
                lines.append("\t".join(str(v) for v in vals[:-1]))
        if lines:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines))
            self.status.set(f"Copied {len(lines)} selected row(s) to clipboard.")

    def _clear_job_console(self) -> None:
        """Remove stale rows before a new browser session supplies live data."""
        self.records = []
        self.job_ids = []
        if hasattr(self, "tree") and isinstance(self.tree, ttk.Treeview):
            for child in self.tree.get_children():
                self.tree.delete(child)

    def _poll_internal_browser_results(self):
        try:
            browser_is_live = self.browser_process is not None and self.browser_process.poll() is None
            result_is_current_session = (
                browser_is_live
                and self.result_path.exists()
                and self.result_path.stat().st_mtime_ns > self._live_result_baseline_mtime_ns
            )
            if result_is_current_session:
                payload = json.loads(self.result_path.read_text(encoding="utf-8"))
                ids = payload.get("job_ids", [])
                records = payload.get("records", [])
                if isinstance(records, list):
                    if records != self.records:
                        self._show_results(records)
                elif isinstance(ids, list) and ids != self.job_ids:
                    self._show_results([str(value) for value in ids])
        except Exception:
            pass
        try:
            dl_file = getattr(self, "download_event_path", None) or _download_event_file()
            if dl_file.exists():
                dl_data = json.loads(dl_file.read_text(encoding="utf-8"))
                dl_ts = float(dl_data.get("time", 0.0))
                if dl_ts > getattr(self, "_last_download_time", 0.0):
                    self._last_download_time = dl_ts
                    fn = dl_data.get("filename", "")
                    target_folder_name = str(dl_data.get("folder") or "").strip()
                    if not target_folder_name and dl_data.get("path"):
                        target_folder_name = Path(dl_data["path"]).parent.name
                    loc_text = f"folder '{target_folder_name}'" if target_folder_name and target_folder_name.lower() != "downloads" else "Downloads folder"
                    self.status.set(f"✓ Downloaded '{fn}' (saved to {loc_text})")
        except Exception:
            pass
        try:
            event_file = getattr(self, "loading_history_event_path", None) or _loading_history_event_file()
            if event_file.exists():
                event = json.loads(event_file.read_text(encoding="utf-8"))
                event_time = float(event.get("time", 0.0))
                if event.get("action") in ("open_loading_history", "download_loading_history") and event_time > self._last_loading_history_time:
                    self._last_loading_history_time = event_time
                    self.start_loading_history_browser(event)
        except Exception:
            pass
        poll_interval = 750 if (self.browser_process is not None and self.browser_process.poll() is None) else 1500
        self.root.after(poll_interval, self._poll_internal_browser_results)

    def _load_persisted_results_on_startup(self):
        """Load previously persisted jobs into the Job Console so it's not blank on startup."""
        loaded = False
        if self.result_path and self.result_path.exists():
            try:
                payload = json.loads(self.result_path.read_text(encoding="utf-8"))
                recs = payload.get("records") or payload.get("job_ids")
                if recs:
                    print(f"[WebsiteDataGrabber] Loaded {len(recs)} cached job(s) from {self.result_path.name} on startup.", flush=True)
                    self._show_results(recs, play_sound_alert=False)
                    loaded = True
            except Exception as exc:
                print(f"[WebsiteDataGrabber] Notice: Could not read startup result file: {exc}", flush=True)
        if not loaded:
            persisted = load_persisted_job_map()
            if persisted:
                recs = list(persisted.values())
                print(f"[WebsiteDataGrabber] Loaded {len(recs)} cached job(s) from persistent job map on startup.", flush=True)
                self._show_results(recs, play_sound_alert=False)
                loaded = True
        if not loaded:
            print("[WebsiteDataGrabber] Job Console ready (no previous jobs cached). Click 'Open Both Browsers'.", flush=True)

    def start_loading_history_browser(self, job_context: dict[str, Any] | None = None) -> None:
        """Open a lightweight external WebView2 window for Loading History or dispatch commands."""
        stop_at_gatepass = bool((job_context or {}).get("stop_at_gatepass"))
        gatepass = _clean(str((job_context or {}).get("gatepass") or ""))
        job_id = _clean(str((job_context or {}).get("job_id") or ""))
        client = _clean(str((job_context or {}).get("client") or ""))

        if stop_at_gatepass:
            gatepass = ""
            job_id = ""
            client = ""

        if not stop_at_gatepass and (not gatepass or not client) and job_id:
            for rec in getattr(self, "records", []):
                if _clean(str(rec.get("job_id", ""))) == job_id:
                    if not gatepass and rec.get("gatepass"):
                        gatepass = _clean(str(rec["gatepass"]))
                    if not client and rec.get("client"):
                        client = _clean(str(rec["client"]))
                    break
        if not stop_at_gatepass and (not gatepass or not client or not job_id):
            try:
                persisted = load_persisted_job_map()
                if job_id and job_id.casefold() in persisted:
                    mapped = persisted[job_id.casefold()]
                    if not gatepass and mapped.get("gatepass"):
                        gatepass = _clean(str(mapped["gatepass"]))
                    if not client and mapped.get("client"):
                        client = _clean(str(mapped["client"]))
                elif gatepass:
                    for mapped in persisted.values():
                        if _clean(str(mapped.get("gatepass", ""))) == gatepass:
                            if not job_id and mapped.get("job_id"):
                                job_id = _clean(str(mapped["job_id"]))
                            if not client and mapped.get("client"):
                                client = _clean(str(mapped["client"]))
                            break
            except Exception:
                pass

        if not stop_at_gatepass and not gatepass and getattr(self, "active_gatepass", None):
            gatepass = _clean(str(self.active_gatepass))
        if not stop_at_gatepass and not job_id and getattr(self, "active_job_id", None):
            job_id = _clean(str(self.active_job_id))
        if not stop_at_gatepass and not client and getattr(self, "active_client", None):
            client = _clean(str(self.active_client))

        if self.loading_history_process is not None and self.loading_history_process.poll() is None:
            self.set_loading_history_visible(True)
            if gatepass:
                self._send_loading_history_command(
                    "query_and_export",
                    gatepass=gatepass,
                    job_id=job_id,
                    client=client,
                )
                self.status.set(f"Entering Gate Pass '{gatepass}' in Loading History, querying and exporting…")
            elif stop_at_gatepass:
                self.status.set("Körber Loading History is open side by side.")
            else:
                self.status.set("Körber Loading History is already open.")
            return

        try:
            import korber_login_bot as korber_login
            url, username, password = korber_login.get_credentials()
            if not username or not password:
                raise ValueError("Körber credentials are not configured. Add them in Settings before downloading Loading History.")

            try:
                import webview  # noqa: F401
            except ImportError as exc:
                raise RuntimeError("pywebview is required to open the lightweight Loading History browser.") from exc

            if getattr(sys, "frozen", False):
                command = [sys.executable, "--loading-history-browser", url]
            else:
                command = [sys.executable, str(Path(__file__).resolve()), "--loading-history-browser", url]
            if gatepass:
                command.append(gatepass)
            if job_id:
                command.append(job_id)
            if client:
                command.append(client)
            child_env = os.environ.copy()
            child_env["EFL_NEXUS_KORBER_USER"] = username
            child_env["EFL_NEXUS_KORBER_PASS"] = password
            if stop_at_gatepass:
                child_env["EFL_NEXUS_LOADING_HISTORY_STOP_AT_GATEPASS"] = "1"
            if gatepass:
                child_env["EFL_NEXUS_KORBER_GATEPASS"] = gatepass
            if job_id:
                child_env["EFL_NEXUS_KORBER_JOB_ID"] = job_id
            if client:
                child_env["EFL_NEXUS_KORBER_CLIENT"] = client
            self.loading_history_process = subprocess.Popen(command, env=child_env.copy())
            child_env.pop("EFL_NEXUS_KORBER_USER", None)
            child_env.pop("EFL_NEXUS_KORBER_PASS", None)
            child_env.pop("EFL_NEXUS_KORBER_GATEPASS", None)
            child_env.pop("EFL_NEXUS_KORBER_JOB_ID", None)
            child_env.pop("EFL_NEXUS_KORBER_CLIENT", None)
            child_env.pop("EFL_NEXUS_LOADING_HISTORY_STOP_AT_GATEPASS", None)
            self._loading_history_embed_attempts = 0
            self.root.after(100, self._find_and_embed_loading_history_browser)
            if stop_at_gatepass:
                self.status.set("Opening Reconciliation and Loading History side by side…")
            else:
                context_note = f" for gate pass {gatepass}" if gatepass else ""
                self.status.set(f"Opening lightweight Körber Loading History browser{context_note}…")
        except Exception as exc:
            messagebox.showerror("Loading History", f"Could not open Körber Loading History: {exc}")
            self.status.set("Could not open Körber Loading History.")

    def _read_browser_log(self) -> str:
        """Read any error messages captured in the browser process log."""
        try:
            if self._browser_log_handle and not self._browser_log_handle.closed:
                self._browser_log_handle.flush()
            if self.browser_log_path.exists():
                content = self.browser_log_path.read_text(encoding="utf-8", errors="replace").strip()
                if content:
                    lines = content.splitlines()
                    return "\n".join(lines[-10:])
        except Exception:
            pass
        return ""

    @staticmethod
    def _find_window_for_process(process_id: int):
        """Return the visible top-level WebView host window for the helper process."""
        if not isinstance(process_id, int) or process_id <= 0:
            return None
        current_pid = os.getpid()
        if process_id == current_pid:
            return None
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        candidates = []
        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @enum_proc_type
        def collect(hwnd, _lparam):
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if int(window_pid.value) == int(process_id) and user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, length + 1)
                t_val = title.value
                if "Reconciliation Browser" in t_val or "Loading History" in t_val or "EFL NEXUS" in t_val:
                    candidates.append(hwnd)
            return True

        user32.EnumWindows(enum_proc_type(collect), 0)
        return candidates[0] if candidates else None

    def _find_and_embed_internal_browser(self):
        process = self.browser_process
        if process is None:
            return
        if not isinstance(getattr(process, "pid", None), int):
            return

        # Check if the helper process terminated prematurely
        if process.poll() is not None:
            exit_code = process.poll()
            self.browser_process = None
            err_detail = self._read_browser_log()
            msg = f"The internal browser helper process terminated unexpectedly (exit code {exit_code})."
            if err_detail:
                msg += f"\n\nDiagnostic Output:\n{err_detail}"
            self.status.set(f"Internal browser closed unexpectedly (exit code {exit_code}).")
            messagebox.showerror("Internal Browser Error", msg)
            return

        if self.browser_hwnd:
            return

        hwnd = self._find_window_for_process(process.pid)
        if hwnd:
            try:
                self._embed_internal_browser(hwnd)
                return
            except Exception as exc:
                self.status.set(f"Could not embed the internal browser: {exc}")
                return
        self._browser_embed_attempts += 1
        if self._browser_embed_attempts < 150:
            self.root.after(100, self._find_and_embed_internal_browser)
        else:
            self.status.set("The internal browser did not become available for embedding. It may be running as a floating window.")

    def _find_and_embed_loading_history_browser(self):
        process = self.loading_history_process
        if process is None:
            return
        if not isinstance(getattr(process, "pid", None), int):
            return
        if process.poll() is not None:
            self.loading_history_process = None
            self.loading_history_hwnd = None
            self.status.set("The Loading History browser closed unexpectedly.")
            return
        if self.loading_history_hwnd:
            return

        hwnd = self._find_window_for_process(process.pid)
        if hwnd:
            try:
                self._embed_loading_history_browser(hwnd)
                self.status.set("Reconciliation and Loading History are open side by side.")
                return
            except Exception as exc:
                self.status.set(f"Could not embed Loading History: {exc}")
                return
        self._loading_history_embed_attempts += 1
        if self._loading_history_embed_attempts < 150:
            self.root.after(100, self._find_and_embed_loading_history_browser)
        else:
            self.status.set("Loading History did not become available for embedding.")

    def _embed_internal_browser(self, hwnd):
        """Reparent the helper's WebView2 window into Tool 6's browser frame."""
        if sys.platform != "win32":
            raise RuntimeError("Internal browser embedding is supported on Windows only.")
        self.browser_host.update_idletasks()
        host_hwnd = int(self.browser_host.winfo_id())

        self._reparent_browser_window(hwnd, host_hwnd)
        self.browser_hwnd = hwnd
        self._resize_internal_browser()

    def _embed_loading_history_browser(self, hwnd):
        """Reparent Loading History into its side-by-side host frame."""
        if sys.platform != "win32":
            raise RuntimeError("Loading History embedding is supported on Windows only.")
        self.loading_history_host.update_idletasks()
        host_hwnd = int(self.loading_history_host.winfo_id())

        self._reparent_browser_window(hwnd, host_hwnd)
        self.loading_history_hwnd = hwnd
        self._resize_loading_history_browser()

    @staticmethod
    def _reparent_browser_window(hwnd, host_hwnd):
        """Attach a top-level helper window to a Tk host HWND."""

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.SetParent.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long

        GWL_STYLE, GWL_EXSTYLE = -16, -20
        WS_CHILD, WS_VISIBLE = 0x40000000, 0x10000000
        WS_CLIPCHILDREN = 0x02000000
        chrome = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000 | 0x80000000 | 0x01000000
        user32.ShowWindow(hwnd, 0)
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, (style & ~chrome) | WS_CHILD | WS_VISIBLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, 0)

        host_style = user32.GetWindowLongW(host_hwnd, GWL_STYLE)
        user32.SetWindowLongW(host_hwnd, GWL_STYLE, host_style | WS_CLIPCHILDREN)

        ctypes.set_last_error(0)
        user32.SetParent(hwnd, host_hwnd)
        actual_parent = int(user32.GetParent(hwnd) or 0)
        if actual_parent != host_hwnd:
            err = ctypes.get_last_error()
            raise OSError(err, f"Windows could not attach the browser window (window={hwnd}, host={host_hwnd}, actual={actual_parent})")

        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = wintypes.BOOL
        # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020 | 0x0040)

        user32.ShowWindow(hwnd, 5)

    def _resize_internal_browser(self, _event=None):
        if not self.browser_hwnd or not getattr(self, "browser_host", None):
            return
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
            user32.MoveWindow.restype = wintypes.BOOL
            user32.MoveWindow(
                self.browser_hwnd, 0, 0,
                max(1, self.browser_host.winfo_width()),
                max(1, self.browser_host.winfo_height()), True,
            )
        except Exception:
            pass

    def _resize_loading_history_browser(self, _event=None):
        if not self.loading_history_hwnd or not getattr(self, "loading_history_host", None):
            return
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
            user32.MoveWindow.restype = wintypes.BOOL
            user32.MoveWindow(
                self.loading_history_hwnd, 0, 0,
                max(1, self.loading_history_host.winfo_width()),
                max(1, self.loading_history_host.winfo_height()), True,
            )
        except Exception:
            pass

    def set_browser_visible(self, visible: bool):
        """Show or hide both embedded browsers with the Pending Jobs page."""
        self._set_embedded_window_visible(self.browser_hwnd, visible)
        self._set_embedded_window_visible(self.loading_history_hwnd, visible)
        if visible:
            if getattr(self, "root", None) and hasattr(self.root, "after_idle"):
                self.root.after_idle(self._resize_internal_browser)
                self.root.after_idle(self._resize_loading_history_browser)
            else:
                self._resize_internal_browser()
                self._resize_loading_history_browser()

    def set_loading_history_visible(self, visible: bool):
        self._set_embedded_window_visible(self.loading_history_hwnd, visible)

    @staticmethod
    def _set_embedded_window_visible(hwnd, visible: bool):
        if not hwnd:
            return
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.ShowWindow(hwnd, 5 if visible else 0)
        except Exception:
            pass

    def close_browser(self):
        """Terminate the internal browser subprocess and release its resources."""
        if self.browser_process is not None and self.browser_process.poll() is None:
            try:
                self.browser_process.terminate()
                self.browser_process.wait(timeout=2)
            except Exception:
                try:
                    self.browser_process.kill()
                except Exception:
                    pass
        self.browser_process = None
        self.browser_hwnd = None
        if self.loading_history_process is not None and self.loading_history_process.poll() is None:
            try:
                self.loading_history_process.terminate()
                self.loading_history_process.wait(timeout=2)
            except Exception:
                try:
                    self.loading_history_process.kill()
                except Exception:
                    pass
        self.loading_history_process = None
        self.loading_history_hwnd = None
        self._loading_history_embed_attempts = 0
        if self._browser_log_handle and not self._browser_log_handle.closed:
            try:
                self._browser_log_handle.close()
            except Exception:
                pass

    def restart_browser(self):
        """Restart the internal browser session, re-login, and navigate to Reconciliation."""
        self.status.set("Restarting internal browser...")
        self.close_browser()
        self._browser_embed_attempts = 0
        self.root.after(150, self.start)

    def _ui(self, callback):
        self.root.after(0, callback)

    def _run(self):
        try:
            from selenium import webdriver
            from selenium.common.exceptions import TimeoutException
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait

            options = webdriver.ChromeOptions()
            options.add_argument("--start-maximized")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            dl_dir = str(get_downloads_folder().resolve())
            options.add_experimental_option("prefs", {
                "download.default_directory": dl_dir,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
            })
            self.driver = webdriver.Chrome(options=options)
            wait = WebDriverWait(self.driver, 20)
            self.driver.get(self.login_url.get().strip())
            self._ui(lambda: self.status.set("Signing in… complete any SSO/MFA in the browser if it appears."))
            self._fill_login(By, wait)

            target = self.reconciliation_url.get().strip()
            if target.startswith(("https://", "http://")):
                self.driver.get(target)
            else:
                self._open_reconciliation(By, wait)
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            ids = self._collect_pages(By, wait)
            if not ids:
                raise RuntimeError(
                    f"No '{self.job_header.get().strip() or 'Job ID'}' column was found. "
                    "Provide the exact column heading or send a screenshot of the reconciliation table."
                )
            self._ui(lambda: self._show_results(ids))
        except Exception as exc:
            self._ui(lambda: messagebox.showerror("Job ID grab failed", str(exc)))
            self._ui(lambda: self.status.set("Failed — the browser remains open for inspection."))
        finally:
            self._ui(self._finish)

    def _fill_login(self, By, wait):
        fields = wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "input"))
        password = next((f for f in fields if (f.get_attribute("type") or "").lower() == "password"), None)
        user = next((f for f in fields if f is not password and any(word in " ".join(filter(None, [f.get_attribute("name"), f.get_attribute("id"), f.get_attribute("autocomplete"), f.get_attribute("type")])).casefold() for word in ("user", "email", "login"))), None)
        user = user or next((f for f in fields if f is not password and f.is_displayed()), None)
        if not user or not password:
            raise RuntimeError("Could not identify the username and password fields on this login page.")
        user.clear(); user.send_keys(self.username.get().strip())
        password.clear(); password.send_keys(self.password.get())
        submit = next((e for e in self.driver.find_elements(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']") if e.is_displayed()), None)
        if submit:
            submit.click()
        else:
            password.submit()

    def _open_reconciliation(self, By, wait):
        link_text = self.reconciliation_link_text.get().strip() or "Reconciliation"
        link = wait.until(lambda d: next((e for e in d.find_elements(By.XPATH, f"//*[self::a or self::button][contains(normalize-space(.), {self._xpath_literal(link_text)})]") if e.is_displayed()), None))
        if not link:
            raise RuntimeError(f"Could not find a visible navigation link containing '{link_text}'. Enter the direct reconciliation URL instead.")
        self.driver.execute_script("arguments[0].click();", link)

    @staticmethod
    def _xpath_literal(value):
        if "'" not in value:
            return f"'{value}'"
        return 'concat(' + ', "\'", '.join(f"'{part}'" for part in value.split("'")) + ')'

    def _collect_pages(self, By, wait):
        all_records: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        for _ in range(100):
            records = self._extract_current_page(By)
            page_ids = tuple(r["job_id"] for r in records)
            if page_ids in seen_pages:
                break
            seen_pages.add(page_ids)
            for r in records:
                key = r["job_id"].casefold()
                if key not in seen_ids:
                    seen_ids.add(key)
                    all_records.append(r)
            next_button = self._next_button(By)
            if not next_button:
                break
            old_html = self.driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
            self.driver.execute_script("arguments[0].click();", next_button)
            try:
                wait.until(lambda d: d.find_element(By.TAG_NAME, "body").get_attribute("innerHTML") != old_html)
            except Exception:
                break
        return all_records

    def _extract_current_page(self, By):
        best: list[dict[str, str]] = []
        tables = self.driver.find_elements(By.CSS_SELECTOR, "table.table-bordered.table-hover")
        if not tables:
            tables = self.driver.find_elements(By.CSS_SELECTOR, "table")
        for table in tables:
            headers = [cell.text for cell in table.find_elements(By.CSS_SELECTOR, "thead th")]
            if not headers:
                first_row = table.find_elements(By.CSS_SELECTOR, "tr")
                headers = [cell.text for cell in first_row[0].find_elements(By.CSS_SELECTOR, "th,td")] if first_row else []
            rows = [[cell.text for cell in row.find_elements(By.CSS_SELECTOR, "td")] for row in table.find_elements(By.CSS_SELECTOR, "tbody tr")]
            records = extract_jobs_with_status(headers, rows, self.job_header.get(), include_client=True, include_details=True)
            if len(records) > len(best):
                best = records
        return best

    def _next_button(self, By):
        candidates = self.driver.find_elements(By.CSS_SELECTOR, "button[aria-label*='Next'], a[aria-label*='Next'], .pagination .next, [rel='next']")
        for element in candidates:
            disabled = (element.get_attribute("disabled") is not None or "disabled" in (element.get_attribute("class") or "").casefold() or element.get_attribute("aria-disabled") == "true")
            if element.is_displayed() and element.is_enabled() and not disabled:
                return element
        return None

    def _show_results(self, items, play_sound_alert: bool = True):
        records: list[dict[str, str]] = []
        ids: list[str] = []
        for item in items:
            if isinstance(item, dict):
                jid = _clean(str(item.get("job_id", "")))
                st = normalize_reconciliation_status(str(item.get("status", "")))
                rec = {"job_id": jid, "status": st}
                for opt_k in ("client", "warehouse", "gatepass", "seal", "delivery_location"):
                    if opt_k in item:
                        rec[opt_k] = _clean(str(item.get(opt_k, "")))
                records.append(rec)
                ids.append(jid)
            else:
                jid = _clean(str(item))
                if jid:
                    records.append({"job_id": jid, "status": "Unknown"})
                    ids.append(jid)
        self.records = records
        self.job_ids = ids

        if hasattr(self, "tree") and isinstance(self.tree, ttk.Treeview):
            selected_ids = []
            for sel in self.tree.selection():
                v = self.tree.item(sel, "values")
                if v:
                    selected_ids.append(str(v[0]))
            for child in self.tree.get_children():
                self.tree.delete(child)
            for r in records:
                status = r["status"]
                tag = "pending" if status == "Pending" else ("in_progress" if status == "In Progress" else ("completed" if status == "Completed" else "other"))
                item_id = self.tree.insert(
                    "", "end",
                    values=(r["job_id"], r.get("client", ""), status, "▶ Start"),
                    tags=(tag,),
                )
                if r["job_id"] in selected_ids:
                    self.tree.selection_add(item_id)
        elif hasattr(self, "output") and hasattr(self.output, "delete"):
            self.output.delete("1.0", tk.END)
            self.output.insert("1.0", "\n".join(ids))

        pending_count = sum(1 for r in records if r["status"] == "Pending")
        in_progress_count = sum(1 for r in records if r["status"] == "In Progress")
        other_count = len(records) - pending_count - in_progress_count

        status_parts = []
        if pending_count:
            status_parts.append(f"{pending_count} Pending")
        if in_progress_count:
            status_parts.append(f"{in_progress_count} In Progress")
        if other_count:
            status_parts.append(f"{other_count} Other")
        breakdown = f" ({', '.join(status_parts)})" if status_parts else ""
        self.status.set(f"Collected {len(records)} Job ID(s){breakdown}. Browser remains open; close it when finished.")
        print(f"\n[WebsiteDataGrabber] Job Console updated with {len(records)} job(s){breakdown}:", flush=True)
        for r in records[:10]:
            print(f"  -> Job: {r.get('job_id')} | Client: {r.get('client', '')} | Gatepass: {r.get('gatepass', '')} | Status: {r.get('status', '')}", flush=True)
        if len(records) > 10:
            print(f"  -> ... and {len(records) - 10} more jobs.", flush=True)

        # Check for newly detected pending jobs to play the notification sound
        current_pending = {
            r["job_id"].strip().casefold()
            for r in records
            if r.get("status") == "Pending" and r.get("job_id")
        }
        new_pending = current_pending - getattr(self, "_seen_pending_ids", set())
        if play_sound_alert and new_pending and getattr(self, "sound_enabled", None) and self.sound_enabled.get():
            self.play_alert()
        self._seen_pending_ids = current_pending

    def start_selected_job(self):
        """Send a command to the browser to click the web portal's Start button for the selected job."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Select Job", "Please select a job from the list first.")
            return
        vals = self.tree.item(selected[0], "values")
        if not vals:
            return
        job_id = str(vals[0]).strip()
        if not job_id:
            return

        active_gp = ""
        active_client = ""
        for rec in getattr(self, "records", []):
            if str(rec.get("job_id", "")).strip() == job_id:
                active_gp = str(rec.get("gatepass") or "").strip()
                active_client = str(rec.get("client") or "").strip()
                break
        if not active_gp:
            try:
                persisted = load_persisted_job_map()
                if job_id in persisted:
                    active_gp = str(persisted[job_id].get("gatepass") or "").strip()
                    if not active_client:
                        active_client = str(persisted[job_id].get("client") or "").strip()
            except Exception:
                pass
        self.active_job_id = job_id
        self.active_gatepass = active_gp

        # Check if browser helper process is active
        if self.browser_process is None or self.browser_process.poll() is not None:
            if not getattr(self, "driver", None):
                if messagebox.askyesno(
                    "Browser Not Open",
                    f"The internal browser is not currently running.\n\n"
                    f"Would you like to open it now to start job '{job_id}'?",
                ):
                    self.start()
                    self._send_browser_command("start_job", job_id=job_id, gatepass=active_gp, client=active_client)
                    self._notify_job_started(job_id)
                return

        # If Selenium driver is running
        if getattr(self, "driver", None):
            try:
                escaped = json.dumps(job_id)
                script = f"""
                const targetClean = {escaped}.trim().toLowerCase().replace(/[^a-z0-9]/g, '');
                const tables = [...document.querySelectorAll('table')];
                for (const table of tables) {{
                    const rows = [...table.querySelectorAll('tbody tr, tr')];
                    for (const row of rows) {{
                        const cells = [...row.querySelectorAll('td, th')];
                        if (cells.some(c => c.textContent.trim().toLowerCase().replace(/[^a-z0-9]/g, '') === targetClean)) {{
                            const btn = row.querySelector("button.btn-start, form[action*='/warf/start'] button, button");
                            if (btn) {{ btn.click(); return true; }}
                        }}
                    }}
                }}
                return false;
                """
                success = self.driver.execute_script(script)
                if success:
                    self.status.set(f"Triggered Start for Job ID '{job_id}' in portal browser.")
                    self._notify_job_started(job_id)
                else:
                    self.status.set(f"Job ID '{job_id}' not found on active portal page.")
                return
            except Exception as exc:
                messagebox.showerror("Selenium Error", f"Failed to trigger start: {exc}")
                return

        sent = self._send_browser_command("start_job", job_id=job_id, gatepass=active_gp, client=active_client)
        if sent:
            self.status.set(f"Sent Start request for Job ID '{job_id}' to the portal browser...")
            self._notify_job_started(job_id)

    def create_gatepass_selected_job(self):
        """Extract WH, Client, Gate Pass, Seal, Delivery Location from selected job and send to Korber."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Select Job", "Please select a job from the list first.")
            return
        vals = self.tree.item(selected[0], "values")
        if not vals:
            return
        job_id = str(vals[0]).strip()
        if not job_id:
            return

        # Find the full parsed record for this job_id
        matched_record = next(
            (r for r in self.records if str(r.get("job_id", "")).strip().casefold() == job_id.casefold()),
            None,
        )
        if matched_record is None:
            matched_record = {
                "job_id": job_id,
                "client": str(vals[1]).strip() if len(vals) > 1 else "",
                "status": str(vals[2]).strip() if len(vals) > 2 else "",
                "warehouse": "",
                "gatepass": "",
                "seal": "",
                "delivery_location": "",
            }

        record_to_send = dict(matched_record) if matched_record else {"job_id": job_id}
        if job_id.upper().startswith("OUT_"):
            deliv = str(record_to_send.get("delivery_location") or "").strip()
            if not deliv or deliv == "-":
                record_to_send["delivery_location"] = "N/A"
            seal = str(record_to_send.get("seal") or "").strip()
            if not seal or seal == "-":
                record_to_send["seal"] = "N/A"

        if callable(self.on_create_gatepass):
            self.on_create_gatepass(record_to_send)
        else:
            messagebox.showinfo("Create Gatepass", f"Job: {job_id}\nData: {record_to_send}")

    def download_selected_job_files(self):
        """Request the browser to download all files for the selected job."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Select Job", "Please select a job from the list first.")
            return
        vals = self.tree.item(selected[0], "values")
        if not vals:
            return
        job_id = str(vals[0]).strip()
        if not job_id:
            return

        # Find the full parsed record for this job_id
        matched_record = next(
            (r for r in self.records if str(r.get("job_id", "")).strip().casefold() == job_id.casefold()),
            None,
        )
        gatepass = matched_record.get("gatepass", "") if matched_record else ""
        client = matched_record.get("client", "") if matched_record else ""
        if not client and len(vals) > 1:
            client = str(vals[1]).strip()

        if self.browser_process is None or self.browser_process.poll() is not None:
            if not getattr(self, "driver", None):
                if messagebox.askyesno(
                    "Browser Not Open",
                    f"The internal browser is not currently running.\n\n"
                    f"Would you like to open it now to view and download files for job '{job_id}'?",
                ):
                    self.start()
                    self._send_browser_command("start_job", job_id=job_id)
                    self.root.after(2000, lambda: self._send_browser_command(
                        "download_job_files",
                        job_id=job_id,
                        gatepass=gatepass,
                        client=client,
                    ))
                return

        sent = self._send_browser_command(
            "download_job_files",
            job_id=job_id,
            gatepass=gatepass,
            client=client,
        )
        if sent:
            target_sub = get_job_download_folder(job_id, gatepass, client).name
            self.status.set(f"Requested file download for Job ID '{job_id}' (saving to folder '{target_sub}')...")

    def download_selected_job_loading_history(self):
        """Request the Loading History browser to enter gatepass, query, and export for the selected job."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Select Job", "Please select a job from the list first.")
            return
        vals = self.tree.item(selected[0], "values")
        if not vals:
            return
        job_id = str(vals[0]).strip()
        if not job_id:
            return

        matched_record = next(
            (r for r in self.records if str(r.get("job_id", "")).strip().casefold() == job_id.casefold()),
            None,
        )
        gatepass = matched_record.get("gatepass", "") if matched_record else ""
        client = matched_record.get("client", "") if matched_record else ""
        if not client and len(vals) > 1:
            client = str(vals[1]).strip()

        if not gatepass:
            persisted = load_persisted_job_map()
            mapped = persisted.get(job_id.casefold())
            if mapped and mapped.get("gatepass"):
                gatepass = str(mapped["gatepass"]).strip()
                if not client and mapped.get("client"):
                    client = str(mapped["client"]).strip()

        if not gatepass:
            messagebox.showwarning(
                "Gate Pass Not Found",
                f"No Gate Pass is associated with Job ID '{job_id}'.\nPlease enter the Gate Pass manually in the Loading History browser.",
            )
            return

        self.start_loading_history_browser({
            "job_id": job_id,
            "gatepass": gatepass,
            "client": client,
            "stop_at_gatepass": False,
        })

    def open_selected_job_folder(self):
        """Open the target download folder for the currently selected job in Windows Explorer."""
        selected = self.tree.selection()
        job_id = ""
        gatepass = ""
        client = ""
        if selected:
            vals = self.tree.item(selected[0], "values")
            if vals:
                job_id = str(vals[0]).strip()
                matched_record = next(
                    (r for r in self.records if str(r.get("job_id", "")).strip().casefold() == job_id.casefold()),
                    None,
                )
                if matched_record:
                    gatepass = matched_record.get("gatepass", "")
                    client = matched_record.get("client", "")
                if not client and len(vals) > 1:
                    client = str(vals[1]).strip()

        target_dir = get_job_download_folder(job_id, gatepass, client)
        try:
            if sys.platform == "win32":
                os.startfile(str(target_dir.resolve()))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(target_dir.resolve())])
            self.status.set(f"Opened folder: {target_dir.name}")
        except Exception as exc:
            messagebox.showerror("Open Folder Error", f"Could not open directory {target_dir}: {exc}")

    def _notify_job_started(self, job_id: str) -> None:
        """Fire the on_job_started callback if configured."""
        if callable(self.on_job_started):
            try:
                self.on_job_started(job_id)
            except Exception:
                pass

    def _send_browser_command(self, action: str, **kwargs) -> bool:
        cmd_file = _command_file()
        try:
            cmd_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {"action": action, "timestamp": time.time(), **kwargs}
            cmd_file.write_text(json.dumps(payload), encoding="utf-8")
            return True
        except Exception as exc:
            messagebox.showerror("Command Error", f"Could not send command to browser: {exc}")
            return False

    def _send_loading_history_command(self, action: str, **kwargs) -> bool:
        cmd_file = _loading_history_command_file()
        try:
            cmd_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {"action": action, "timestamp": time.time(), **kwargs}
            cmd_file.write_text(json.dumps(payload), encoding="utf-8")
            return True
        except Exception as exc:
            messagebox.showerror("Command Error", f"Could not send command to Loading History browser: {exc}")
            return False

    def _is_action_column(self, event_x: int) -> bool:
        col = self.tree.identify_column(event_x)
        if not col or not col.startswith("#"):
            return False
        try:
            num = col.lstrip("#")
            if not num.isdigit():
                return False
            col_idx = int(num) - 1
            cols = self.tree["columns"]
            return 0 <= col_idx < len(cols) and cols[col_idx] == "action"
        except Exception:
            return col == "#3"

    def _on_tree_button_1(self, event):
        region = self.tree.identify_region(event.x, event.y)
        row = self.tree.identify_row(event.y)
        if region == "cell" and self._is_action_column(event.x) and row:
            self._pressed_action_row = row
            self.tree.selection_set(row)
            self.tree.focus(row)
        else:
            self._pressed_action_row = None

    def _on_tree_release_1(self, event):
        region = self.tree.identify_region(event.x, event.y)
        row = self.tree.identify_row(event.y)
        pressed = getattr(self, "_pressed_action_row", None)
        self._pressed_action_row = None
        if region == "cell" and self._is_action_column(event.x) and row and row == pressed:
            self.tree.selection_set(row)
            self.tree.focus(row)
            self.start_selected_job()

    def _on_tree_motion(self, event):
        region = self.tree.identify_region(event.x, event.y)
        row = self.tree.identify_row(event.y)
        if region == "cell" and self._is_action_column(event.x) and row:
            self.tree.configure(cursor="hand2")
        else:
            self.tree.configure(cursor="")

    def _on_tree_leave(self, event=None):
        self.tree.configure(cursor="")

    def _on_tree_double_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region in ("cell", "tree"):
            self.start_selected_job()

    def browser_go_back(self):
        """Navigate back to the previous page in the browser session."""
        if getattr(self, "driver", None):
            try:
                self.driver.back()
                self.status.set("Navigated back in browser.")
                return
            except Exception as exc:
                messagebox.showerror("Navigation Error", f"Could not navigate back: {exc}")
                return

        if self.browser_process is not None and self.browser_process.poll() is None:
            self._send_browser_command("go_back")
            self.status.set("Navigating back to the previous page...")
        else:
            messagebox.showinfo("Browser Not Open", "Open the internal browser first.")

    def browser_reload(self):
        """Reload the active page in the browser session."""
        if getattr(self, "driver", None):
            try:
                self.driver.refresh()
                self.status.set("Reloaded browser page.")
                return
            except Exception as exc:
                messagebox.showerror("Navigation Error", f"Could not reload page: {exc}")
                return

        if self.browser_process is not None and self.browser_process.poll() is None:
            self._send_browser_command("reload")
            self.status.set("Reloading portal browser...")
        else:
            messagebox.showinfo("Browser Not Open", "Open the internal browser first.")

    def browser_go_home(self):
        """Navigate directly to the reconciliation portal dashboard."""
        target = self.reconciliation_url.get().strip() or DEFAULT_RECONCILIATION_URL
        if getattr(self, "driver", None):
            try:
                self.driver.get(target)
                self.status.set("Navigated to Reconciliation dashboard.")
                return
            except Exception as exc:
                messagebox.showerror("Navigation Error", f"Could not navigate to Reconciliation: {exc}")
                return

        if self.browser_process is not None and self.browser_process.poll() is None:
            self._send_browser_command("go_home", url=target)
            self.status.set("Navigating to Reconciliation dashboard...")
        else:
            messagebox.showinfo("Browser Not Open", "Open the internal browser first.")

    def _finish(self):
        self.running = False
        self.run_button.configure(state="normal")

    def copy_results(self):
        if not self.records and not self.job_ids:
            messagebox.showinfo("No results", "Run the grabber first.")
            return
        if self.records:
            lines = [
                f"{r['job_id']}\t{r.get('client', '')}\t{r['status']}".strip()
                if r.get("client")
                else f"{r['job_id']}\t{r['status']}"
                for r in self.records
            ]
        else:
            lines = list(self.job_ids)
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.status.set(f"Copied {len(lines)} Job ID(s) & status to the clipboard.")

    def export_csv(self):
        if not self.records and not self.job_ids:
            messagebox.showinfo("No results", "Run the grabber first.")
            return
        filename = filedialog.asksaveasfilename(
            title="Export Job IDs & Status",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="reconciliation_job_ids.csv",
        )
        if not filename:
            return
        with Path(filename).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            has_client = any(bool(r.get("client")) for r in self.records)
            if has_client:
                writer.writerow([self.job_header.get().strip() or "Job ID", "Client", "Reconciliation Status"])
                writer.writerows([[r["job_id"], r.get("client", ""), r["status"]] for r in self.records])
            else:
                writer.writerow([self.job_header.get().strip() or "Job ID", "Reconciliation Status"])
                if self.records:
                    writer.writerows([[r["job_id"], r["status"]] for r in self.records])
                else:
                    writer.writerows([[value, "Unknown"] for value in self.job_ids])
        self.status.set(f"Exported {len(self.records or self.job_ids)} Job ID(s) to {filename}.")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--internal-browser":
        run_internal_browser(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else DEFAULT_LOGIN_URL)
    elif len(sys.argv) >= 3 and sys.argv[1] == "--loading-history-browser":
        gatepass_arg = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("EFL_NEXUS_KORBER_GATEPASS", "")
        job_id_arg = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("EFL_NEXUS_KORBER_JOB_ID", "")
        client_arg = sys.argv[5] if len(sys.argv) > 5 else os.environ.get("EFL_NEXUS_KORBER_CLIENT", "")
        run_loading_history_browser(sys.argv[2], gatepass=gatepass_arg, job_id=job_id_arg, client=client_arg)
    else:
        root = tk.Tk()
        root.title("EFL NEXUS — Tool 6: Pending Jobs")
        root.geometry("1560x940")
        root.minsize(1050, 700)
        try:
            root.state("zoomed")
        except Exception:
            pass
        app = WebsiteDataGrabberApp(root, standalone=True)
        root.protocol("WM_DELETE_WINDOW", lambda: (app.close_browser(), root.destroy()))
        root.mainloop()
