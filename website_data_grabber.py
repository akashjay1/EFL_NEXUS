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
            else:
                raw_id = _clean(str(item))
                raw_client = ""
                raw_status = ""
                raw_wh = ""
                raw_gp = ""
                raw_seal = ""
                raw_deliv = ""
            if not raw_id:
                continue
            key = raw_id.casefold()
            if key in seen:
                continue
            seen.add(key)
            norm_status = normalize_reconciliation_status(raw_status)
            records.append({
                "job_id": raw_id,
                "client": raw_client,
                "status": norm_status,
                "warehouse": raw_wh,
                "gatepass": raw_gp,
                "seal": raw_seal,
                "delivery_location": raw_deliv,
            })
            unique_ids.append(raw_id)
        if self.result_path:
            _write_results(self.result_path, unique_ids, records)
        return {"count": len(unique_ids)}

    def save_downloaded_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        import base64
        from urllib.parse import unquote, urlparse
        try:
            raw_filename = str(payload.get("filename") or "").strip()
            b64_data = payload.get("data") or ""
            url = str(payload.get("url") or "")
            job_id = str(payload.get("job_id") or "")

            if not raw_filename or raw_filename.lower() in ("download", "file", ""):
                if url:
                    parsed = unquote(urlparse(url).path.split("/")[-1])
                    if parsed:
                        raw_filename = parsed
            if not raw_filename:
                raw_filename = f"job_{job_id}_file.xlsx" if job_id else "downloaded_file"

            raw_filename = raw_filename.split("?")[0].split("#")[0].strip()
            target_path = get_unique_download_path(raw_filename)

            if isinstance(b64_data, str):
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                file_bytes = base64.b64decode(b64_data)
            elif isinstance(b64_data, bytes):
                file_bytes = b64_data
            else:
                return {"success": False, "error": "Invalid data format"}

            target_path.write_bytes(file_bytes)

            try:
                dl_event_file = _download_event_file()
                dl_event_file.parent.mkdir(parents=True, exist_ok=True)
                dl_event_file.write_text(json.dumps({
                    "action": "file_downloaded",
                    "filename": target_path.name,
                    "path": str(target_path.resolve()),
                    "size": len(file_bytes),
                    "time": time.time(),
                    "job_id": job_id,
                }), encoding="utf-8")
            except Exception:
                pass

            return {
                "success": True,
                "filename": target_path.name,
                "path": str(target_path.resolve()),
                "size": len(file_bytes),
            }
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
                  if (path.includes('clerk-dashboard') || href.includes('clerk-dashboard') || href.includes('job_type=outbound')) return true;
                  const allTables = [...document.querySelectorAll('table')];
                  return allTables.some(t => {{
                    const txt = (t.textContent || '').toLowerCase().replace(/[^a-z0-9]/g, '');
                    return txt.includes('jobid') || txt.includes('jobnumber') || txt.includes('jobno');
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
                  const jIdx = headers.findIndex(h => ['jobid', 'jobnumber', 'jobno', 'job', 'job#'].includes(h) || h.includes('jobid'));
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
                  values.push({{
                    job_id: jobVal,
                    client: clientVal,
                    status: stVal,
                    warehouse: whVal,
                    gatepass: gatepassVal,
                    seal: sealVal,
                    delivery_location: deliveryVal
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

              // ---------------- Center Web Portal & Content ----------------
              const centerPortal = () => {{
                try {{
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
                        display: flex !important;
                        justify-content: center !important;
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
                        t.parentElement.style.display = 'flex';
                        t.parentElement.style.justifyContent = 'center';
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

              const getCurrentJobId = () => {{
                try {{
                  const m = (location.pathname || '').match(/\\/warf\\/(?:start\\/)?([^\\/?#]+)/i);
                  if (m) return m[1];
                  const headings = [...document.querySelectorAll('h1, h2, h3, h4, h5')];
                  for (const h of headings) {{
                    const hm = (h.textContent || '').match(/Job\\s*ID\\s*[-:]\\s*([A-Za-z0-9_-]+)/i);
                    if (hm) return hm[1];
                  }}
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

              const fetchAndSaveFile = async (url, suggestedName, statusEl = null) => {{
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
                        const result = await window.pywebview.api.save_downloaded_file({{
                          filename: suggestedName || url.split('/').pop().split('?')[0] || 'downloaded_file',
                          data: base64Data,
                          url: url,
                          job_id: getCurrentJobId(),
                        }});
                        if (result && result.success) {{
                          showDownloadToast('✓ Saved: ' + result.filename + ' to Downloads folder!');
                          if (statusEl) statusEl.textContent = '✓ Downloaded';
                          resolve(true);
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
                  fetchAndSaveFile(url, filename, link);
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
                    fetchAndSaveFile(imgUrl, filename, dlBtn);
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
                        fetchAndSaveFile(modalImg.src, filename, modalDlBtn);
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

              const downloadAllJobFiles = async () => {{
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
                for (let i = 0; i < items.length; i++) {{
                  if (allBtn) allBtn.textContent = '⏳ Downloading (' + (i + 1) + '/' + items.length + ')...';
                  const ok = await fetchAndSaveFile(items[i].url, items[i].filename);
                  if (ok) successCount++;
                }}
                if (allBtn) {{
                  allBtn.disabled = false;
                  allBtn.textContent = '✓ Downloaded ' + successCount + '/' + items.length + ' Files';
                  setTimeout(() => {{
                    allBtn.textContent = '📥 Download All Files';
                  }}, 4000);
                }}
                showDownloadToast('✓ Finished: ' + successCount + ' of ' + items.length + ' file(s) saved to Downloads folder!');
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
                  btn.addEventListener('click', downloadAllJobFiles);
                  if (document.body) document.body.appendChild(btn);
                }} else {{
                  btn.style.display = 'block';
                }}
              }};
              attachDownloadAllButton();
              setInterval(attachDownloadAllButton, 1000);

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
                    executeStartJob(cmd.job_id);
                  }} else if (cmd && cmd.action === 'download_job_files') {{
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
        self.browser_log_path = _browser_log_file()
        self.download_event_path = _download_event_file()
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
        self._browser_embed_attempts = 0
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
            "Ready. Click 'Open Internal Browser' to launch the portal session."
            if self.username.get() and self.password.get()
            else "Enter portal credentials in Settings to automatically sign in and open Reconciliation."
        )
        self.status = tk.StringVar(value=initial_status)
        self._build()

    def _build(self):
        page = tk.Frame(self.container, bg="#faf8f2", padx=16, pady=8)
        page.pack(fill="both", expand=True)

        # Compact single-row top banner to maximize vertical height for the browser
        header_bar = tk.Frame(page, bg="#faf8f2")
        header_bar.pack(fill="x", pady=(0, 6))

        tk.Label(header_bar, text="Pending Jobs", bg="#faf8f2", fg="#0f172a", font=("Segoe UI", 13, "bold")).pack(side="left")
        self.run_button = ttk.Button(header_bar, text="Open Internal Browser", command=self.start)
        self.run_button.pack(side="left", padx=(14, 0))
        self.restart_button = ttk.Button(header_bar, text="🔄 Restart Browser", command=self.restart_browser)
        self.restart_button.pack(side="left", padx=(6, 0))
        tk.Label(header_bar, textvariable=self.status, bg="#faf8f2", fg="#475569", font=("Segoe UI", 9)).pack(side="left", padx=10)

        if self.on_open_settings:
            ttk.Button(header_bar, text="⚙ Settings", command=self.on_open_settings).pack(side="right")

        results = tk.Frame(page, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=10, pady=6)
        results.pack(fill="both", expand=True)
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=3, minsize=520)
        results.rowconfigure(1, weight=1, minsize=100)

        # ---------------- Top: Internal Reconciliation Browser ----------------
        browser_panel = tk.Frame(results, bg="#ffffff")
        browser_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
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
            self.browser_host, text="The internal browser will appear here after you click Open Internal Browser.",
            bg="#e2e8f0", fg="#64748b", font=("Segoe UI", 10), wraplength=600,
        ).place(relx=0.5, rely=0.5, anchor="center")

        # ---------------- Bottom: Job Console (IDs, Status & Actions) ----------------
        console_panel = tk.Frame(results, bg="#ffffff")
        console_panel.grid(row=1, column=0, sticky="nsew")
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
            self.status.set("The internal browser is already open. Use its Export Job IDs button after reaching Reconciliation.")
            self.set_browser_visible(True)
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
            if self.result_path.exists():
                try:
                    self.result_path.unlink()
                except Exception:
                    pass
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

    def _poll_internal_browser_results(self):
        try:
            if self.result_path.exists():
                payload = json.loads(self.result_path.read_text(encoding="utf-8"))
                ids = payload.get("job_ids", [])
                records = payload.get("records", [])
                if records and isinstance(records, list):
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
                    self.status.set(f"✓ Downloaded '{fn}' (saved to Downloads folder)")
        except Exception:
            pass
        if self.browser_process is not None and self.browser_process.poll() is None:
            self.root.after(750, self._poll_internal_browser_results)

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
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        candidates = []
        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @enum_proc_type
        def collect(hwnd, _lparam):
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == process_id and user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, length + 1)
                t_val = title.value
                if "Reconciliation Browser" in t_val or "EFL NEXUS" in t_val:
                    candidates.append(hwnd)
            return True

        user32.EnumWindows(enum_proc_type(collect), 0)
        return candidates[0] if candidates else None

    def _find_and_embed_internal_browser(self):
        process = self.browser_process
        if process is None:
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

    def _embed_internal_browser(self, hwnd):
        """Reparent the helper's WebView2 window into Tool 6's browser frame."""
        if sys.platform != "win32":
            raise RuntimeError("Internal browser embedding is supported on Windows only.")
        self.browser_host.update_idletasks()
        host_hwnd = int(self.browser_host.winfo_id())

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
        chrome = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000
        user32.ShowWindow(hwnd, 0)
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, (style & ~chrome) | WS_CHILD | WS_VISIBLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, 0)

        ctypes.set_last_error(0)
        user32.SetParent(hwnd, host_hwnd)
        actual_parent = int(user32.GetParent(hwnd) or 0)
        if actual_parent != host_hwnd:
            err = ctypes.get_last_error()
            raise OSError(err, f"Windows could not attach the browser window (window={hwnd}, host={host_hwnd}, actual={actual_parent})")

        self.browser_hwnd = hwnd
        self._resize_internal_browser()
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

    def set_browser_visible(self, visible: bool):
        """Hide the foreign child window when another NEXUS page is selected."""
        if not self.browser_hwnd:
            return
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.ShowWindow(self.browser_hwnd, 5 if visible else 0)
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

    def _show_results(self, items):
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

        # Check for newly detected pending jobs to play the notification sound
        current_pending = {
            r["job_id"].strip().casefold()
            for r in records
            if r.get("status") == "Pending" and r.get("job_id")
        }
        new_pending = current_pending - getattr(self, "_seen_pending_ids", set())
        if new_pending and getattr(self, "sound_enabled", None) and self.sound_enabled.get():
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

        # Check if browser helper process is active
        if self.browser_process is None or self.browser_process.poll() is not None:
            if not getattr(self, "driver", None):
                if messagebox.askyesno(
                    "Browser Not Open",
                    f"The internal browser is not currently running.\n\n"
                    f"Would you like to open it now to start job '{job_id}'?",
                ):
                    self.start()
                    self._send_browser_command("start_job", job_id=job_id)
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

        sent = self._send_browser_command("start_job", job_id=job_id)
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

        if self.browser_process is None or self.browser_process.poll() is not None:
            if not getattr(self, "driver", None):
                if messagebox.askyesno(
                    "Browser Not Open",
                    f"The internal browser is not currently running.\n\n"
                    f"Would you like to open it now to view and download files for job '{job_id}'?",
                ):
                    self.start()
                    self._send_browser_command("start_job", job_id=job_id)
                    self.root.after(2000, lambda: self._send_browser_command("download_job_files", job_id=job_id))
                return

        sent = self._send_browser_command("download_job_files", job_id=job_id)
        if sent:
            self.status.set(f"Requested file download for Job ID '{job_id}' in portal browser...")

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
