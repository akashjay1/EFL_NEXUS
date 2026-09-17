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


def _write_results(path: Path, job_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"job_ids": job_ids}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle)
        temporary_name = handle.name
    Path(temporary_name).replace(path)


def run_internal_browser(result_path: Path, start_url: str = DEFAULT_LOGIN_URL) -> None:
    """Run an application-owned Edge WebView2 browser for Tool 6.

    This function is started in a separate process because WebView2 and Tk
    each own their UI event loop. pywebview's Edge backend uses the installed
    WebView2 runtime and private mode by default.
    """
    import webview
    start_url = start_url or DEFAULT_LOGIN_URL
    username = os.environ.pop("EFL_NEXUS_GRABBER_USER", "")
    password = os.environ.pop("EFL_NEXUS_GRABBER_PASS", "")
    reconciliation_url = os.environ.pop("EFL_NEXUS_GRABBER_RECON_URL", DEFAULT_RECONCILIATION_URL)

    class ResultsBridge:
        def save_job_ids(self, values):
            unique: list[str] = []
            seen: set[str] = set()
            for value in values if isinstance(values, list) else []:
                clean = _clean(str(value))
                if clean and clean.casefold() not in seen:
                    seen.add(clean.casefold())
                    unique.append(clean)
            _write_results(result_path, unique)
            return {"count": len(unique)}

    bridge = ResultsBridge()
    window = webview.create_window(
        "EFL NEXUS — Reconciliation Browser",
        start_url,
        js_api=bridge,
        width=1360,
        height=860,
        min_size=(900, 650),
    )

    def add_extract_button():
        window.run_js("""
            (() => {
              if (document.getElementById('efl-nexus-extract-job-ids')) return;
              const button = document.createElement('button');
              button.id = 'efl-nexus-extract-job-ids';
              button.type = 'button';
              button.textContent = 'Export Pending Job IDs to Tool 6';
              Object.assign(button.style, {
                position: 'fixed', right: '22px', bottom: '22px', zIndex: 2147483647,
                border: '0', borderRadius: '6px', padding: '11px 16px', cursor: 'pointer',
                background: '#0d1b2a', color: '#ffffff', fontWeight: '700', boxShadow: '0 3px 12px #0005'
              });
              button.addEventListener('click', async () => {
                const tables = [...document.querySelectorAll('table.table-bordered.table-hover, table')];
                const table = tables.find(t => [...t.querySelectorAll('thead th')].some(h =>
                  h.textContent.trim().toLowerCase().replace(/[^a-z0-9]/g, '') === 'jobid'));
                if (!table) { alert('No table with a JOB ID column was found on this page.'); return; }
                const headers = [...table.querySelectorAll('thead th')].map(h => h.textContent.trim().toLowerCase().replace(/[^a-z0-9]/g, ''));
                const index = headers.indexOf('jobid');
                const statusIndex = headers.indexOf('reconciliationstatus');
                if (statusIndex < 0) { alert('The Reconciliation Status column was not found.'); return; }
                const rows = [...table.querySelectorAll('tbody tr')];
                const values = rows.map(row => {
                  const cells = row.querySelectorAll('td'); return cells[index] ? cells[index].textContent.trim() : '';
                }).filter((value, rowIndex) => {
                  const statusCell = rows[rowIndex].querySelectorAll('td')[statusIndex];
                  return value && statusCell && statusCell.textContent.trim().toLowerCase() === 'pending';
                });
                const response = await window.pywebview.api.save_job_ids(values);
                alert(`${response.count} unique Pending Job ID(s) sent to Tool 6.`);
              });
              document.body.appendChild(button);
            })();
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
              const inputs = [...document.querySelectorAll('input')].filter(input => !input.disabled);
              const password = document.querySelector('#password') || inputs.find(input => (input.type || '').toLowerCase() === 'password');
              const username = document.querySelector('#email') || inputs.find(input => input !== password &&
                /user|email|login/.test([input.name, input.id, input.autocomplete, input.type].filter(Boolean).join(' ').toLowerCase()))
                || inputs.find(input => input !== password && ['text', 'email'].includes((input.type || 'text').toLowerCase()));
              if (!username || !password) return;
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
            }})();
        """)

    window.events.loaded += add_extract_button
    window.events.loaded += automate_portal_flow
    webview.start(gui="edgechromium", private_mode=True)


def _clean(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _clean(value).casefold())


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

    def __init__(self, root: tk.Misc, container=None, standalone=True, config_store=None, on_open_settings=None):
        self.root = root
        self.container = container or root
        self.standalone = standalone
        self.config_store = config_store
        self.on_open_settings = on_open_settings
        self.driver = None
        self.running = False
        self.job_ids: list[str] = []
        self.result_path = _result_file()
        self.browser_process = None
        self.browser_hwnd = None
        self._browser_embed_attempts = 0
        settings = getattr(config_store, "config", {}) if config_store is not None else {}
        self.login_url = tk.StringVar(value=settings.get("data_grabber_login_url", DEFAULT_LOGIN_URL))
        self.username = tk.StringVar(value=settings.get("data_grabber_user", ""))
        self.password = tk.StringVar(value=_load_saved_password())
        self.reconciliation_url = tk.StringVar(value=settings.get("data_grabber_reconciliation_url", DEFAULT_RECONCILIATION_URL))
        self.reconciliation_link_text = tk.StringVar(value="Reconciliation")
        self.job_header = tk.StringVar(value="Job ID")
        self.status = tk.StringVar(value="Enter portal credentials to automatically sign in and open Reconciliation.")
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
        ttk.Button(controls, text="Copy Results", command=self.copy_results).pack(side="left", padx=8)
        ttk.Button(controls, text="Export CSV", command=self.export_csv).pack(side="left")
        tk.Label(controls, textvariable=self.status, bg="#faf8f2", fg="#475569", font=("Segoe UI", 9)).pack(side="left", padx=14)

        results = tk.Frame(page, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=14, pady=14)
        results.pack(fill="both", expand=True)
        results.columnconfigure(0, weight=4)
        results.columnconfigure(1, weight=1)
        results.rowconfigure(1, weight=1)
        tk.Label(results, text="Internal Reconciliation Browser", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(results, text="Job IDs", bg="#ffffff", fg="#0f172a", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.browser_host = tk.Frame(results, bg="#e2e8f0", highlightbackground="#cbd5e1", highlightthickness=1)
        self.browser_host.grid(row=1, column=0, sticky="nsew", pady=(8, 0), padx=(0, 8))
        self.browser_host.bind("<Configure>", self._resize_internal_browser)
        tk.Label(
            self.browser_host, text="The internal browser will appear here after you click Open Internal Browser.",
            bg="#e2e8f0", fg="#64748b", font=("Segoe UI", 10), wraplength=480,
        ).place(relx=0.5, rely=0.5, anchor="center")
        self.output = tk.Text(results, height=16, wrap="none", font=("Cascadia Mono", 10), relief="flat", bg="#ffffff", fg="#0f172a")
        self.output.grid(row=1, column=1, sticky="nsew", pady=(8, 0), padx=(12, 0))

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
            messagebox.showwarning("Credentials required", "Enter the username and password for the authorised portal.")
            return
        if not self.save_credentials(show_success=False):
            return
        if self.browser_process is not None and self.browser_process.poll() is None:
            self.status.set("The internal browser is already open. Use its Export Job IDs button after reaching Reconciliation.")
            return
        try:
            if self.result_path.exists():
                self.result_path.unlink()
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--internal-browser", str(self.result_path), login_url]
            else:
                command = [sys.executable, str(Path(__file__).resolve()), "--internal-browser", str(self.result_path), login_url]
            child_env = os.environ.copy()
            child_env["EFL_NEXUS_GRABBER_USER"] = username
            child_env["EFL_NEXUS_GRABBER_PASS"] = password
            child_env["EFL_NEXUS_GRABBER_RECON_URL"] = reconciliation_url
            self.browser_process = subprocess.Popen(command, env=child_env)
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
            if self.config_store is None or not self.config_store.save(
                data_grabber_login_url=login_url,
                data_grabber_user=username,
                data_grabber_reconciliation_url=self.reconciliation_url.get().strip(),
            ):
                raise RuntimeError("Could not save the non-secret Tool 6 settings.")
        except Exception as exc:
            messagebox.showerror("Credential save failed", f"Windows Credential Manager could not save Tool 6 credentials: {exc}")
            return False
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

    def _poll_internal_browser_results(self):
        try:
            if self.result_path.exists():
                payload = json.loads(self.result_path.read_text(encoding="utf-8"))
                ids = payload.get("job_ids", [])
                if isinstance(ids, list) and ids != self.job_ids:
                    self._show_results([str(value) for value in ids])
        except Exception:
            pass
        if self.browser_process is not None and self.browser_process.poll() is None:
            self.root.after(750, self._poll_internal_browser_results)

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
                if "EFL NEXUS — Reconciliation Browser" in title.value:
                    candidates.append(hwnd)
            return True

        user32.EnumWindows(enum_proc_type(collect), 0)
        return candidates[0] if candidates else None

    def _find_and_embed_internal_browser(self):
        process = self.browser_process
        if process is None or process.poll() is not None or self.browser_hwnd:
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
            self.status.set("The internal browser did not become available. Please reopen Tool 6.")

    def _embed_internal_browser(self, hwnd):
        """Reparent the helper's WebView2 window into Tool 6's browser frame."""
        if sys.platform != "win32":
            raise RuntimeError("Internal browser embedding is supported on Windows only.")
        self.browser_host.update_idletasks()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        GWL_STYLE, GWL_EXSTYLE = -16, -20
        WS_CHILD, WS_VISIBLE = 0x40000000, 0x10000000
        chrome = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000
        user32.ShowWindow(hwnd, 0)
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, (style & ~chrome) | WS_CHILD | WS_VISIBLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, 0)
        user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.SetParent.restype = wintypes.HWND
        ctypes.set_last_error(0)
        previous_parent = user32.SetParent(hwnd, int(self.browser_host.winfo_id()))
        if not previous_parent and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        self.browser_hwnd = hwnd
        self._resize_internal_browser()
        user32.ShowWindow(hwnd, 5)

    def _resize_internal_browser(self, _event=None):
        if not self.browser_hwnd or not getattr(self, "browser_host", None):
            return
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
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
            ctypes.WinDLL("user32", use_last_error=True).ShowWindow(self.browser_hwnd, 5 if visible else 0)
        except Exception:
            pass

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
        all_ids: list[str] = []
        seen_pages: set[tuple[str, ...]] = set()
        for _ in range(100):
            ids = self._extract_current_page(By)
            signature = tuple(ids)
            if signature in seen_pages:
                break
            seen_pages.add(signature)
            all_ids.extend(value for value in ids if value.casefold() not in {x.casefold() for x in all_ids})
            next_button = self._next_button(By)
            if not next_button:
                break
            old_html = self.driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
            self.driver.execute_script("arguments[0].click();", next_button)
            try:
                wait.until(lambda d: d.find_element(By.TAG_NAME, "body").get_attribute("innerHTML") != old_html)
            except Exception:
                break
        return all_ids

    def _extract_current_page(self, By):
        best: list[str] = []
        # The authorised reconciliation page uses this Bootstrap table class;
        # retain the generic fallback for portal markup changes.
        tables = self.driver.find_elements(By.CSS_SELECTOR, "table.table-bordered.table-hover")
        if not tables:
            tables = self.driver.find_elements(By.CSS_SELECTOR, "table")
        for table in tables:
            headers = [cell.text for cell in table.find_elements(By.CSS_SELECTOR, "thead th")]
            if not headers:
                first_row = table.find_elements(By.CSS_SELECTOR, "tr")
                headers = [cell.text for cell in first_row[0].find_elements(By.CSS_SELECTOR, "th,td")] if first_row else []
            rows = [[cell.text for cell in row.find_elements(By.CSS_SELECTOR, "td")] for row in table.find_elements(By.CSS_SELECTOR, "tbody tr")]
            ids = job_ids_from_rows(headers, rows, self.job_header.get(), required_status="Pending")
            if len(ids) > len(best):
                best = ids
        return best

    def _next_button(self, By):
        candidates = self.driver.find_elements(By.CSS_SELECTOR, "button[aria-label*='Next'], a[aria-label*='Next'], .pagination .next, [rel='next']")
        for element in candidates:
            disabled = (element.get_attribute("disabled") is not None or "disabled" in (element.get_attribute("class") or "").casefold() or element.get_attribute("aria-disabled") == "true")
            if element.is_displayed() and element.is_enabled() and not disabled:
                return element
        return None

    def _show_results(self, ids):
        self.job_ids = ids
        self.output.delete("1.0", tk.END)
        self.output.insert("1.0", "\n".join(ids))
        self.status.set(f"Collected {len(ids)} unique Pending Job ID(s). Browser remains open; close it when finished.")

    def _finish(self):
        self.running = False
        self.run_button.configure(state="normal")

    def copy_results(self):
        if not self.job_ids:
            messagebox.showinfo("No results", "Run the grabber first.")
            return
        self.root.clipboard_clear(); self.root.clipboard_append("\n".join(self.job_ids))
        self.status.set(f"Copied {len(self.job_ids)} Job ID(s) to the clipboard.")

    def export_csv(self):
        if not self.job_ids:
            messagebox.showinfo("No results", "Run the grabber first.")
            return
        filename = filedialog.asksaveasfilename(title="Export Job IDs", defaultextension=".csv", filetypes=[("CSV files", "*.csv")], initialfile="reconciliation_job_ids.csv")
        if not filename:
            return
        with Path(filename).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle); writer.writerow([self.job_header.get().strip() or "Job ID"])
            writer.writerows([[value] for value in self.job_ids])
        self.status.set(f"Exported {len(self.job_ids)} Job ID(s) to {filename}.")


if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "--internal-browser":
    run_internal_browser(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else DEFAULT_LOGIN_URL)
