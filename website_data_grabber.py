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


_HEADER_WORDS = ("job id", "jobid", "job number", "job no", "job #")

# Confirmed from the authorised portal screenshots supplied for this tool.
DEFAULT_LOGIN_URL = "https://active.efl3plofc.com/login"
DEFAULT_RECONCILIATION_URL = "https://active.efl3plofc.com/clerk-dashboard?job_type=OUTBOUND"
WINDOWS_CREDENTIAL_TARGET = "EFL_NEXUS:WebsiteDataGrabber"


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


def run_internal_browser(result_path: Path, start_url: str = DEFAULT_LOGIN_URL) -> None:
    """Run an application-owned Edge WebView2 browser for Tool 6.

    This function is started in a separate process because WebView2 and Tk
    each own their UI event loop. pywebview's Edge backend uses the installed
    WebView2 runtime and private mode by default.
    """
    try:
        import webview
    except Exception as err:
        sys.stderr.write(f"Failed to import 'webview' in internal browser helper: {err}\n")
        sys.stderr.flush()
        raise

    start_url = start_url or DEFAULT_LOGIN_URL
    username = os.environ.pop("EFL_NEXUS_GRABBER_USER", "")
    password = os.environ.pop("EFL_NEXUS_GRABBER_PASS", "")
    reconciliation_url = os.environ.pop("EFL_NEXUS_GRABBER_RECON_URL", DEFAULT_RECONCILIATION_URL)

    class ResultsBridge:
        def __init__(self, cmd_path: Path):
            self.cmd_path = cmd_path

        def save_job_ids(self, values):
            records: list[dict[str, str]] = []
            unique_ids: list[str] = []
            seen: set[str] = set()
            for item in values if isinstance(values, list) else []:
                if isinstance(item, dict):
                    raw_id = _clean(str(item.get("job_id", "")))
                    raw_client = _clean(str(item.get("client", "")))
                    raw_status = _clean(str(item.get("status", "")))
                else:
                    raw_id = _clean(str(item))
                    raw_client = ""
                    raw_status = ""
                if not raw_id:
                    continue
                key = raw_id.casefold()
                if key in seen:
                    continue
                seen.add(key)
                norm_status = normalize_reconciliation_status(raw_status)
                records.append({"job_id": raw_id, "client": raw_client, "status": norm_status})
                unique_ids.append(raw_id)
            _write_results(result_path, unique_ids, records)
            return {"count": len(unique_ids)}

        def get_pending_command(self):
            try:
                if self.cmd_path.exists():
                    text = self.cmd_path.read_text(encoding="utf-8")
                    self.cmd_path.unlink(missing_ok=True)
                    return json.loads(text)
            except Exception:
                pass
            return None

    bridge = ResultsBridge(_command_file())
    window = webview.create_window(
        "EFL NEXUS — Reconciliation Browser",
        start_url,
        js_api=bridge,
        width=1360,
        height=860,
        min_size=(900, 650),
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
                for (const t of allTables) {{
                  const headers = getHeaders(t);
                  const jIdx = headers.findIndex(h => ['jobid', 'jobnumber', 'jobno', 'job', 'job#'].includes(h) || h.includes('jobid'));
                  if (jIdx >= 0) {{
                    targetTable = t;
                    jobColIndex = jIdx;
                    clientColIndex = headers.findIndex(h => ['client', 'customer', 'clientname', 'account'].includes(h) || h.includes('client'));
                    statusColIndex = headers.findIndex(h => ['reconciliationstatus', 'status', 'reconstatus', 'jobstatus', 'state'].includes(h) || h.includes('reconciliation') || h.includes('status'));
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
                  values.push({{ job_id: jobVal, client: clientVal, status: stVal }});
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
                    btn.textContent = `✓ Synced ${{count}} Jobs (Auto: 5s)`;
                  }}
                  return true;
                }} catch (e) {{
                  if (isManual) alert('Error sending Job IDs to Tool 6: ' + e);
                  return false;
                }} finally {{
                  isExporting = false;
                }}
              }};

              let refreshSeconds = 5;
              let autoRefreshPaused = false;

              const attachButton = () => {{
                if (document.getElementById('efl-nexus-extract-job-ids')) return;
                const button = document.createElement('button');
                button.id = 'efl-nexus-extract-job-ids';
                button.type = 'button';
                button.textContent = 'Auto-Sync: 5s | Export Job IDs';
                Object.assign(button.style, {{
                  position: 'fixed', right: '22px', bottom: '22px', zIndex: 2147483647,
                  border: '0', borderRadius: '6px', padding: '11px 16px', cursor: 'pointer',
                  background: '#0d1b2a', color: '#ffffff', fontWeight: '700', boxShadow: '0 3px 12px #0005',
                  transition: 'background 0.2s, transform 0.1s'
                }});
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

              // 5-second Auto-Refresh timer when in reconciliation page
              const tickCountdown = () => {{
                if (!isReconciliationPage() || autoRefreshPaused) {{
                  refreshSeconds = 2;
                  const btn = document.getElementById('efl-nexus-extract-job-ids');
                  if (btn && !isReconciliationPage()) {{
                    btn.style.display = 'none';
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
                  refreshSeconds = 5;
                  if (btn) btn.textContent = 'Refreshing...';
                  autoExportJobIds(false).finally(() => {{
                    if (isReconciliationPage() && !autoRefreshPaused) {{
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
                  position: 'fixed', left: '22px', bottom: '22px', zIndex: 2147483647,
                  border: '0', borderRadius: '6px', padding: '11px 16px', cursor: 'pointer',
                  background: '#0d1b2a', color: '#ffffff', fontWeight: '700', boxShadow: '0 3px 12px #0005'
                }});
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
        raw_status = ""
        if status_column is not None and status_column < len(row):
            raw_status = row[status_column]
        rec = {
            "job_id": value,
            "status": normalize_reconciliation_status(raw_status),
        }
        if include_client:
            rec["client"] = client_val
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

    def __init__(self, root: tk.Misc, container=None, standalone=True, config_store=None, on_open_settings=None, on_job_started=None):
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
        self.driver = None
        self.running = False
        self.job_ids: list[str] = []
        self.records: list[dict[str, str]] = []
        self.result_path = _result_file()
        self.browser_log_path = _browser_log_file()
        self._browser_log_handle = None
        self.browser_process = None
        self.browser_hwnd = None
        self._browser_embed_attempts = 0
        settings = getattr(self.config_store, "config", {}) if self.config_store is not None else {}
        self.login_url = tk.StringVar(value=settings.get("data_grabber_login_url", DEFAULT_LOGIN_URL))
        self.username = tk.StringVar(value=settings.get("data_grabber_user", ""))
        self.password = tk.StringVar(value=_load_saved_password())
        self.reconciliation_url = tk.StringVar(value=settings.get("data_grabber_reconciliation_url", DEFAULT_RECONCILIATION_URL))
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
        page = tk.Frame(self.container, bg="#faf8f2", padx=32, pady=26)
        page.pack(fill="both", expand=True)
        tk.Label(page, text="Website Data Grabber", bg="#faf8f2", fg="#0f172a", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(
            page,
            text="Tool 6 · Automatically sign in with the application-owned Edge browser, open Reconciliation, and send every displayed Job ID back here.",
            bg="#faf8f2", fg="#64748b", font=("Segoe UI", 9), wraplength=900, justify="left",
        ).pack(anchor="w", pady=(4, 18))

        connection = tk.Frame(page, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=20, pady=14)
        connection.pack(fill="x")
        tk.Label(connection, text="Connection settings are managed in Settings.", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(connection, text="Credentials are stored in Windows Credential Manager for this Windows user.", bg="#ffffff", fg="#64748b", font=("Segoe UI", 9)).pack(side="left", padx=14)
        if self.on_open_settings:
            ttk.Button(connection, text="Open Settings", command=self.on_open_settings).pack(side="right")

        controls = tk.Frame(page, bg="#faf8f2")
        controls.pack(fill="x", pady=14)
        self.run_button = ttk.Button(controls, text="Open Internal Browser", command=self.start)
        self.run_button.pack(side="left")
        self.start_job_button = tk.Button(
            controls, text="▶ Start Selected Job",
            bg="#F28C28", fg="#ffffff", activebackground="#d97706", activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=3, cursor="hand2",
            command=self.start_selected_job,
        )
        self.start_job_button.pack(side="left", padx=8)
        self.restart_button = ttk.Button(controls, text="🔄 Restart Browser", command=self.restart_browser)
        self.restart_button.pack(side="left")
        tk.Label(controls, textvariable=self.status, bg="#faf8f2", fg="#475569", font=("Segoe UI", 9)).pack(side="left", padx=14)

        results = tk.Frame(page, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=14, pady=14)
        results.pack(fill="both", expand=True)
        results.columnconfigure(0, weight=3)
        results.columnconfigure(1, weight=2)
        results.rowconfigure(1, weight=1)
        browser_header = tk.Frame(results, bg="#ffffff")
        browser_header.grid(row=0, column=0, sticky="ew")
        tk.Label(browser_header, text="Internal Reconciliation Browser", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.auto_refresh_badge = tk.Label(browser_header, text="⚡ Auto-Refresh: 5s", bg="#ffffff", fg="#16a34a", font=("Segoe UI", 8, "bold"))
        self.auto_refresh_badge.pack(side="left", padx=(10, 0))
        self.back_button = ttk.Button(browser_header, text="◀ Go Back", command=self.browser_go_back)
        self.back_button.pack(side="right", padx=(4, 0))
        self.reload_button = ttk.Button(browser_header, text="🔄 Reload", command=self.browser_reload)
        self.reload_button.pack(side="right", padx=(4, 0))
        self.home_button = ttk.Button(browser_header, text="🏠 Reconciliation", command=self.browser_go_home)
        self.home_button.pack(side="right", padx=(4, 0))

        tk.Label(results, text="Reconciliation Job IDs & Status", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.browser_host = tk.Frame(results, bg="#e2e8f0", highlightbackground="#cbd5e1", highlightthickness=1)
        self.browser_host.grid(row=1, column=0, sticky="nsew", pady=(8, 0), padx=(0, 8))
        self.browser_host.bind("<Configure>", self._resize_internal_browser)
        tk.Label(
            self.browser_host, text="The internal browser will appear here after you click Open Internal Browser.",
            bg="#e2e8f0", fg="#64748b", font=("Segoe UI", 10), wraplength=480,
        ).place(relx=0.5, rely=0.5, anchor="center")

        style = ttk.Style()
        try:
            if style.theme_use() in ("vista", "xpnative", "winnative"):
                style.theme_use("clam")
        except Exception:
            pass

        table_frame = tk.Frame(results, bg="#ffffff")
        table_frame.grid(row=1, column=1, sticky="nsew", pady=(8, 0), padx=(12, 0))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_frame, columns=("job_id", "client", "status", "action"), show="headings", selectmode="extended")
        self.tree.heading("job_id", text="Job ID", anchor="w")
        self.tree.heading("client", text="Client", anchor="w")
        self.tree.heading("status", text="Reconciliation Status", anchor="w")
        self.tree.heading("action", text="Action", anchor="center")
        self.tree.column("job_id", width=130, minwidth=90, stretch=True)
        self.tree.column("client", width=100, minwidth=70, stretch=True)
        self.tree.column("status", width=120, minwidth=80, stretch=True)
        self.tree.column("action", width=75, minwidth=65, stretch=False, anchor="center")
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

    def set_connection_settings(self, login_url: str, username: str, password: str, reconciliation_url: str):
        """Apply Settings-page changes to an already-open Tool 6 instance."""
        self.login_url.set(login_url)
        self.username.set(username)
        self.password.set(password)
        self.reconciliation_url.set(reconciliation_url)
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
            records = extract_jobs_with_status(headers, rows, self.job_header.get(), include_client=True)
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
                if "client" in item:
                    rec["client"] = _clean(str(item.get("client", "")))
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
        root.title("EFL NEXUS — Tool 6: Website Data Grabber")
        root.geometry("1200x800")
        app = WebsiteDataGrabberApp(root, standalone=True)
        root.protocol("WM_DELETE_WINDOW", lambda: (app.close_browser(), root.destroy()))
        root.mainloop()
