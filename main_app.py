"""
EFL NEXUS - Unified Launcher & Automation Suite
Featuring 'Aurora Borealis' Aura Gradient Aesthetic UI and Dynamic Network Status.

RUN:
    python main_app.py

Requires korber_tool.py, reconciliation_tool.py, outlook_email_gui.py,
Pillow, and numpy.
"""

import os
import sys
import json
import shutil
import glob
import socket
import threading
import subprocess
import traceback
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageTk
from kpi_profile import load_saved_profile, validate_profile

try:
    from outlook_email_gui import ConfigStore, CONFIG_JSON_PATH
except Exception:
    ConfigStore = None
    CONFIG_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ---------------------------------------------------------------------------
# GitHub Repository Configuration
# ---------------------------------------------------------------------------
GITHUB_USER = "akashjay1"
GITHUB_REPO = "EFL_NEXUS"

# ---------------------------------------------------------------------------
# Theme Colors & Palette ('Aurora Borealis' Nebula Theme)
# Base backdrop: #faf8f2 with multi-layer cyan, mint, and sapphire blends.
# ---------------------------------------------------------------------------
BASE_BG = "#faf8f2"
CONTENT_BG = "#faf8f2"

SIDEBAR_BG = "#0b1420"
SIDEBAR_BORDER = "#142338"
SIDEBAR_BG_HOVER = "#13233a"
SIDEBAR_BG_ACTIVE = "#162e4c"
SIDEBAR_ACTIVE_ACCENT = "#00e5ff"  # Auroral Cyan
SIDEBAR_FG = "#94a3b8"
SIDEBAR_FG_ACTIVE = "#ffffff"

CARD_BG = "#ffffff"
CARD_BORDER = "#e2e8f0"
CARD_BORDER_HOVER = "#00e5ff"
CARD_TEXT_MAIN = "#0f172a"
CARD_TEXT_MUTED = "#64748b"

AURORA_CYAN = "#00e5ff"
AURORA_MINT = "#49cf9e"
AURORA_SAPPHIRE = "#00b7ff"
AURORA_AMBER = "#ff6b00"

SIDEBAR_WIDTH_EXPANDED = 230
SIDEBAR_WIDTH_COLLAPSED = 64

NAV_ITEMS = [
    ("dashboard", "🏠", "Dashboard"),
    ("tool1", "🔧", "Korber Automation"),
    ("tool2", "⚡", "Load Reconciliation"),
    ("tool3", "📧", "Outlook Email Sender"),
    ("tool4", "👥", "User KPI"),
    ("tool5", "🚚", "Korber AuditShip"),
    ("tool6", "🔗", "Pending Jobs"),
    ("settings", "⚙", "Settings"),
]

AUDITSHIP_RELATIVE_PATH = os.path.join("Korber_AuditShip", "KORBER AuditShip.exe")


def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    target = os.path.join(base_path, relative_path)
    if os.path.exists(target):
        return target
    if getattr(sys, 'frozen', False):
        exe_target = os.path.join(os.path.dirname(sys.executable), relative_path)
        if os.path.exists(exe_target):
            return exe_target
    return target


class ClearCacheDialog(tk.Toplevel):
    def __init__(self, master, app_dir, on_complete=None):
        super().__init__(master)
        self.app_dir = Path(app_dir)
        self.on_complete = on_complete
        self.title("Clear Storage & Cache Data")
        self.geometry("560x540")
        self.minsize(500, 480)
        self.configure(bg=BASE_BG)
        self.transient(master)
        self.grab_set()

        self._build_ui()
        self._center_window(master)

    def _center_window(self, master):
        self.update_idletasks()
        master.update_idletasks()
        mw = master.winfo_width() or 1000
        mh = master.winfo_height() or 700
        mx = master.winfo_rootx()
        my = master.winfo_rooty()
        dw = self.winfo_reqwidth()
        dh = self.winfo_reqheight()
        x = max(0, mx + (mw - dw) // 2)
        y = max(0, my + (mh - dh) // 2)
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        container = tk.Frame(self, bg=BASE_BG, padx=28, pady=24)
        container.pack(fill="both", expand=True)

        tk.Label(
            container, text="Clear Storage & Cache", bg=BASE_BG, fg="#0f172a",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            container,
            text="Select items to remove. This frees up disk space and resets automation sessions.",
            bg=BASE_BG, fg="#64748b", font=("Segoe UI", 9), wraplength=480, justify="left"
        ).pack(anchor="w", pady=(0, 16))

        # Card container for checkboxes
        card = tk.Frame(container, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=20, pady=16)
        card.pack(fill="both", expand=True, pady=(0, 16))

        # Checkbox variables
        self.var_profiles = tk.BooleanVar(value=True)
        self.var_cache = tk.BooleanVar(value=True)
        self.var_templates = tk.BooleanVar(value=True)
        self.var_settings = tk.BooleanVar(value=False)

        # Scan what exists
        profile_count = len(list(self.app_dir.glob("chrome_automation_profile_*")))
        template_files = []
        for t in ["templates.xlsx", "variance_templates.xlsx"]:
            if (self.app_dir / t).exists():
                template_files.append(t)
        template_count = len(template_files)

        # Checkbox rows
        self._make_checkbox_row(
            card, self.var_profiles,
            "Browser Automation Profiles",
            f"Removes Chrome session folders & singleton locks ({profile_count} profile folder{'s' if profile_count != 1 else ''} found)."
        )

        self._make_checkbox_row(
            card, self.var_cache,
            "Temporary Cache & WebDrivers",
            "Clears WebDriver binaries (~/.wdm) and Python bytecode caches."
        )

        self._make_checkbox_row(
            card, self.var_templates,
            "Saved Recipient & Variance Templates",
            f"Deletes templates.xlsx and variance_templates.xlsx ({template_count} file{'s' if template_count != 1 else ''} found)."
        )

        self._make_checkbox_row(
            card, self.var_settings,
            "Reconciliation Preferences & Send Logs",
            "Resets local column mapping history (.load_reconciliation_tool_settings.json) and sent_log.xlsx."
        )

        # Select all / none bar
        select_bar = tk.Frame(container, bg=BASE_BG)
        select_bar.pack(fill="x", pady=(0, 16))

        sel_all = tk.Label(select_bar, text="Select All", bg=BASE_BG, fg="#0ea5e9", font=("Segoe UI", 9, "bold"), cursor="hand2")
        sel_all.pack(side="left", padx=(0, 14))
        sel_all.bind("<Button-1>", lambda e: self._set_all(True))

        desel_all = tk.Label(select_bar, text="Deselect All", bg=BASE_BG, fg="#64748b", font=("Segoe UI", 9), cursor="hand2")
        desel_all.pack(side="left")
        desel_all.bind("<Button-1>", lambda e: self._set_all(False))

        # Bottom Buttons
        btn_bar = tk.Frame(container, bg=BASE_BG)
        btn_bar.pack(fill="x", side="bottom")

        clear_btn = tk.Label(
            btn_bar, text="🗑️  Clear Selected Data", bg="#dc2626", fg="#ffffff",
            font=("Segoe UI", 9, "bold"), padx=18, pady=8, cursor="hand2"
        )
        clear_btn.pack(side="left", padx=(0, 10))
        clear_btn.bind("<Button-1>", lambda e: self._execute_clear())
        clear_btn.bind("<Enter>", lambda e: clear_btn.config(bg="#b91c1c"))
        clear_btn.bind("<Leave>", lambda e: clear_btn.config(bg="#dc2626"))

        cancel_btn = tk.Label(
            btn_bar, text="Cancel", bg="#e2e8f0", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), padx=16, pady=8, cursor="hand2"
        )
        cancel_btn.pack(side="left")
        cancel_btn.bind("<Button-1>", lambda e: self.destroy())
        cancel_btn.bind("<Enter>", lambda e: cancel_btn.config(bg="#cbd5e1"))
        cancel_btn.bind("<Leave>", lambda e: cancel_btn.config(bg="#e2e8f0"))

    def _make_checkbox_row(self, parent, var, title, desc):
        row = tk.Frame(parent, bg="#ffffff", pady=6)
        row.pack(fill="x")

        cb = ttk.Checkbutton(row, variable=var)
        cb.pack(side="left", anchor="nw", padx=(0, 10), pady=2)

        text_box = tk.Frame(row, bg="#ffffff")
        text_box.pack(side="left", fill="x", expand=True)

        tk.Label(text_box, text=title, bg="#ffffff", fg="#0f172a", font=("Segoe UI", 9, "bold"), anchor="w").pack(anchor="w")
        tk.Label(text_box, text=desc, bg="#ffffff", fg="#64748b", font=("Segoe UI", 8), wraplength=380, justify="left", anchor="w").pack(anchor="w")

    def _set_all(self, val):
        self.var_profiles.set(val)
        self.var_cache.set(val)
        self.var_templates.set(val)
        self.var_settings.set(val)

    def _execute_clear(self):
        cleared_items = []
        errors = []

        # 1. Profiles
        if self.var_profiles.get():
            deleted_p = 0
            for p_dir in self.app_dir.glob("chrome_automation_profile_*"):
                if p_dir.is_dir():
                    try:
                        shutil.rmtree(p_dir, ignore_errors=True)
                        deleted_p += 1
                    except Exception as e:
                        errors.append(f"Profile {p_dir.name}: {e}")
            if deleted_p > 0:
                cleared_items.append(f"• {deleted_p} Chrome automation profile folder(s)")

        # 2. Cache & WDM
        if self.var_cache.get():
            wdm = Path.home() / ".wdm"
            if wdm.exists() and wdm.is_dir():
                try:
                    shutil.rmtree(wdm, ignore_errors=True)
                    cleared_items.append("• WebDriver binary cache (~/.wdm)")
                except Exception as e:
                    errors.append(f"WDM cache: {e}")

            pycache_count = 0
            for pyc in self.app_dir.glob("**/__pycache__"):
                if pyc.is_dir():
                    try:
                        shutil.rmtree(pyc, ignore_errors=True)
                        pycache_count += 1
                    except Exception:
                        pass
            if pycache_count > 0:
                cleared_items.append(f"• {pycache_count} Python __pycache__ directory/directories")

        # 3. Templates
        if self.var_templates.get():
            t_count = 0
            for t_file in ["templates.xlsx", "variance_templates.xlsx"]:
                target = self.app_dir / t_file
                if target.exists():
                    try:
                        target.unlink()
                        t_count += 1
                    except Exception as e:
                        errors.append(f"{t_file}: {e}")
            if t_count > 0:
                cleared_items.append(f"• {t_count} saved template spreadsheet(s)")

        # 4. Settings & Logs
        if self.var_settings.get():
            rec_set = Path.home() / ".load_reconciliation_tool_settings.json"
            if rec_set.exists():
                try:
                    rec_set.unlink()
                    cleared_items.append("• Reconciliation settings (.load_reconciliation_tool_settings.json)")
                except Exception as e:
                    errors.append(f"Settings: {e}")

            sent_l = self.app_dir / "sent_log.xlsx"
            if sent_l.exists():
                try:
                    sent_l.unlink()
                    cleared_items.append("• Outlook send log (sent_log.xlsx)")
                except Exception as e:
                    errors.append(f"Sent log: {e}")

        if not cleared_items and not errors:
            messagebox.showinfo("Storage & Cache", "No matching cache or profile files were found to clear.")
        else:
            msg = "Storage and cache cleanup completed successfully!\n\n"
            if cleared_items:
                msg += "Items removed:\n" + "\n".join(cleared_items) + "\n\n"
            if errors:
                msg += "Warnings / Skipped locked files:\n" + "\n".join(errors) + "\n\n"
            messagebox.showinfo("Cleanup Complete", msg)

        if self.on_complete:
            try:
                self.on_complete()
            except Exception:
                pass

        self.destroy()


class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EFL NEXUS")
        self.root.geometry("1560x940")
        self.root.minsize(1050, 700)
        self.root.configure(bg=BASE_BG)

        # Always open maximized in full screen
        try:
            self.root.state('zoomed')
        except Exception:
            pass

        # Set window / taskbar icon
        for icon_name in ("icon_2.ico", "icon.ico", "favicon.ico"):
            icon_path = get_resource_path(icon_name)
            if os.path.exists(icon_path):
                try:
                    self.root.iconbitmap(default=icon_path)
                    break
                except Exception:
                    try:
                        self.root.iconbitmap(icon_path)
                        break
                    except Exception:
                        pass

        # Configure modern TTK styles
        self._setup_ttk_styles()

        # Load icon_2 for sidebar branding
        self.sidebar_logo = self._load_header_icon(size=(24, 24))

        # Load / Ensure Aurora Background Image
        self.aurora_base_image = self._load_aurora_image()
        self.bg_photo = None
        self._resize_timer = None

        # Network connectivity state & UI handles
        self.is_online = True
        self._stop_network_monitor = threading.Event()
        self.dash_status_pill = None
        self.dash_status_lbl = None
        self.sidebar_status_box = None
        self.sidebar_status_lbl = None

        # Lazily-created tool instances
        self.tool1_lanes = {"a": None, "b": None}
        self.tool1_ready = False
        self.tool2_app = None
        self.tool3_app = None
        self.tool4_app = None
        self.tool5_process = None
        self.tool5_ready = False
        self.tool5_launch_button = None
        self.tool5_host_frame = None
        self.tool5_overlay = None
        self.tool5_hwnd = None
        self.tool5_watchdog_running = False
        self.tool6_app = None
        self.tool1_error = None
        self.tool2_error = None
        self.tool3_error = None
        self.tool4_error = None
        self.tool5_error = None
        self.tool6_error = None

        self.sidebar_collapsed = False
        self.active_page = None
        self.nav_buttons = {}  # key -> {"row":..., "accent":..., "label":...}

        self.config_store = ConfigStore(CONFIG_JSON_PATH)
        try:
            if ConfigStore is not None:
                from outlook_email_gui import SentLogStore
                SentLogStore(self.config_store).sort_local_records()
        except Exception:
            pass

        self._build_layout()
        self._build_sidebar()
        self._build_pages()

        self.show_page("dashboard")

        # Start non-blocking network monitor loop
        threading.Thread(target=self._network_monitor_worker, daemon=True).start()

        # Warm up heavy tool modules in the background right after startup
        self.root.after(150, self._start_background_warmup)

        # Pre-instantiate Tool 4 in idle time so opening User KPI is instant without stutter
        self.root.after(600, self._prewarm_tool4)

        # Silent update check 2 seconds after startup
        self.root.after(2000, lambda: self.check_for_updates(silent=True))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_ttk_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Notebook tabs
        style.configure(
            "TNotebook",
            background=BASE_BG,
            borderwidth=0
        )
        style.configure(
            "TNotebook.Tab",
            background="#e2e8f0",
            foreground="#334155",
            font=("Segoe UI", 9, "bold"),
            padding=[16, 8],
            borderwidth=0
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#0d1b2a")],
            foreground=[("selected", AURORA_CYAN)]
        )

        # Buttons
        style.configure(
            "Aurora.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=[14, 7],
            background="#0d1b2a",
            foreground="#ffffff",
            borderwidth=0
        )
        style.map(
            "Aurora.TButton",
            background=[("active", "#152e4c"), ("pressed", "#00e5ff")],
            foreground=[("pressed", "#0b1420")]
        )

        # LabelFrame
        style.configure(
            "Aurora.TLabelframe",
            background="#ffffff",
            foreground="#0f172a",
            relief="solid",
            borderwidth=1
        )
        style.configure(
            "Aurora.TLabelframe.Label",
            background="#ffffff",
            foreground="#0f172a",
            font=("Segoe UI", 10, "bold")
        )

    def _load_header_icon(self, size=(24, 24)):
        """Loads and resizes icon_2 for header bars."""
        for icon_name in ("icon_2.ico", "icon.ico", "favicon.ico"):
            icon_path = get_resource_path(icon_name)
            if os.path.exists(icon_path):
                try:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        img = Image.open(icon_path).convert("RGBA")
                        return ImageTk.PhotoImage(img.resize(size, Image.Resampling.LANCZOS))
                except Exception:
                    pass
        return None

    def _load_aurora_image(self):
        """Loads or automatically creates the Aurora Borealis background texture."""
        asset_path = get_resource_path(os.path.join("assets", "aurora_bg.png"))
        if not os.path.exists(asset_path):
            alt_path = get_resource_path("aurora_bg.png")
            if os.path.exists(alt_path):
                asset_path = alt_path
            else:
                try:
                    import generate_aurora_asset
                    return generate_aurora_asset.generate_aurora_image(1920, 1200, asset_path)
                except Exception:
                    pass

        try:
            return Image.open(asset_path)
        except Exception:
            fallback = Image.new("RGB", (1920, 1200), (250, 248, 242))
            return fallback

    # ------------------------------------------------------------------
    # Network Connectivity Monitor
    # ------------------------------------------------------------------
    def _network_monitor_worker(self):
        """Asynchronously tests internet connection and updates UI state."""
        while not self._stop_network_monitor.is_set():
            online = False
            for host, port in [("1.1.1.1", 53), ("8.8.8.8", 53), ("www.google.com", 80)]:
                try:
                    sock = socket.create_connection((host, port), timeout=1.8)
                    sock.close()
                    online = True
                    break
                except Exception:
                    continue

            if self.is_online != online:
                self.root.after(0, lambda o=online: self._apply_network_status(o))

            self._stop_network_monitor.wait(4.0)

    def _apply_network_status(self, is_online):
        """Updates the status pill on Dashboard and Sidebar."""
        self.is_online = is_online

        # Update Dashboard Status Pill
        if self.dash_status_pill and self.dash_status_pill.winfo_exists() and self.dash_status_lbl and self.dash_status_lbl.winfo_exists():
            pill_bg = "#e2fdf2" if is_online else "#fef2f2"
            pill_border = "#49cf9e" if is_online else "#ef4444"
            pill_fg = "#065f46" if is_online else "#991b1b"
            pill_text = "●  SYSTEM OPERATIONAL" if is_online else "●  SYSTEM OFFLINE"
            try:
                self.dash_status_pill.config(bg=pill_bg, highlightbackground=pill_border)
                self.dash_status_lbl.config(text=pill_text, bg=pill_bg, fg=pill_fg)
            except Exception:
                pass

        # Update Sidebar Status Badge
        if self.sidebar_status_box and self.sidebar_status_box.winfo_exists() and self.sidebar_status_lbl and self.sidebar_status_lbl.winfo_exists():
            status_bg = "#101d2d" if is_online else "#261418"
            status_fg = AURORA_MINT if is_online else "#ef4444"
            status_text = "● System Online" if is_online else "● System Offline"
            try:
                self.sidebar_status_box.config(bg=status_bg)
                self.sidebar_status_lbl.config(text=status_text, bg=status_bg, fg=status_fg)
                for child in self.sidebar_status_box.winfo_children():
                    if child != self.sidebar_status_lbl:
                        child.config(bg=status_bg)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Background Module Warmup
    # ------------------------------------------------------------------
    def _start_background_warmup(self):
        def _warmup():
            for mod in ("requests", "korber_tool", "reconciliation_tool", "outlook_email_gui", "KPI"):
                try:
                    __import__(mod)
                except Exception:
                    pass

            # Automatically update local and remote records to date order on startup
            try:
                import outlook_email_gui
                if hasattr(outlook_email_gui, 'SentLogStore'):
                    store = outlook_email_gui.SentLogStore(self.config_store)
                    store.sort_local_records()
                    store.get_counts()  # Triggers Google Apps Script doGet to sort records on sheet
            except Exception:
                pass

        threading.Thread(target=_warmup, daemon=True).start()

    # ------------------------------------------------------------------
    # Update Checker Functions
    # ------------------------------------------------------------------
    def get_current_version(self):
        # 1. Check next to executable / dev script first
        if getattr(sys, 'frozen', False):
            app_dir_ver = Path(sys.executable).parent / "version.txt"
        else:
            app_dir_ver = Path(__file__).resolve().parent / "version.txt"

        if app_dir_ver.exists():
            try:
                with open(app_dir_ver, "r", encoding="utf-8") as f:
                    ver = f.read().strip()
                    if ver:
                        return ver
            except Exception:
                pass

        # 2. Check bundled PyInstaller resource (sys._MEIPASS / version.txt)
        res_ver_path = get_resource_path("version.txt")
        if os.path.exists(res_ver_path):
            try:
                with open(res_ver_path, "r", encoding="utf-8") as f:
                    ver = f.read().strip()
                    if ver:
                        return ver
            except Exception:
                pass

        return "1.0.0"

    def check_for_updates(self, silent=False):
        if not self.is_online:
            if not silent:
                messagebox.showwarning(
                    "Network Offline",
                    "Cannot check for updates while system is offline. Please check your internet connection."
                )
            return

        threading.Thread(
            target=self._check_for_updates_worker,
            args=(silent,),
            daemon=True
        ).start()

    def _check_for_updates_worker(self, silent=False):
        import requests
        api_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
        current_version = self.get_current_version()

        try:
            headers = {"User-Agent": "EFL-Nexus-Updater"}
            response = requests.get(api_url, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()

            latest_version = data.get("tag_name", "").strip().lstrip("v")

            download_url = None
            for asset in data.get("assets", []):
                if asset.get("name", "").endswith(".zip"):
                    download_url = asset.get("browser_download_url")
                    break

            if not download_url:
                if not silent:
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Update Error", "No .zip asset found in the latest GitHub release."
                        )
                    )
                return

            def parse_ver(v):
                return tuple(map(int, v.split('.')))

            try:
                is_newer = parse_ver(latest_version) > parse_ver(current_version)
            except Exception:
                is_newer = latest_version > current_version

            if is_newer:
                self.root.after(
                    0,
                    lambda: self._prompt_update(latest_version, current_version, download_url)
                )
            else:
                if not silent:
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Up to Date", f"You are running the latest version (v{current_version})."
                        )
                    )

        except Exception as e:
            if not silent:
                self.root.after(
                    0,
                    lambda err=str(e): messagebox.showerror(
                        "Update Error", f"Could not check for updates:\n{err}"
                    )
                )

    def _prompt_update(self, latest_version, current_version, download_url):
        if messagebox.askyesno(
            "Update Available",
            f"A new version ({latest_version}) is available!\n\n"
            f"Current Version: v{current_version}\n\n"
            f"Would you like to download and update now?"
        ):
            if getattr(sys, 'frozen', False):
                app_dir = Path(sys.executable).parent
            else:
                app_dir = Path(__file__).resolve().parent
                
            updater_exe = app_dir / "updater.exe"

            if not updater_exe.exists():
                messagebox.showerror("Update Error", "updater.exe was not found in the application directory.")
                return

            cmd = [
                str(updater_exe),
                "--url", download_url,
                "--version", latest_version,
                "--pid", str(os.getpid()),
                "--appdir", str(app_dir)
            ]

            subprocess.Popen(cmd)
            self.root.destroy()
            sys.exit(0)

    # ------------------------------------------------------------------
    # Layout Scaffolding
    # ------------------------------------------------------------------
    def _build_layout(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Sidebar Frame
        self.sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=SIDEBAR_WIDTH_EXPANDED)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)

        # Content outer container
        self.content_outer = tk.Frame(self.root, bg=BASE_BG)
        self.content_outer.grid(row=0, column=1, sticky="nsew")
        self.content_outer.columnconfigure(0, weight=1)
        self.content_outer.rowconfigure(0, weight=1)

        self.pages = {}

    # ------------------------------------------------------------------
    # Sidebar Component
    # ------------------------------------------------------------------
    def _build_sidebar(self):
        for w in self.sidebar.winfo_children():
            w.destroy()

        # --- Brand Row ---
        brand_row = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        brand_row.pack(fill="x", pady=(18, 18), padx=14)

        if not self.sidebar_collapsed:
            if self.sidebar_logo:
                tk.Label(brand_row, image=self.sidebar_logo, bg=SIDEBAR_BG).pack(side="left", padx=(0, 10))
            tk.Label(
                brand_row, text="EFL NEXUS", bg=SIDEBAR_BG, fg="#ffffff",
                font=("Segoe UI", 13, "bold"), anchor="w"
            ).pack(side="left")
        else:
            if self.sidebar_logo:
                tk.Label(brand_row, image=self.sidebar_logo, bg=SIDEBAR_BG).pack(fill="x")
            else:
                tk.Label(
                    brand_row, text="EN", bg=SIDEBAR_BG, fg="#ffffff",
                    font=("Segoe UI", 12, "bold"), anchor="center"
                ).pack(fill="x")

        # Divider line
        div = tk.Frame(self.sidebar, bg=SIDEBAR_BORDER, height=1)
        div.pack(fill="x", padx=12, pady=(0, 14))

        # --- Navigation Items ---
        self.nav_buttons = {}
        for key, icon, label in NAV_ITEMS:
            self.nav_buttons[key] = self._make_nav_button(key, icon, label)

        # --- Spacer ---
        spacer = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        spacer.pack(fill="both", expand=True)

        # --- Status Badge & Collapse Toggle ---
        if not self.sidebar_collapsed:
            status_bg = "#101d2d" if self.is_online else "#261418"
            status_fg = AURORA_MINT if self.is_online else "#ef4444"
            status_text = "● System Online" if self.is_online else "● System Offline"

            self.sidebar_status_box = tk.Frame(self.sidebar, bg=status_bg, padx=10, pady=8)
            self.sidebar_status_box.pack(fill="x", padx=12, pady=(0, 12))
            self.sidebar_status_lbl = tk.Label(
                self.sidebar_status_box, text=status_text, bg=status_bg, fg=status_fg,
                font=("Segoe UI", 8, "bold"), anchor="w"
            )
            self.sidebar_status_lbl.pack(anchor="w")
            tk.Label(
                self.sidebar_status_box, text=f"v{self.get_current_version()}", bg=status_bg, fg="#64748b",
                font=("Segoe UI", 8), anchor="w"
            ).pack(anchor="w")
        else:
            self.sidebar_status_box = None
            self.sidebar_status_lbl = None

        toggle_row = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        toggle_row.pack(fill="x", pady=(0, 14), padx=10)
        toggle_text = "▶" if self.sidebar_collapsed else "◀   Collapse"
        self.toggle_btn = tk.Label(
            toggle_row, text=toggle_text, bg=SIDEBAR_BG, fg=SIDEBAR_FG,
            font=("Segoe UI", 9, "bold"), cursor="hand2", anchor="center" if self.sidebar_collapsed else "w",
            padx=10, pady=8
        )
        self.toggle_btn.pack(fill="x")
        self.toggle_btn.bind("<Button-1>", lambda e: self.toggle_sidebar())
        self.toggle_btn.bind("<Enter>", lambda e: self.toggle_btn.config(bg=SIDEBAR_BG_HOVER, fg="#ffffff"))
        self.toggle_btn.bind("<Leave>", lambda e: self.toggle_btn.config(bg=SIDEBAR_BG, fg=SIDEBAR_FG))

        self._refresh_nav_highlight()

    def _make_nav_button(self, key, icon, label):
        row = tk.Frame(self.sidebar, bg=SIDEBAR_BG, cursor="hand2")
        row.pack(fill="x", padx=8, pady=3)

        # Left active indicator bar
        accent = tk.Frame(row, bg=SIDEBAR_BG, width=3)
        accent.pack(side="left", fill="y")

        if self.sidebar_collapsed:
            lbl = tk.Label(
                row, text=icon, bg=SIDEBAR_BG, fg=SIDEBAR_FG,
                font=("Segoe UI", 12), anchor="center", padx=6, pady=9
            )
            lbl.pack(side="left", fill="both", expand=True)
        else:
            icon_lbl = tk.Label(
                row, text=icon, bg=SIDEBAR_BG, fg=SIDEBAR_FG,
                font=("Segoe UI", 11), anchor="center", width=3, pady=9
            )
            icon_lbl.pack(side="left")
            lbl = tk.Label(
                row, text=label, bg=SIDEBAR_BG, fg=SIDEBAR_FG,
                font=("Segoe UI", 9, "bold"), anchor="w", padx=6, pady=9
            )
            lbl.pack(side="left", fill="both", expand=True)

        def on_click(e, k=key):
            self.show_page(k)

        def on_enter(e):
            if self.active_page != key:
                row.config(bg=SIDEBAR_BG_HOVER)
                for child in row.winfo_children():
                    if child != accent:
                        child.config(bg=SIDEBAR_BG_HOVER, fg="#ffffff")

        def on_leave(e):
            if self.active_page != key:
                row.config(bg=SIDEBAR_BG)
                for child in row.winfo_children():
                    if child != accent:
                        child.config(bg=SIDEBAR_BG, fg=SIDEBAR_FG)

        for widget in [row] + list(row.winfo_children()):
            widget.bind("<Button-1>", on_click)
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

        return {"row": row, "accent": accent, "label": lbl}

    def _refresh_nav_highlight(self):
        for key, widgets in self.nav_buttons.items():
            active = (key == self.active_page)
            bg = SIDEBAR_BG_ACTIVE if active else SIDEBAR_BG
            fg = SIDEBAR_FG_ACTIVE if active else SIDEBAR_FG
            accent_bg = SIDEBAR_ACTIVE_ACCENT if active else SIDEBAR_BG

            widgets["row"].config(bg=bg)
            widgets["accent"].config(bg=accent_bg)
            for child in widgets["row"].winfo_children():
                if child != widgets["accent"]:
                    child.config(bg=bg, fg=fg)

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        new_w = SIDEBAR_WIDTH_COLLAPSED if self.sidebar_collapsed else SIDEBAR_WIDTH_EXPANDED
        self.sidebar.configure(width=new_w)
        self._build_sidebar()

    # ------------------------------------------------------------------
    # Pages Construction
    # ------------------------------------------------------------------
    def _build_pages(self):
        for key, _, _ in NAV_ITEMS:
            frame = tk.Frame(self.content_outer, bg=BASE_BG)
            frame.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = frame

        self._build_dashboard_page(self.pages["dashboard"])
        self._build_settings_page(self.pages["settings"])

    def show_page(self, key):
        self.active_page = key
        self._refresh_nav_highlight()

        # A foreign child HWND needs an explicit hide when another stacked Tk
        # page is selected; Tk's tkraise alone cannot manage its visibility.
        if key != "tool5":
            self._set_tool5_window_visibility(False)
        if key != "tool6" and self.tool6_app is not None:
            self.tool6_app.set_browser_visible(False)

        # Map of tool keys → whether they are already loaded
        _tool_loaded = {
            "tool1": self.tool1_ready or self.tool1_error is not None,
            "tool2": self.tool2_app is not None or self.tool2_error is not None,
            "tool3": self.tool3_app is not None or self.tool3_error is not None,
            "tool4": self.tool4_app is not None or self.tool4_error is not None,
            "tool5": self.tool5_ready or self.tool5_error is not None,
            "tool6": self.tool6_app is not None or self.tool6_error is not None,
        }

        if key in _tool_loaded and not _tool_loaded[key]:
            # Show loading overlay immediately, then build the tool asynchronously
            self._show_loading_overlay(key)
            self.pages[key].tkraise()
            self.root.after(50, lambda k=key: self._deferred_tool_load(k))
            return

        # Already loaded or non-tool page — switch instantly
        if key == "tool2" and self.tool2_app is not None:
            try:
                self.tool2_app.refresh_job_queue()
            except Exception:
                pass
        self.pages[key].tkraise()
        if key == "tool5":
            self._set_tool5_window_visibility(True)
        elif key == "tool6" and self.tool6_app is not None:
            self.tool6_app.set_browser_visible(True)

    # ------------------------------------------------------------------
    # Deferred Tool Loader (runs behind the spinner overlay)
    # ------------------------------------------------------------------
    def _deferred_tool_load(self, key):
        if key == "tool1":
            self._ensure_tool1()
        elif key == "tool2":
            self._ensure_tool2()
        elif key == "tool3":
            self._ensure_tool3()
        elif key == "tool4":
            self._ensure_tool4()
        elif key == "tool5":
            self._ensure_tool5()
            return  # tool5 manages its own overlay
        elif key == "tool6":
            self._ensure_tool6()
        self._hide_loading_overlay()

    # ------------------------------------------------------------------
    # Fade-Arc Loading Spinner Overlay
    # ------------------------------------------------------------------
    _TOOL_DISPLAY_NAMES = {
        "tool1": "Korber Automation",
        "tool2": "Load Reconciliation",
        "tool3": "Outlook Email Sender",
        "tool4": "User KPI",
        "tool5": "Korber AuditShip",
        "tool6": "Pending Jobs",
    }

    def _show_loading_overlay(self, key):
        """Show a full-page overlay with an animated fade-arc spinner."""
        page = self.pages[key]

        # Overlay frame that fills the entire page
        overlay = tk.Frame(page, bg=BASE_BG)
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()

        # Center wrapper
        center = tk.Frame(overlay, bg=BASE_BG)
        center.place(relx=0.5, rely=0.42, anchor="center")

        # Spinner canvas
        spinner_size = 52
        canvas = tk.Canvas(
            center, width=spinner_size, height=spinner_size,
            bg=BASE_BG, highlightthickness=0
        )
        canvas.pack()

        # Tool name label
        tool_name = self._TOOL_DISPLAY_NAMES.get(key, "Module")
        tk.Label(
            center, text=f"Loading {tool_name}...",
            bg=BASE_BG, fg="#334155",
            font=("Segoe UI", 12, "bold")
        ).pack(pady=(16, 4))

        tk.Label(
            center, text="Initializing components",
            bg=BASE_BG, fg="#94a3b8",
            font=("Segoe UI", 9)
        ).pack()

        # Store state for animation
        self._loading_overlay = overlay
        self._spinner_canvas = canvas
        self._spinner_size = spinner_size
        self._spinner_angle = 0
        self._spinner_running = True
        self._animate_fade_arc()

    def _animate_fade_arc(self):
        """Draw one frame of the fade-arc spinner and schedule the next."""
        if not self._spinner_running:
            return
        canvas = self._spinner_canvas
        if not canvas or not canvas.winfo_exists():
            return

        canvas.delete("all")
        size = self._spinner_size
        cx = cy = size / 2
        r = size / 2 - 5
        segments = 12
        seg_angle = 360 / segments
        line_width = 4

        for i in range(segments):
            start = self._spinner_angle + i * seg_angle
            # Segment 0 is darkest, fading to near-invisible
            alpha = max(0.06, 1.0 - (i / segments) * 0.92)
            color = self._blend_hex(SIDEBAR_BG_ACTIVE, BASE_BG, alpha)
            canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start, extent=seg_angle - 4,
                outline=color, width=line_width, style="arc"
            )

        self._spinner_angle = (self._spinner_angle - 30) % 360
        canvas.after(75, self._animate_fade_arc)

    @staticmethod
    def _blend_hex(fg, bg, alpha):
        """Blend fg color into bg at given alpha (0-1) to simulate opacity."""
        r1, g1, b1 = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
        r2, g2, b2 = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        r = int(r1 * alpha + r2 * (1 - alpha))
        g = int(g1 * alpha + g2 * (1 - alpha))
        b = int(b1 * alpha + b2 * (1 - alpha))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _hide_loading_overlay(self):
        """Destroy the spinner overlay once the tool is fully loaded."""
        self._spinner_running = False
        if hasattr(self, '_loading_overlay') and self._loading_overlay:
            try:
                self._loading_overlay.destroy()
            except Exception:
                pass
            self._loading_overlay = None

    # ------------------------------------------------------------------
    # Dashboard Page with Aurora Canvas & Frosted Cards
    # ------------------------------------------------------------------
    def _build_dashboard_page(self, parent):
        # Background Canvas
        self.dash_canvas = tk.Canvas(parent, bg=BASE_BG, highlightthickness=0)
        self.dash_canvas.pack(fill="both", expand=True)

        # Smooth debounced resize for background
        def on_canvas_resize(event):
            w, h = event.width, event.height
            if w < 50 or h < 50:
                return
            if self._resize_timer is not None:
                self.root.after_cancel(self._resize_timer)
            self._resize_timer = self.root.after(30, lambda: self._update_aurora_bg(w, h))

        self.dash_canvas.bind("<Configure>", on_canvas_resize)

        # Interactive Overlay Frame (sitting above the canvas layers)
        self.dash_overlay = tk.Frame(self.dash_canvas, bg=BASE_BG)
        self.dash_window = self.dash_canvas.create_window(
            (0, 0), window=self.dash_overlay, anchor="nw"
        )

        def sync_overlay_size(event):
            self.dash_canvas.itemconfig(self.dash_window, width=event.width, height=event.height)

        self.dash_canvas.bind("<Configure>", sync_overlay_size, add="+")

        self._build_dashboard_content(self.dash_overlay)

    def _update_aurora_bg(self, w, h):
        try:
            resized = self.aurora_base_image.resize((w, h), Image.Resampling.BILINEAR)
            self.bg_photo = ImageTk.PhotoImage(resized)
            self.dash_canvas.delete("aurora_bg")
            self.dash_canvas.create_image(0, 0, image=self.bg_photo, anchor="nw", tags="aurora_bg")
            self.dash_canvas.tag_lower("aurora_bg")
        except Exception:
            pass

    def _build_dashboard_content(self, container):
        wrap = tk.Frame(container, bg=BASE_BG)
        wrap.pack(fill="both", expand=True, padx=48, pady=36)

        # --- Hero Header ---
        header_frame = tk.Frame(wrap, bg=BASE_BG)
        header_frame.pack(fill="x", pady=(0, 28))

        tk.Label(
            header_frame, text="Welcome to EFL NEXUS", bg=BASE_BG, fg="#0f172a",
            font=("Segoe UI", 24, "bold")
        ).pack(anchor="w")

        tk.Label(
            header_frame,
            text="High-performance automation & variance reconciliation workspace.",
            bg=BASE_BG, fg="#475569", font=("Segoe UI", 11)
        ).pack(anchor="w", pady=(4, 0))

        # --- Tool Cards Row ---
        cards_row = tk.Frame(wrap, bg=BASE_BG)
        cards_row.pack(fill="x", pady=(0, 32))

        # Card 1: Korber Automation
        self._make_aurora_card(
            parent=cards_row,
            icon="🔧",
            badge="QUEUE & AUTO-RETRY",
            badge_color=AURORA_CYAN,
            accent_color=AURORA_CYAN,
            title="Korber Automation",
            desc="Dual-lane automated GDN / GRN creation with persistent browser sessions and auto-recovery.",
            page_key="tool1",
            side_pad=(0, 12)
        ).pack(side="left", fill="both", expand=True)

        # Card 2: Load Reconciliation
        self._make_aurora_card(
            parent=cards_row,
            icon="⚡",
            badge="VARIANCE ANALYTICS",
            badge_color=AURORA_MINT,
            accent_color=AURORA_MINT,
            title="Load Reconciliation",
            desc="Reconcile Loading History against Load Plans, generate variances, and export Excel reports.",
            page_key="tool2",
            side_pad=(0, 12)
        ).pack(side="left", fill="both", expand=True)

        # Card 3: Outlook Email Sender
        self._make_aurora_card(
            parent=cards_row,
            icon="📧",
            badge="DIRECT MAIL ENGINE",
            badge_color=AURORA_SAPPHIRE,
            accent_color=AURORA_SAPPHIRE,
            title="Outlook Email Sender",
            desc="Send batch dispatch emails through native Outlook with dynamic templates and audit logs.",
            page_key="tool3",
            side_pad=(0, 12)
        ).pack(side="left", fill="both", expand=True)

        # Card 4: User KPI
        self._make_aurora_card(
            parent=cards_row,
            icon="👥",
            badge="TASK & METRIC LOGS",
            badge_color=AURORA_AMBER,
            accent_color=AURORA_AMBER,
            title="User KPI",
            desc="Operator task logging, job record management, Google Sheets live sync, and daily KPI tracking.",
            page_key="tool4",
            side_pad=(0, 0)
        ).pack(side="left", fill="both", expand=True)

        # Row 2 cards
        cards_row_two = tk.Frame(wrap, bg=BASE_BG)
        cards_row_two.pack(fill="x", pady=(0, 8))

        # Card 5: Korber AuditShip
        self._make_aurora_card(
            parent=cards_row_two,
            icon="🚚",
            badge="SHIPPING & AUDIT",
            badge_color=AURORA_CYAN,
            accent_color=AURORA_CYAN,
            title="Korber AuditShip",
            desc="Audit outbound loads and complete shipping workflows through the Korber One Mobile portal.",
            page_key="tool5",
            side_pad=(0, 12)
        ).pack(side="left", fill="both", expand=True)

        # Card 6: Pending Jobs
        self._make_aurora_card(
            parent=cards_row_two,
            icon="🔗",
            badge="AUTHORISED WEB EXTRACTION",
            badge_color="#a855f7",
            accent_color="#a855f7",
            title="Pending Jobs",
            desc="Sign in to an authorised portal, open reconciliation, and export every Job ID.",
            page_key="tool6",
            side_pad=(0, 0)
        ).pack(side="left", fill="both", expand=True)

        # --- Bottom Feature Highlights Banner ---
        info_banner = tk.Frame(
            wrap, bg="#ffffff", highlightbackground="#e2e8f0",
            highlightthickness=1, padx=24, pady=20
        )
        info_banner.pack(fill="x", pady=(10, 0))

        tk.Label(
            info_banner, text="PLATFORM CAPABILITIES", bg="#ffffff",
            fg="#94a3b8", font=("Segoe UI", 8, "bold")
        ).pack(anchor="w", pady=(0, 12))

        features_row = tk.Frame(info_banner, bg="#ffffff")
        features_row.pack(fill="x")

        self._make_info_chip(
            features_row, "⚡ Instant Tool Switching",
            "Pre-warmed background modules for zero-delay navigation."
        ).pack(side="left", fill="x", expand=True, padx=(0, 12))

        self._make_info_chip(
            features_row, "🛡 Isolated Dual Lanes",
            "Run bulk jobs in Lane A while priority items execute in Lane B."
        ).pack(side="left", fill="x", expand=True, padx=(0, 12))

        self._make_info_chip(
            features_row, "📊 Automated Variance & Logs",
            "Instant discrepancy calculations, Excel export, and dispatch audit logs."
        ).pack(side="left", fill="x", expand=True)

    def _make_aurora_card(self, parent, icon, badge, badge_color, accent_color, title, desc, page_key, side_pad=(0, 0)):
        card_outer = tk.Frame(
            parent, bg=CARD_BG, highlightbackground=CARD_BORDER,
            highlightthickness=1, cursor="hand2", padx=0, pady=0
        )

        # Top Auroral Accent Bar
        top_bar = tk.Frame(card_outer, bg=accent_color, height=4)
        top_bar.pack(fill="x")

        # Inner Content Box
        inner = tk.Frame(card_outer, bg=CARD_BG, padx=22, pady=20)
        inner.pack(fill="both", expand=True)

        # Header Row: Badge & Icon
        head_row = tk.Frame(inner, bg=CARD_BG)
        head_row.pack(fill="x", pady=(0, 14))

        # Icon Circle
        icon_box = tk.Frame(head_row, bg="#f1f5f9", width=42, height=42)
        icon_box.pack_propagate(False)
        icon_box.pack(side="left")
        tk.Label(
            icon_box, text=icon, bg="#f1f5f9", font=("Segoe UI", 16)
        ).pack(fill="both", expand=True)

        # Feature Badge Pill
        badge_lbl = tk.Label(
            head_row, text=badge, bg="#0d1b2a", fg=badge_color,
            font=("Segoe UI", 7, "bold"), padx=8, pady=4
        )
        badge_lbl.pack(side="right")

        # Title
        title_lbl = tk.Label(
            inner, text=title, bg=CARD_BG, fg=CARD_TEXT_MAIN,
            font=("Segoe UI", 13, "bold"), anchor="w"
        )
        title_lbl.pack(anchor="w", pady=(0, 8))

        # Description
        desc_lbl = tk.Label(
            inner, text=desc, bg=CARD_BG, fg=CARD_TEXT_MUTED,
            font=("Segoe UI", 9), wraplength=260, justify="left", anchor="w"
        )
        desc_lbl.pack(anchor="w", fill="x", expand=True, pady=(0, 18))

        # Action Button Row
        btn_row = tk.Frame(inner, bg=CARD_BG)
        btn_row.pack(fill="x", side="bottom")

        action_btn = tk.Label(
            btn_row, text="Open Tool  →", bg="#0d1b2a", fg="#ffffff",
            font=("Segoe UI", 9, "bold"), padx=14, pady=7, cursor="hand2"
        )
        action_btn.pack(side="left")

        # Hover and Click Interactions
        def on_go(e=None):
            self.show_page(page_key)

        def on_enter(e=None):
            card_outer.config(highlightbackground=accent_color, highlightthickness=2)
            action_btn.config(bg=accent_color, fg="#0b1420")

        def on_leave(e=None):
            card_outer.config(highlightbackground=CARD_BORDER, highlightthickness=1)
            action_btn.config(bg="#0d1b2a", fg="#ffffff")

        # Bind events recursively to all child widgets
        for w in [card_outer, inner, head_row, icon_box, badge_lbl, title_lbl, desc_lbl, btn_row, action_btn]:
            w.bind("<Button-1>", lambda e: on_go())
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

        # Apply side padding via frame packaging
        card_outer.pack_configure(padx=side_pad)
        return card_outer

    def _make_info_chip(self, parent, title, text):
        chip = tk.Frame(parent, bg="#f8fafc", highlightbackground="#e2e8f0", highlightthickness=1, padx=14, pady=12)
        tk.Label(
            chip, text=title, bg="#f8fafc", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), anchor="w"
        ).pack(anchor="w", pady=(0, 3))
        tk.Label(
            chip, text=text, bg="#f8fafc", fg="#64748b",
            font=("Segoe UI", 8), wraplength=220, justify="left", anchor="w"
        ).pack(anchor="w")
        return chip

    # ------------------------------------------------------------------
    # Tool 1 / Tool 2 / Tool 3 Lazy Loading
    # ------------------------------------------------------------------
    def _ensure_tool1(self):
        page = self.pages["tool1"]
        if self.tool1_ready or self.tool1_error is not None:
            return
        try:
            import korber_tool
        except Exception:
            self.tool1_error = traceback.format_exc()
            self._show_tool_error(page, "Tool 1: Korber Automation", self.tool1_error)
            return

        try:
            # Styled Header Banner
            notice = tk.Frame(page, bg="#0d1b2a", padx=16, pady=8)
            notice.pack(fill="x")
            tk.Label(
                notice,
                text="✦  Lane A & Lane B run independently — each creates its own isolated browser session.",
                bg="#0d1b2a", fg=AURORA_CYAN, font=("Segoe UI", 9, "bold"), anchor="w"
            ).pack(side="left")

            notebook = ttk.Notebook(page)
            notebook.pack(fill="both", expand=True)

            lane_a_frame = tk.Frame(notebook, bg=BASE_BG)
            lane_b_frame = tk.Frame(notebook, bg=BASE_BG)
            notebook.add(lane_a_frame, text="  Lane A (Default)  ")
            notebook.add(lane_b_frame, text="  Lane B (Priority)  ")

            self.tool1_lanes["a"] = korber_tool.KorberApp(
                self.root, container=lane_a_frame, standalone=False, profile_name="lane_a"
            )
            self.tool1_lanes["b"] = korber_tool.KorberApp(
                self.root, container=lane_b_frame, standalone=False, profile_name="lane_b"
            )
            self.tool1_ready = True
        except Exception:
            self.tool1_error = traceback.format_exc()
            self.tool1_lanes = {"a": None, "b": None}
            self._show_tool_error(page, "Tool 1: Korber Automation", self.tool1_error)

    def _ensure_tool2(self):
        page = self.pages["tool2"]
        if self.tool2_app is not None or self.tool2_error is not None:
            return
        try:
            import reconciliation_tool
        except Exception:
            self.tool2_error = traceback.format_exc()
            self._show_tool_error(page, "Tool 2: Load Reconciliation", self.tool2_error)
            return

        try:
            self.tool2_app = reconciliation_tool.ReconciliationApp(
                self.root, container=page, standalone=False
            )
            self.tool2_app.on_embedded_exit = lambda: self.show_page("dashboard")
        except Exception:
            self.tool2_error = traceback.format_exc()
            self.tool2_app = None
            self._show_tool_error(page, "Tool 2: Load Reconciliation", self.tool2_error)

    def _ensure_tool3(self):
        page = self.pages["tool3"]
        if self.tool3_app is not None or self.tool3_error is not None:
            return
        try:
            import outlook_email_gui
        except Exception:
            self.tool3_error = traceback.format_exc()
            self._show_tool_error(page, "Tool 3: Outlook Email Sender", self.tool3_error)
            return

        try:
            self.tool3_app = outlook_email_gui.OutlookEmailApp(
                self.root, container=page, standalone=False,
                on_open_settings=lambda: self.show_page("settings")
            )
        except Exception:
            self.tool3_error = traceback.format_exc()
            self.tool3_app = None
            self._show_tool_error(page, "Tool 3: Outlook Email Sender", self.tool3_error)

    def _prewarm_tool4(self):
        """Pre-instantiate Tool 4 during main launcher idle time to eliminate click lag and stutter."""
        if self.tool4_app is None and self.tool4_error is None:
            try:
                self._ensure_tool4()
            except Exception:
                pass

    def _ensure_tool4(self):
        page = self.pages["tool4"]
        if self.tool4_app is not None or self.tool4_error is not None:
            return
        try:
            import KPI
        except Exception:
            self.tool4_error = traceback.format_exc()
            self._show_tool_error(page, "Tool 4: User KPI", self.tool4_error)
            return

        try:
            page.configure(bg=KPI.BG_DARK)
            self.tool4_app = KPI.EFLApp(
                self.root, container=page, standalone=False,
                profile=load_saved_profile(self.config_store.path if self.config_store else None),
                on_open_settings=lambda: self.show_page("settings"),
            )
        except Exception:
            self.tool4_error = traceback.format_exc()
            self.tool4_app = None
            self._show_tool_error(page, "Tool 4: User KPI", self.tool4_error)

    def _ensure_tool6(self):
        page = self.pages["tool6"]
        if self.tool6_app is not None or self.tool6_error is not None:
            return
        try:
            import website_data_grabber
            self.tool6_app = website_data_grabber.WebsiteDataGrabberApp(
                self.root, container=page, standalone=False, config_store=self.config_store,
                on_open_settings=lambda: self.show_page("settings"),
                on_job_started=self._prefill_kpi_for_job,
                on_create_gatepass=self._create_gatepass_for_job,
            )
        except Exception:
            self.tool6_error = traceback.format_exc()
            self.tool6_app = None
            self._show_tool_error(page, "Tool 6: Pending Jobs", self.tool6_error)

    def _create_gatepass_for_job(self, record: dict[str, str]) -> None:
        """Called when Tool 6 'Create Gatepass' button is clicked.

        Routing:
          OUT_* → Fills Korber Automation GDN fields (Warehouse ID, Client Code, Gate Pass No, Delivery Location, Seal No)
          IN_*  → Fills Korber Automation GRN fields (Warehouse ID, Gate Pass No)
        Navigates to Tool 1 (Korber Automation) automatically.
        """
        job_id = str(record.get("job_id", "")).strip()
        upper = job_id.upper()
        if not (upper.startswith("OUT_") or upper.startswith("IN_")):
            messagebox.showwarning("Create Gatepass", f"Job ID '{job_id}' must start with 'OUT_' or 'IN_'.")
            return

        def _do_route():
            self._ensure_tool1()
            lane_a = self.tool1_lanes.get("a") if isinstance(self.tool1_lanes, dict) else None
            if lane_a is None:
                messagebox.showerror("Tool 1 Unavailable", "Korber Automation (Tool 1) could not be loaded.")
                return

            wh = record.get("warehouse", "")
            client = record.get("client", "")
            gp = record.get("gatepass", "")
            deliv = record.get("delivery_location", "")
            seal = record.get("seal", "")

            if upper.startswith("OUT_"):
                deliv_clean = str(deliv or "").strip()
                if not deliv_clean or deliv_clean == "-":
                    deliv_clean = "N/A"
                seal_clean = str(seal or "").strip()
                if not seal_clean or seal_clean == "-":
                    seal_clean = "N/A"
                lane_a.prefill_gdn(
                    warehouse=wh,
                    client=client,
                    gatepass=gp,
                    delivery_location=deliv_clean,
                    seal=seal_clean,
                )
            else:
                lane_a.prefill_grn(
                    warehouse=wh,
                    gatepass=gp,
                )
            self.show_page("tool1")

        self.root.after(0, _do_route)

    def _prefill_kpi_for_job(self, job_id: str) -> None:
        """Called when Tool 6 starts a job — route prefix to the correct KPI section,
        prefill the Job ID entry in User KPI, and navigate there automatically.

        Routing:
          OUT_* → 'GDN Reconciliation:'
          IN_*  → 'GRN Reconciliation:'
          Other → no-op (job still starts, no KPI prefill)
        """
        upper = job_id.upper()
        if upper.startswith("OUT_"):
            section = "GDN Reconciliation:"
        elif upper.startswith("IN_"):
            section = "GRN Reconciliation:"
        else:
            return  # Unknown prefix — do not prefill

        def _do_prefill():
            # Ensure Tool 4 (User KPI) is instantiated before touching it
            self._ensure_tool4()
            if self.tool4_app is None:
                return
            ok = self.tool4_app.prefill_reconciliation_job(job_id, section)
            if ok:
                self.show_page("tool4")

        # Always run UI mutations on the Tk main thread
        self.root.after(0, _do_prefill)

    def _ensure_tool5(self):
        """Build a launcher page for AuditShip — process starts only when the user clicks the button."""
        if self.tool5_ready:
            return

        page = self.pages["tool5"]
        try:
            page.configure(bg=BASE_BG)

            # Full-page host frame (needed by the embedding helpers)
            self.tool5_host_frame = tk.Frame(page, bg=BASE_BG, highlightthickness=0)
            self.tool5_host_frame.pack(fill="both", expand=True)
            self.tool5_host_frame.bind("<Configure>", self._resize_tool5_window)

            # ── Launcher card ─────────────────────────────────────────────
            card_wrap = tk.Frame(self.tool5_host_frame, bg=BASE_BG)
            card_wrap.place(relx=0.5, rely=0.42, anchor="center")

            card = tk.Frame(
                card_wrap, bg="#ffffff",
                highlightbackground="#e2e8f0", highlightthickness=1,
                padx=36, pady=28
            )
            card.pack()

            # Icon
            tk.Label(card, text="🚚", bg="#ffffff", font=("Segoe UI Emoji", 32)).pack()

            # Title
            tk.Label(
                card, text="Korber AuditShip",
                bg="#ffffff", fg="#0f172a",
                font=("Segoe UI", 16, "bold")
            ).pack(pady=(10, 4))

            # Subtitle
            tk.Label(
                card,
                text="Audit outbound loads and complete shipping workflows\nthrough the Korber One Mobile portal.",
                bg="#ffffff", fg="#64748b",
                font=("Segoe UI", 9),
                justify="center"
            ).pack(pady=(0, 20))

            # Open AuditShip button
            self.tool5_launch_button = tk.Button(
                card,
                text="  Open AuditShip  ",
                bg=SIDEBAR_BG_ACTIVE,
                fg="#ffffff",
                activebackground="#1e3a5f",
                activeforeground="#ffffff",
                relief="flat",
                font=("Segoe UI", 10, "bold"),
                cursor="hand2",
                padx=20, pady=8,
                command=self._on_tool5_open_clicked
            )
            self.tool5_launch_button.pack()

            self.tool5_ready = True
            self._hide_loading_overlay()

        except Exception:
            self.tool5_error = traceback.format_exc()
            self.tool5_ready = False
            self._hide_loading_overlay()
            self._show_tool_error(page, "Tool 5: Korber AuditShip", self.tool5_error)

    def _on_tool5_open_clicked(self):
        """Called when the user clicks 'Open AuditShip'. Replaces the launcher card with the embedded window."""
        # Hide the launcher card and show the loading overlay
        if self.tool5_launch_button:
            try:
                self.tool5_launch_button.master.master.destroy()  # destroy card_wrap
            except Exception:
                pass
        self._show_tool5_loading()
        self.root.after(100, self._launch_tool5)


    def _auditship_executable(self):
        if getattr(sys, "frozen", False):
            installed_exe = Path(sys.executable).parent / AUDITSHIP_RELATIVE_PATH
            if installed_exe.is_file():
                return installed_exe
        return Path(get_resource_path(AUDITSHIP_RELATIVE_PATH))

    def _launch_tool5(self):
        """Launch AuditShip hidden and attach it to the Tool 5 host."""
        if self.tool5_process is not None and self.tool5_process.poll() is None:
            self._focus_tool5_window()
            return

        exe_path = self._auditship_executable()
        if not exe_path.is_file():
            self._show_tool5_error(
                "Korber AuditShip is unavailable",
                "The bundled AuditShip executable was not found. Rebuild or reinstall "
                "EFL NEXUS with the Korber_AuditShip folder included."
            )
            return

        try:
            if sys.platform != "win32":
                raise RuntimeError("Embedded AuditShip hosting is supported on Windows only.")

            self.tool5_hwnd = None
            self._show_tool5_loading()
            child_env = os.environ.copy()
            # AuditShip is a separate PyInstaller application. This prevents it
            # from inheriting EFL NEXUS's frozen-runtime state.
            child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            if self.config_store:
                as_user = self.config_store.get_auditship_user()
                as_pass = self.config_store.get_auditship_pass()
                as_fork = self.config_store.get_auditship_fork_id()
                if as_user:
                    child_env["AUDITSHIP_USER"] = as_user
                if as_pass:
                    child_env["AUDITSHIP_PASS"] = as_pass
                if as_fork:
                    child_env["AUDITSHIP_FORK_ID"] = as_fork
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = 0  # SW_HIDE until attached to the host
            self.tool5_process = subprocess.Popen(
                [str(exe_path)], cwd=str(exe_path.parent), env=child_env,
                startupinfo=startup_info
            )
            process = self.tool5_process
            # Delay the first poll past AuditShip's built-in
            # `app.after(100, open_app_maximized)` → state('zoomed') callback
            # so we embed a window that has already settled into its maximized
            # state rather than racing against it.
            self.root.after(350, lambda p=process: self._poll_tool5_window(p, 0))
            self._poll_tool5_process(process)
        except Exception as exc:
            self.tool5_process = None
            self._show_tool5_error(
                "AuditShip could not start",
                f"EFL NEXUS could not embed AuditShip. {exc}"
            )

    @staticmethod
    def _find_window_for_process(process_id):
        """Return the largest unowned top-level HWND for a PID."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.EnumWindows.argtypes = [
            ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
            wintypes.LPARAM,
        ]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL

        candidates = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def collect_window(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != process_id:
                return True
            if user32.GetWindow(hwnd, 4):  # GW_OWNER
                return True
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
                candidates.append((area, int(hwnd)))
            return True

        user32.EnumWindows(collect_window, 0)
        return max(candidates, default=(0, None))[1]

    def _poll_tool5_window(self, process, attempts=0):
        if process is not self.tool5_process:
            return
        if process.poll() is not None:
            return

        hwnd = self._find_window_for_process(process.pid)
        if hwnd:
            # Tkinter ignores STARTF_USESHOWWINDOW/SW_HIDE because it calls
            # wm_deiconify() during its own startup. Re-hide immediately the
            # moment we find the HWND so it never appears as a separate window.
            try:
                import ctypes
                from ctypes import wintypes
                _u32 = ctypes.WinDLL("user32", use_last_error=True)
                _u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                _u32.ShowWindow.restype = wintypes.BOOL
                _u32.ShowWindow(hwnd, 0)  # SW_HIDE
            except Exception:
                pass
            try:
                self._embed_tool5_window(hwnd)
                return
            except Exception as exc:
                self._fail_tool5_embedding(process, str(exc))
                return

        if attempts >= 200:  # 20 seconds
            self._fail_tool5_embedding(
                process, "The AuditShip window did not become available within 20 seconds."
            )
            return

        self.root.after(
            100, lambda p=process, n=attempts + 1: self._poll_tool5_window(p, n)
        )

    def _embed_tool5_window(self, hwnd):
        import ctypes
        from ctypes import wintypes

        host = self.tool5_host_frame
        if host is None or not host.winfo_exists():
            raise RuntimeError("The AuditShip host frame is unavailable.")
        host.update_idletasks()
        host_hwnd = int(host.winfo_id())

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # Belt-and-suspenders: ensure the window is hidden before any style or
        # parent changes so it never flashes as a separate top-level window.
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.ShowWindow(hwnd, 0)  # SW_HIDE
        user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.SetParent.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        # Apply the child style before SetParent as well. Some CustomTkinter
        # top-level windows reject cross-process parenting while still popup
        # windows, then reassert it after parenting and after startup.
        self._apply_tool5_window_chrome(hwnd)
        ctypes.set_last_error(0)
        user32.SetParent(hwnd, host_hwnd)
        set_parent_error = ctypes.get_last_error()
        actual_parent = int(user32.GetParent(hwnd) or 0)
        if actual_parent != host_hwnd:
            raise OSError(
                set_parent_error,
                "Windows could not attach the AuditShip window "
                f"(window={hwnd}, host={host_hwnd}, actual_parent={actual_parent})",
            )
        self.tool5_hwnd = hwnd
        self._apply_tool5_window_chrome(hwnd)
        self._resize_tool5_window()
        self._hide_tool5_overlay()
        self._set_tool5_window_visibility(self.active_page == "tool5")
        self._start_tool5_watchdog()

        # AuditShip calls app.state("zoomed") shortly after startup. It can
        # restore native chrome, so re-assert child styles after startup too.
        # Gap 2: cover CustomTkinter state("zoomed") callbacks that fire up to ~3 s after startup.
        for delay in (250, 700, 1400, 2500, 4000):
            self.root.after(delay, lambda h=hwnd: self._refresh_tool5_chrome(h))

    def _refresh_tool5_chrome(self, hwnd):
        if hwnd != self.tool5_hwnd or self.tool5_process is None:
            return
        try:
            self._apply_tool5_window_chrome(hwnd)
            self._resize_tool5_window()
        except Exception:
            pass

    @staticmethod
    def _tool5_user32():
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.SetParent.restype = wintypes.HWND
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        return user32

    def _apply_tool5_window_chrome(self, hwnd):
        """Remove top-level decorations from the native child window."""
        import ctypes
        from ctypes import wintypes

        user32 = self._tool5_user32()
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL

        GWL_STYLE = -16
        GWL_EXSTYLE = -20
        SW_RESTORE = 9
        WS_CHILD = 0x40000000
        WS_VISIBLE = 0x10000000
        WS_POPUP = 0x80000000
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_SYSMENU = 0x00080000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        WS_MAXIMIZE = 0x01000000  # set by state('zoomed') — must clear before SetParent
        WS_ICONIC = 0x20000000
        WS_EX_DLGMODALFRAME = 0x00000001
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_WINDOWEDGE = 0x00000100
        WS_EX_CLIENTEDGE = 0x00000200
        WS_EX_STATICEDGE = 0x00020000
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_NOACTIVATE = 0x08000000  # Gap 1: prevent child reasserting taskbar presence
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        # Un-maximize first so Windows doesn't fight our style change.
        # SW_RESTORE has no effect if the window is already normal.
        user32.ShowWindow(hwnd, SW_RESTORE)

        style = user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
        style &= ~(
            WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU |
            WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_MAXIMIZE | WS_ICONIC
        )
        style |= WS_CHILD | WS_VISIBLE
        user32.SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_long(style).value)

        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
        exstyle &= ~(
            WS_EX_DLGMODALFRAME | WS_EX_TOOLWINDOW | WS_EX_WINDOWEDGE |
            WS_EX_CLIENTEDGE | WS_EX_STATICEDGE | WS_EX_APPWINDOW | WS_EX_NOACTIVATE
        )
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ctypes.c_long(exstyle).value)
        user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

    def _start_tool5_watchdog(self):
        if self.tool5_watchdog_running:
            return
        self.tool5_watchdog_running = True
        self.root.after(100, self._maintain_tool5_embedding)
        # SetWinEventHook fires the moment AuditShip calls ShowWindow from its
        # own process, giving us sub-millisecond reaction time vs the 100ms poll.
        self._install_tool5_show_hook()

    def _install_tool5_show_hook(self):
        """Watch for AuditShip's window becoming visible and immediately re-hide it."""
        if getattr(self, '_tool5_hook_handle', None):
            return  # already installed
        try:
            import ctypes
            from ctypes import wintypes

            # EVENT_OBJECT_SHOW (0x8002) fires when ShowWindow makes any object visible.
            EVENT_OBJECT_SHOW = 0x8002
            WINEVENT_OUTOFCONTEXT = 0x0000
            WinEventProcType = ctypes.WINFUNCTYPE(
                None,
                wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
            )

            def _on_show(hook, event, h, id_obj, id_child, thread, ts):
                # Only care about AuditShip's top-level window escaping the embed.
                if not h or h != self.tool5_hwnd:
                    return
                try:
                    u32 = ctypes.WinDLL("user32", use_last_error=True)
                    u32.GetParent.argtypes = [wintypes.HWND]
                    u32.GetParent.restype = wintypes.HWND
                    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                    u32.ShowWindow.restype = wintypes.BOOL
                    host = self.tool5_host_frame
                    if host is None or not host.winfo_exists():
                        return
                    host_hwnd = int(host.winfo_id())
                    if int(u32.GetParent(h) or 0) != host_hwnd:
                        # Window escaped the embed — hide immediately.
                        u32.ShowWindow(h, 0)  # SW_HIDE
                        # Re-embed from the Tk main loop (thread-safe).
                        self.root.after_idle(lambda hh=h: self._force_reembed_tool5(hh))
                except Exception:
                    pass

            proc = WinEventProcType(_on_show)
            self._tool5_winevent_proc = proc  # keep reference so it isn't GC'd

            u32 = ctypes.WinDLL("user32", use_last_error=True)
            u32.SetWinEventHook.restype = wintypes.HANDLE
            u32.SetWinEventHook.argtypes = [
                wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
                WinEventProcType, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            ]
            process = self.tool5_process
            pid = process.pid if process else 0
            handle = u32.SetWinEventHook(
                EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW,
                None, proc, pid, 0, WINEVENT_OUTOFCONTEXT,
            )
            self._tool5_hook_handle = int(handle) if handle else 0
        except Exception:
            self._tool5_hook_handle = 0

    def _teardown_tool5_show_hook(self):
        handle = getattr(self, '_tool5_hook_handle', 0)
        if handle:
            try:
                import ctypes
                from ctypes import wintypes
                u32 = ctypes.WinDLL("user32", use_last_error=True)
                u32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
                u32.UnhookWinEvent.restype = wintypes.BOOL
                u32.UnhookWinEvent(handle)
            except Exception:
                pass
        self._tool5_hook_handle = 0
        self._tool5_winevent_proc = None

    def _force_reembed_tool5(self, hwnd):
        """Re-apply parent + chrome when the show-hook fires on an escaped window."""
        if hwnd != self.tool5_hwnd or self.tool5_process is None:
            return
        try:
            import ctypes
            from ctypes import wintypes
            u32 = self._tool5_user32()
            u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            u32.ShowWindow.restype = wintypes.BOOL
            host = self.tool5_host_frame
            if host is None or not host.winfo_exists():
                return
            host.update_idletasks()
            host_hwnd = int(host.winfo_id())
            u32.ShowWindow(hwnd, 0)  # SW_HIDE
            self._apply_tool5_window_chrome(hwnd)
            u32.SetParent(hwnd, host_hwnd)
            self._resize_tool5_window()
            if self.active_page == "tool5":
                u32.ShowWindow(hwnd, 5)  # SW_SHOW
        except Exception:
            pass

    def _maintain_tool5_embedding(self):
        """Keep the compiled AuditShip UI attached despite its own WM updates."""
        process = self.tool5_process
        hwnd = self.tool5_hwnd
        host = self.tool5_host_frame
        if (
            process is None or process.poll() is not None or not hwnd or host is None
            or not host.winfo_exists()
        ):
            self.tool5_watchdog_running = False
            return

        try:
            import ctypes
            from ctypes import wintypes

            user32 = self._tool5_user32()
            if not user32.IsWindow(hwnd):
                self.tool5_hwnd = None
                self.tool5_watchdog_running = False
                return

            host.update_idletasks()
            host_hwnd = int(host.winfo_id())
            reparented = False
            if int(user32.GetParent(hwnd) or 0) != host_hwnd:
                # CustomTkinter can reapply top-level geometry after startup.
                # Hide immediately so it doesn't flash as a separate window
                # between watchdog cycles, then restore the parent relation.
                user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.ShowWindow.restype = wintypes.BOOL
                user32.ShowWindow(hwnd, 0)  # SW_HIDE before re-parenting
                self._apply_tool5_window_chrome(hwnd)
                user32.SetParent(hwnd, host_hwnd)
                reparented = int(user32.GetParent(hwnd) or 0) == host_hwnd

            GWL_STYLE = -16
            GWL_EXSTYLE = -20
            chrome_style = (
                0x80000000 | 0x00C00000 | 0x00040000 | 0x00080000 |
                0x00020000 | 0x00010000 | 0x01000000  # include WS_MAXIMIZE
            )
            # Gap 4: include WS_EX_NOACTIVATE (0x08000000) in the drift-detection mask.
            chrome_exstyle = 0x00000001 | 0x00000080 | 0x00000100 | 0x00000200 | 0x00020000 | 0x00040000 | 0x08000000
            style = user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
            exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
            if not (style & 0x40000000) or style & chrome_style or exstyle & chrome_exstyle:
                self._apply_tool5_window_chrome(hwnd)

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            bounds_changed = (
                abs(rect.left - host.winfo_rootx()) > 2
                or abs(rect.top - host.winfo_rooty()) > 2
                or abs((rect.right - rect.left) - host.winfo_width()) > 2
                or abs((rect.bottom - rect.top) - host.winfo_height()) > 2
            )
            if bounds_changed:
                self._resize_tool5_window()
            if reparented:
                self._set_tool5_window_visibility(self.active_page == "tool5")
        except Exception:
            pass

        if self.root.winfo_exists():
            self.root.after(100, self._maintain_tool5_embedding)

    def _resize_tool5_window(self, _event=None):
        if not self.tool5_hwnd or not self.tool5_host_frame:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.MoveWindow.argtypes = [
                wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.BOOL,
            ]
            user32.MoveWindow.restype = wintypes.BOOL
            width = max(1, self.tool5_host_frame.winfo_width())
            height = max(1, self.tool5_host_frame.winfo_height())
            user32.MoveWindow(self.tool5_hwnd, 0, 0, width, height, True)
        except Exception:
            pass

    def _set_tool5_window_visibility(self, visible):
        if not self.tool5_hwnd:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            if not user32.IsWindow(self.tool5_hwnd):
                self.tool5_hwnd = None
                return
            user32.ShowWindow(self.tool5_hwnd, 5 if visible else 0)
            if visible:
                self.root.after_idle(lambda h=self.tool5_hwnd: self._refresh_tool5_chrome(h))
        except Exception:
            pass

    def _focus_tool5_window(self):
        if not self.tool5_hwnd:
            return
        try:
            import ctypes
            from ctypes import wintypes
            self._set_tool5_window_visibility(True)
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.SetFocus.argtypes = [wintypes.HWND]
            user32.SetFocus.restype = wintypes.HWND
            user32.SetFocus(self.tool5_hwnd)
        except Exception:
            pass

    def _fail_tool5_embedding(self, process, reason):
        self._teardown_tool5_show_hook()
        if process is self.tool5_process and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass
        if process is self.tool5_process:
            self.tool5_process = None
        self.tool5_hwnd = None
        # Gap 3: reset ready flag so a subsequent retry re-triggers the full load path.
        self.tool5_ready = False
        self._show_tool5_error(
            "AuditShip could not be embedded",
            f"EFL NEXUS could not attach AuditShip. {reason}"
        )

    def _poll_tool5_process(self, process):
        if process is not self.tool5_process:
            return
        if process.poll() is None:
            if self.root.winfo_exists():
                self.root.after(1000, lambda p=process: self._poll_tool5_process(p))
            return

        exit_code = process.returncode
        self.tool5_process = None
        self.tool5_hwnd = None
        # Gap 3: reset ready flag so navigating back to Tool 5 re-triggers the load flow.
        self.tool5_ready = False
        self._teardown_tool5_show_hook()
        detail = "AuditShip was closed." if exit_code == 0 else f"AuditShip stopped unexpectedly (exit code {exit_code})."
        self._show_tool5_error("AuditShip is not running", detail)

    def _show_tool5_loading(self):
        self._destroy_tool5_overlay()
        if self.tool5_host_frame is None or not self.tool5_host_frame.winfo_exists():
            return
        self.tool5_overlay = tk.Frame(self.tool5_host_frame, bg="#F3F6FA")
        self.tool5_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        tk.Label(
            self.tool5_overlay, text="Loading Korber AuditShip…", bg="#F3F6FA",
            fg="#334155", font=("Segoe UI", 12, "bold")
        ).place(relx=0.5, rely=0.46, anchor="center")
        tk.Label(
            self.tool5_overlay, text="Preparing the unified workspace", bg="#F3F6FA",
            fg="#94a3b8", font=("Segoe UI", 9)
        ).place(relx=0.5, rely=0.51, anchor="center")

    def _show_tool5_error(self, title, detail):
        self._destroy_tool5_overlay()
        if self.tool5_host_frame is None or not self.tool5_host_frame.winfo_exists():
            return
        self.tool5_overlay = tk.Frame(self.tool5_host_frame, bg="#F3F6FA")
        self.tool5_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        card = tk.Frame(
            self.tool5_overlay, bg="#ffffff", highlightbackground="#fecaca",
            highlightthickness=1, padx=28, pady=24
        )
        card.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(card, text=title, bg="#ffffff", fg="#b91c1c", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(
            card, text=detail, bg="#ffffff", fg="#64748b", font=("Segoe UI", 9),
            justify="left", wraplength=460
        ).pack(anchor="w", pady=(8, 18))
        self.tool5_launch_button = tk.Button(
            card, text="Retry AuditShip", command=self._launch_tool5,
            bg="#0d1b2a", fg="#ffffff", activebackground="#2563eb",
            activeforeground="#ffffff", relief="flat", bd=0,
            font=("Segoe UI", 9, "bold"), padx=16, pady=8, cursor="hand2"
        )
        self.tool5_launch_button.pack(anchor="w")

    def _hide_tool5_overlay(self):
        self._destroy_tool5_overlay()

    def _destroy_tool5_overlay(self):
        if self.tool5_overlay is not None:
            try:
                self.tool5_overlay.destroy()
            except Exception:
                pass
        self.tool5_overlay = None
        self.tool5_launch_button = None

    def _show_tool_error(self, page, tool_name, error_text):
        for w in page.winfo_children():
            w.destroy()
        wrap = tk.Frame(page, bg=BASE_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=40)

        card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#ef4444", highlightthickness=1, padx=24, pady=24)
        card.pack(fill="both", expand=True)

        tk.Label(
            card, text=f"⚠️  {tool_name} could not start", bg="#ffffff",
            fg="#b91c1c", font=("Segoe UI", 14, "bold")
        ).pack(anchor="w")
        tk.Label(
            card, text="A required dependency or module error occurred. Technical details below:",
            bg="#ffffff", fg="#64748b", font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(6, 12))

        text_box = tk.Text(card, height=14, font=("Consolas", 9), wrap="word", bg="#f8fafc", fg="#0f172a")
        text_box.insert("1.0", error_text)
        text_box.configure(state="disabled")
        text_box.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Settings Page
    # ------------------------------------------------------------------
    def _build_settings_page(self, parent):
        # Scrollable Canvas container for Settings
        canvas = tk.Canvas(parent, bg=BASE_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BASE_BG)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_window, width=e.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mouse wheel support
        def _on_mousewheel(event):
            if self.active_page == "settings":
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        wrap = tk.Frame(scrollable_frame, bg=BASE_BG)
        wrap.pack(fill="both", expand=True, padx=48, pady=36)

        tk.Label(
            wrap, text="Settings & System Status", bg=BASE_BG, fg="#0f172a",
            font=("Segoe UI", 20, "bold")
        ).pack(anchor="w", pady=(0, 20))

        # --- Software Updates Card ---
        update_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        update_card.pack(fill="x", pady=(0, 20))

        top_up = tk.Frame(update_card, bg="#ffffff")
        top_up.pack(fill="x", pady=(0, 8))
        tk.Label(
            top_up, text="SOFTWARE UPDATES", bg="#ffffff", fg="#64748b",
            font=("Segoe UI", 8, "bold")
        ).pack(side="left")

        ver_pill = tk.Label(
            top_up, text=f"v{self.get_current_version()} (Current)", bg="#0d1b2a", fg=AURORA_CYAN,
            font=("Segoe UI", 8, "bold"), padx=8, pady=2
        )
        ver_pill.pack(side="right")
        tk.Label(
            update_card, text="Check for new releases, patch updates, and performance enhancements.",
            bg="#ffffff", fg="#64748b", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(0, 14))

        check_btn = tk.Label(
            update_card, text="🔄  Check for Updates", bg="#0d1b2a", fg="#ffffff",
            font=("Segoe UI", 9, "bold"), padx=16, pady=8, cursor="hand2"
        )
        check_btn.pack(anchor="w")
        check_btn.bind("<Button-1>", lambda e: self.check_for_updates(silent=False))
        check_btn.bind("<Enter>", lambda e: check_btn.config(bg=AURORA_CYAN, fg="#0b1420"))
        check_btn.bind("<Leave>", lambda e: check_btn.config(bg="#0d1b2a", fg="#ffffff"))

        # KPI identity is local to this installation and controls Tool 4.
        kpi_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        kpi_card.pack(fill="x", pady=(0, 20))
        kpi_top = tk.Frame(kpi_card, bg="#ffffff")
        kpi_top.pack(fill="x", pady=(0, 8))
        tk.Label(kpi_top, text="KPI USER PROFILE", bg="#ffffff", fg="#64748b",
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        configured_profile = load_saved_profile(self.config_store.path if self.config_store else None)
        self.kpi_status_pill = tk.Label(
            kpi_top, text="● Configured" if configured_profile else "● Needs Setup",
            bg="#0d1b2a", fg=AURORA_MINT if configured_profile else "#f59e0b",
            font=("Segoe UI", 8, "bold"), padx=8, pady=2,
        )
        self.kpi_status_pill.pack(side="right")
        tk.Label(kpi_card, text="Use your registered User ID and individual User Code for KPI entry and exports.",
                 bg="#ffffff", fg="#64748b", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 14))
        kpi_fields = tk.Frame(kpi_card, bg="#ffffff")
        kpi_fields.pack(fill="x", pady=(0, 14))
        kpi_fields.columnconfigure(1, weight=1)
        for row, (label, key) in enumerate((("User ID:", "kpi_user_id"), ("User Code:", "kpi_user_code"))):
            tk.Label(kpi_fields, text=label, bg="#ffffff", fg="#0f172a",
                     font=("Segoe UI", 9, "bold"), width=16, anchor="w").grid(
                         row=row, column=0, sticky="w", padx=(0, 12), pady=(0, 8))
            entry = ttk.Entry(kpi_fields, font=("Segoe UI", 9))
            entry.insert(0, self.config_store.config.get(key, "") if self.config_store else "")
            entry.grid(row=row, column=1, sticky="ew", pady=(0, 8))
            setattr(self, f"{key}_entry", entry)
        kpi_actions = tk.Frame(kpi_card, bg="#ffffff")
        kpi_actions.pack(fill="x")
        tk.Button(kpi_actions, text="Save KPI Profile", bg="#0d1b2a", fg="#ffffff",
                  font=("Segoe UI", 9, "bold"), padx=16, pady=8,
                  relief="flat", cursor="hand2", command=self._save_kpi_profile).pack(side="left")
        self.kpi_msg_lbl = tk.Label(kpi_actions, text="", bg="#ffffff", fg=AURORA_MINT,
                                    font=("Segoe UI", 9, "bold"))
        self.kpi_msg_lbl.pack(side="left", padx=(14, 0))

        # --- Körber Cloud Authentication Card ---
        korber_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        korber_card.pack(fill="x", pady=(0, 20))

        top_kb = tk.Frame(korber_card, bg="#ffffff")
        top_kb.pack(fill="x", pady=(0, 8))
        tk.Label(
            top_kb, text="KÖRBER CLOUD AUTHENTICATION", bg="#ffffff", fg="#64748b",
            font=("Segoe UI", 8, "bold")
        ).pack(side="left")

        kb_user_init = self.config_store.get_korber_user() if self.config_store else ""
        kb_pass_init = self.config_store.get_korber_pass() if self.config_store else ""
        kb_url_init = self.config_store.get_korber_url() if self.config_store else "https://lopwaprodweb.koerbercloud.com/core/Default.html"

        is_kb_configured = bool(kb_user_init and kb_pass_init)
        kb_status_text = "● Configured" if is_kb_configured else "● Needs Setup"
        kb_status_fg = AURORA_MINT if is_kb_configured else "#f59e0b"

        self.korber_status_pill = tk.Label(
            top_kb, text=kb_status_text, bg="#0d1b2a", fg=kb_status_fg,
            font=("Segoe UI", 8, "bold"), padx=8, pady=2
        )
        self.korber_status_pill.pack(side="right")

        tk.Label(
            korber_card,
            text="Configure your personal Körber Cloud portal credentials. Automation lanes will automatically use these credentials to authenticate.",
            bg="#ffffff", fg="#64748b", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(0, 14))

        # Körber Fields frame
        kb_fields = tk.Frame(korber_card, bg="#ffffff")
        kb_fields.pack(fill="x", pady=(0, 14))
        kb_fields.columnconfigure(1, weight=1)

        # Username
        tk.Label(
            kb_fields, text="User Name:", bg="#ffffff", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), width=16, anchor="w"
        ).grid(row=0, column=0, sticky="w", pady=(0, 8), padx=(0, 12))

        self.korber_user_entry = ttk.Entry(kb_fields, font=("Segoe UI", 9))
        self.korber_user_entry.insert(0, kb_user_init)
        self.korber_user_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        # Password
        tk.Label(
            kb_fields, text="Password:", bg="#ffffff", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), width=16, anchor="w"
        ).grid(row=1, column=0, sticky="w", pady=(0, 8), padx=(0, 12))

        pwd_frame = tk.Frame(kb_fields, bg="#ffffff")
        pwd_frame.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        pwd_frame.columnconfigure(0, weight=1)

        self.korber_pass_entry = ttk.Entry(pwd_frame, font=("Segoe UI", 9), show="•")
        self.korber_pass_entry.insert(0, kb_pass_init)
        self.korber_pass_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.korber_pass_toggle_btn = tk.Label(
            pwd_frame, text="👁 Show", bg="#f1f5f9", fg="#334155",
            font=("Segoe UI", 8, "bold"), padx=10, pady=4, cursor="hand2", bd=1, relief="solid"
        )
        self.korber_pass_toggle_btn.grid(row=0, column=1)
        self.korber_pass_toggle_btn.bind("<Button-1>", lambda e: self._toggle_korber_password_visibility())

        # Portal URL
        tk.Label(
            kb_fields, text="Portal URL:", bg="#ffffff", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), width=16, anchor="w"
        ).grid(row=2, column=0, sticky="w", pady=(0, 4), padx=(0, 12))

        self.korber_url_entry = ttk.Entry(kb_fields, font=("Segoe UI", 9))
        self.korber_url_entry.insert(0, kb_url_init)
        self.korber_url_entry.grid(row=2, column=1, sticky="ew", pady=(0, 4))

        # Körber Button row
        kb_btn_row = tk.Frame(korber_card, bg="#ffffff")
        kb_btn_row.pack(fill="x", pady=(8, 0))

        save_kb_btn = tk.Label(
            kb_btn_row, text="💾  Save Credentials", bg="#0d1b2a", fg="#ffffff",
            font=("Segoe UI", 9, "bold"), padx=16, pady=8, cursor="hand2"
        )
        save_kb_btn.pack(side="left", padx=(0, 10))
        save_kb_btn.bind("<Button-1>", lambda e: self._save_korber_settings())
        save_kb_btn.bind("<Enter>", lambda e: save_kb_btn.config(bg=AURORA_CYAN, fg="#0b1420"))
        save_kb_btn.bind("<Leave>", lambda e: save_kb_btn.config(bg="#0d1b2a", fg="#ffffff"))

        self.korber_msg_lbl = tk.Label(
            kb_btn_row, text="", bg="#ffffff", fg=AURORA_MINT, font=("Segoe UI", 9, "bold")
        )
        self.korber_msg_lbl.pack(side="left", padx=(14, 0))

        # --- AuditShip credentials (separate from Körber Cloud automation) ---
        auditship_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        auditship_card.pack(fill="x", pady=(0, 20))

        auditship_user = self.config_store.get_auditship_user() if self.config_store else ""
        auditship_pass = self.config_store.get_auditship_pass() if self.config_store else ""
        auditship_fork = self.config_store.get_auditship_fork_id() if self.config_store else ""
        auditship_header = tk.Frame(auditship_card, bg="#ffffff")
        auditship_header.pack(fill="x", pady=(0, 8))
        tk.Label(
            auditship_header, text="KORBER AUDITSHIP CREDENTIALS", bg="#ffffff", fg="#64748b",
            font=("Segoe UI", 8, "bold")
        ).pack(side="left")
        self.auditship_status_pill = tk.Label(
            auditship_header,
            text="● Configured" if auditship_user and auditship_pass and auditship_fork else "● Needs Setup",
            bg="#0d1b2a", fg=AURORA_MINT if auditship_user and auditship_pass and auditship_fork else "#f59e0b",
            font=("Segoe UI", 8, "bold"), padx=8, pady=2
        )
        self.auditship_status_pill.pack(side="right")
        tk.Label(
            auditship_card,
            text="Save the username, password, and Fork ID for the Korber AuditShip tool.",
            bg="#ffffff", fg="#64748b", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(0, 14))

        auditship_fields = tk.Frame(auditship_card, bg="#ffffff")
        auditship_fields.pack(fill="x", pady=(0, 14))
        auditship_fields.columnconfigure(1, weight=1)
        tk.Label(
            auditship_fields, text="User Name:", bg="#ffffff", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), width=16, anchor="w"
        ).grid(row=0, column=0, sticky="w", pady=(0, 8), padx=(0, 12))
        self.auditship_user_entry = ttk.Entry(auditship_fields, font=("Segoe UI", 9))
        self.auditship_user_entry.insert(0, auditship_user)
        self.auditship_user_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        tk.Label(
            auditship_fields, text="Password:", bg="#ffffff", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), width=16, anchor="w"
        ).grid(row=1, column=0, sticky="w", pady=(0, 8), padx=(0, 12))
        auditship_password_row = tk.Frame(auditship_fields, bg="#ffffff")
        auditship_password_row.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        auditship_password_row.columnconfigure(0, weight=1)
        self.auditship_pass_entry = ttk.Entry(auditship_password_row, font=("Segoe UI", 9), show="•")
        self.auditship_pass_entry.insert(0, auditship_pass)
        self.auditship_pass_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.auditship_pass_toggle_btn = tk.Label(
            auditship_password_row, text="👁 Show", bg="#f1f5f9", fg="#334155",
            font=("Segoe UI", 8, "bold"), padx=10, pady=4, cursor="hand2", bd=1, relief="solid"
        )
        self.auditship_pass_toggle_btn.grid(row=0, column=1)
        self.auditship_pass_toggle_btn.bind("<Button-1>", lambda e: self._toggle_auditship_password_visibility())

        tk.Label(
            auditship_fields, text="Fork ID:", bg="#ffffff", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), width=16, anchor="w"
        ).grid(row=2, column=0, sticky="w", pady=(0, 8), padx=(0, 12))
        self.auditship_fork_entry = ttk.Entry(auditship_fields, font=("Segoe UI", 9))
        self.auditship_fork_entry.insert(0, auditship_fork)
        self.auditship_fork_entry.grid(row=2, column=1, sticky="ew", pady=(0, 8))

        auditship_button_row = tk.Frame(auditship_card, bg="#ffffff")
        auditship_button_row.pack(fill="x", pady=(8, 0))
        save_auditship_btn = tk.Label(
            auditship_button_row, text="💾  Save Credentials", bg="#0d1b2a", fg="#ffffff",
            font=("Segoe UI", 9, "bold"), padx=16, pady=8, cursor="hand2"
        )
        save_auditship_btn.pack(side="left", padx=(0, 10))
        save_auditship_btn.bind("<Button-1>", lambda e: self._save_auditship_settings())
        save_auditship_btn.bind("<Enter>", lambda e: save_auditship_btn.config(bg=AURORA_CYAN, fg="#0b1420"))
        save_auditship_btn.bind("<Leave>", lambda e: save_auditship_btn.config(bg="#0d1b2a", fg="#ffffff"))
        self.auditship_msg_lbl = tk.Label(
            auditship_button_row, text="", bg="#ffffff", fg=AURORA_MINT,
            font=("Segoe UI", 9, "bold")
        )
        self.auditship_msg_lbl.pack(side="left", padx=(14, 0))

        # --- Pending Jobs credentials ---
        grabber_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        grabber_card.pack(fill="x", pady=(0, 20))
        grabber_settings = self.config_store.config if self.config_store else {}
        grabber_login_url = grabber_settings.get("data_grabber_login_url", "https://active.efl3plofc.com/login")
        grabber_user = grabber_settings.get("data_grabber_user", "")
        try:
            from website_data_grabber import _load_saved_password
            grabber_password = _load_saved_password()
        except Exception:
            grabber_password = ""
        grabber_header = tk.Frame(grabber_card, bg="#ffffff")
        grabber_header.pack(fill="x", pady=(0, 8))
        tk.Label(grabber_header, text="PENDING JOBS", bg="#ffffff", fg="#64748b",
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        self.grabber_status_pill = tk.Label(
            grabber_header,
            text="● Configured" if grabber_user and grabber_password else "● Needs Setup",
            bg="#0d1b2a", fg=AURORA_MINT if grabber_user and grabber_password else "#f59e0b",
            font=("Segoe UI", 8, "bold"), padx=8, pady=2,
        )
        self.grabber_status_pill.pack(side="right")
        tk.Label(
            grabber_card,
            text="Configure Tool 6 login and reconciliation routes. The password is saved in Windows Credential Manager, not config.json.",
            bg="#ffffff", fg="#64748b", font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 14))
        grabber_fields = tk.Frame(grabber_card, bg="#ffffff")
        grabber_fields.pack(fill="x", pady=(0, 14))
        grabber_fields.columnconfigure(1, weight=1)
        for row, label in enumerate(("Login URL:", "Username / Email:", "Password:", "Reconciliation URL:", "Auto-Refresh (seconds):", "Sound Notification:", "Sound File:")):
            tk.Label(grabber_fields, text=label, bg="#ffffff", fg="#0f172a",
                     font=("Segoe UI", 9, "bold"), width=18, anchor="w").grid(
                          row=row, column=0, sticky="w", pady=(0, 8), padx=(0, 12))
        self.grabber_login_url_entry = ttk.Entry(grabber_fields, font=("Segoe UI", 9))
        self.grabber_login_url_entry.insert(0, grabber_login_url)
        self.grabber_login_url_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.grabber_user_entry = ttk.Entry(grabber_fields, font=("Segoe UI", 9))
        self.grabber_user_entry.insert(0, grabber_user)
        self.grabber_user_entry.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        grabber_password_row = tk.Frame(grabber_fields, bg="#ffffff")
        grabber_password_row.grid(row=2, column=1, sticky="ew", pady=(0, 8))
        grabber_password_row.columnconfigure(0, weight=1)
        self.grabber_pass_entry = ttk.Entry(grabber_password_row, font=("Segoe UI", 9), show="•")
        self.grabber_pass_entry.insert(0, grabber_password)
        self.grabber_pass_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.grabber_pass_toggle_btn = tk.Label(grabber_password_row, text="👁 Show", bg="#f1f5f9", fg="#334155",
                                                font=("Segoe UI", 8, "bold"), padx=10, pady=4, cursor="hand2", bd=1, relief="solid")
        self.grabber_pass_toggle_btn.grid(row=0, column=1)
        self.grabber_pass_toggle_btn.bind("<Button-1>", lambda e: self._toggle_grabber_password_visibility())
        self.grabber_reconciliation_url_entry = ttk.Entry(grabber_fields, font=("Segoe UI", 9))
        self.grabber_reconciliation_url_entry.insert(0, grabber_settings.get("data_grabber_reconciliation_url", "https://active.efl3plofc.com/clerk-dashboard?job_type=OUTBOUND"))
        self.grabber_reconciliation_url_entry.grid(row=3, column=1, sticky="ew", pady=(0, 8))
        self.grabber_refresh_seconds_entry = ttk.Entry(grabber_fields, font=("Segoe UI", 9))
        self.grabber_refresh_seconds_entry.insert(0, str(grabber_settings.get("data_grabber_refresh_seconds", "5")))
        self.grabber_refresh_seconds_entry.grid(row=4, column=1, sticky="ew", pady=(0, 8))

        # Sound notification toggle
        self.grabber_sound_enabled_var = tk.BooleanVar(value=bool(grabber_settings.get("data_grabber_sound_enabled", True)))
        sound_check_f = tk.Frame(grabber_fields, bg="#ffffff")
        sound_check_f.grid(row=5, column=1, sticky="w", pady=(0, 8))
        tk.Checkbutton(
            sound_check_f,
            text="Play notification sound when new pending jobs are detected",
            variable=self.grabber_sound_enabled_var,
            bg="#ffffff",
            fg="#0f172a",
            font=("Segoe UI", 9),
            activebackground="#ffffff",
        ).pack(side="left")

        # Sound file path + browse + test
        sound_file_row = tk.Frame(grabber_fields, bg="#ffffff")
        sound_file_row.grid(row=6, column=1, sticky="ew", pady=(0, 8))
        sound_file_row.columnconfigure(0, weight=1)
        self.grabber_sound_path_entry = ttk.Entry(sound_file_row, font=("Segoe UI", 9))
        self.grabber_sound_path_entry.insert(0, str(grabber_settings.get("data_grabber_sound_path", "")))
        self.grabber_sound_path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        tk.Button(
            sound_file_row,
            text="Browse...",
            bg="#f1f5f9",
            fg="#0f172a",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._browse_grabber_sound,
        ).grid(row=0, column=1, padx=(0, 4))
        tk.Button(
            sound_file_row,
            text="🔊 Test Sound",
            bg="#f1f5f9",
            fg="#16a34a",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._test_grabber_sound,
        ).grid(row=0, column=2)
        grabber_actions = tk.Frame(grabber_card, bg="#ffffff")
        grabber_actions.pack(fill="x", pady=(8, 0))
        tk.Button(grabber_actions, text="Save Tool 6 Settings", bg="#0d1b2a", fg="#ffffff",
                  font=("Segoe UI", 9, "bold"), padx=16, pady=8, relief="flat", cursor="hand2",
                  command=self._save_data_grabber_settings).pack(side="left")
        tk.Button(grabber_actions, text="Clear Saved Credentials", bg="#e2e8f0", fg="#0f172a",
                  font=("Segoe UI", 9, "bold"), padx=16, pady=8, relief="flat", cursor="hand2",
                  command=self._clear_data_grabber_credentials).pack(side="left", padx=(8, 0))
        self.grabber_msg_lbl = tk.Label(grabber_actions, text="", bg="#ffffff", fg=AURORA_MINT, font=("Segoe UI", 9, "bold"))
        self.grabber_msg_lbl.pack(side="left", padx=(14, 0))

        # --- Google Sheets & Web App Integration Card ---
        gsheet_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        gsheet_card.pack(fill="x", pady=(0, 20))

        top_gs = tk.Frame(gsheet_card, bg="#ffffff")
        top_gs.pack(fill="x", pady=(0, 8))
        tk.Label(
            top_gs, text="GOOGLE SHEETS & CLOUD SYNC", bg="#ffffff", fg="#64748b",
            font=("Segoe UI", 8, "bold")
        ).pack(side="left")

        is_configured = bool(
            self.config_store and self.config_store.get_webapp_url() and self.config_store.get_sheet_url()
        )
        status_text = "● Configured" if is_configured else "● Needs Setup"
        status_fg = AURORA_MINT if is_configured else "#f59e0b"

        self.gsheet_status_pill = tk.Label(
            top_gs, text=status_text, bg="#0d1b2a", fg=status_fg,
            font=("Segoe UI", 8, "bold"), padx=8, pady=2
        )
        self.gsheet_status_pill.pack(side="right")

        tk.Label(
            gsheet_card,
            text="Configure the Google Apps Script Web App URL and Google Sheet URL for real-time dispatch tracking and records.",
            bg="#ffffff", fg="#64748b", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(0, 14))

        # Fields frame
        fields_frame = tk.Frame(gsheet_card, bg="#ffffff")
        fields_frame.pack(fill="x", pady=(0, 14))
        fields_frame.columnconfigure(1, weight=1)

        # Web App URL
        tk.Label(
            fields_frame, text="Web App URL:", bg="#ffffff", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), width=16, anchor="w"
        ).grid(row=0, column=0, sticky="w", pady=(0, 8), padx=(0, 12))

        self.webapp_entry = ttk.Entry(fields_frame, font=("Segoe UI", 9))
        if self.config_store:
            self.webapp_entry.insert(0, self.config_store.get_webapp_url())
        self.webapp_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        # Sheet URL
        tk.Label(
            fields_frame, text="Google Sheet URL:", bg="#ffffff", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), width=16, anchor="w"
        ).grid(row=1, column=0, sticky="w", pady=(0, 4), padx=(0, 12))

        self.sheet_entry = ttk.Entry(fields_frame, font=("Segoe UI", 9))
        if self.config_store:
            self.sheet_entry.insert(0, self.config_store.get_sheet_url())
        self.sheet_entry.grid(row=1, column=1, sticky="ew", pady=(0, 4))

        # Button row
        btn_row = tk.Frame(gsheet_card, bg="#ffffff")
        btn_row.pack(fill="x", pady=(8, 0))

        save_gs_btn = tk.Label(
            btn_row, text="💾  Save Settings", bg="#0d1b2a", fg="#ffffff",
            font=("Segoe UI", 9, "bold"), padx=16, pady=8, cursor="hand2"
        )
        save_gs_btn.pack(side="left", padx=(0, 10))
        save_gs_btn.bind("<Button-1>", lambda e: self._save_gsheet_settings())
        save_gs_btn.bind("<Enter>", lambda e: save_gs_btn.config(bg=AURORA_CYAN, fg="#0b1420"))
        save_gs_btn.bind("<Leave>", lambda e: save_gs_btn.config(bg="#0d1b2a", fg="#ffffff"))

        open_sheet_btn = tk.Label(
            btn_row, text="📊  View Records Sheet ↗", bg="#e2e8f0", fg="#0f172a",
            font=("Segoe UI", 9, "bold"), padx=16, pady=8, cursor="hand2"
        )
        open_sheet_btn.pack(side="left")
        open_sheet_btn.bind("<Button-1>", lambda e: self._open_google_sheet())
        open_sheet_btn.bind("<Enter>", lambda e: open_sheet_btn.config(bg="#cbd5e1"))
        open_sheet_btn.bind("<Leave>", lambda e: open_sheet_btn.config(bg="#e2e8f0"))

        self.gsheet_msg_lbl = tk.Label(
            btn_row, text="", bg="#ffffff", fg=AURORA_MINT, font=("Segoe UI", 9, "bold")
        )
        self.gsheet_msg_lbl.pack(side="left", padx=(14, 0))

        # --- Storage & Cache Management Card ---
        cache_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        cache_card.pack(fill="x", pady=(0, 20))

        top_cache = tk.Frame(cache_card, bg="#ffffff")
        top_cache.pack(fill="x", pady=(0, 8))
        tk.Label(
            top_cache, text="STORAGE & CACHE MANAGEMENT", bg="#ffffff", fg="#64748b",
            font=("Segoe UI", 8, "bold")
        ).pack(side="left")

        tk.Label(
            cache_card, text="Clear stored browser profiles, session locks, driver binaries, and saved templates.",
            bg="#ffffff", fg="#64748b", font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(0, 14))

        clear_cache_btn = tk.Label(
            cache_card, text="🗑️  Clear Cache & Saved Data...", bg="#0d1b2a", fg="#ffffff",
            font=("Segoe UI", 9, "bold"), padx=16, pady=8, cursor="hand2"
        )
        clear_cache_btn.pack(anchor="w")
        clear_cache_btn.bind("<Button-1>", lambda e: self.open_clear_cache_dialog())
        clear_cache_btn.bind("<Enter>", lambda e: clear_cache_btn.config(bg="#dc2626", fg="#ffffff"))
        clear_cache_btn.bind("<Leave>", lambda e: clear_cache_btn.config(bg="#0d1b2a", fg="#ffffff"))

        # --- Diagnostics Card ---
        diag_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        diag_card.pack(fill="x", pady=(0, 20))

        tk.Label(
            diag_card, text="SYSTEM DIAGNOSTICS", bg="#ffffff", fg="#64748b",
            font=("Segoe UI", 8, "bold")
        ).pack(anchor="w", pady=(0, 8))

        diag_grid = tk.Frame(diag_card, bg="#ffffff")
        diag_grid.pack(fill="x")

        self._make_diag_row(diag_grid, "Engine Runtime:", f"Python {sys.version.split()[0]} (64-bit)")
        self._make_diag_row(diag_grid, "Module Warmup:", "Active Daemon Thread")
        _app_dir_disp = str(Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent)
        self._make_diag_row(diag_grid, "App Directory:", _app_dir_disp)

        kb_user_val = self.config_store.get_korber_user() if self.config_store else ""
        kb_pass_val = self.config_store.get_korber_pass() if self.config_store else ""
        kb_diag_status = f"{kb_user_val} (Configured)" if (kb_user_val and kb_pass_val) else ("Needs Setup" if not kb_user_val else "Password Missing")
        self._make_diag_row(diag_grid, "Körber Account:", kb_diag_status)

        sync_status = "Configured" if is_configured else "Unconfigured"
        self._make_diag_row(diag_grid, "Google Cloud Sync:", sync_status)

        # --- About Box ---
        about_card = tk.Frame(wrap, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=24, pady=20)
        about_card.pack(fill="x")

        tk.Label(
            about_card, text="ABOUT EFL NEXUS", bg="#ffffff", fg="#64748b",
            font=("Segoe UI", 8, "bold")
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            about_card,
            text="EFL NEXUS is an enterprise automation suite combining Korber Automation, "
            "Load Reconciliation, and Outlook Email Dispatch into a single unified client.\n\n"
            "For feedback, questions, or bug reports, please refer to the internal repository "
            "or contact the automation engineering team.",
            bg="#ffffff", fg="#334155", font=("Segoe UI", 9), wraplength=800, justify="left"
        ).pack(anchor="w")

    def _toggle_korber_password_visibility(self):
        """Toggles masking on the Körber password entry."""
        if self.korber_pass_entry.cget("show") == "":
            self.korber_pass_entry.config(show="•")
            self.korber_pass_toggle_btn.config(text="👁 Show")
        else:
            self.korber_pass_entry.config(show="")
            self.korber_pass_toggle_btn.config(text="🔒 Hide")

    def _save_korber_settings(self):
        """Saves user-configured Körber credentials to config.json and active runtime."""
        user = self.korber_user_entry.get().strip()
        pwd = self.korber_pass_entry.get().strip()
        url = self.korber_url_entry.get().strip() or "https://lopwaprodweb.koerbercloud.com/core/Default.html"

        if not user or not pwd:
            messagebox.showwarning("Incomplete Credentials", "Please enter both User Name and Password for Körber Cloud.")
            return

        if self.config_store:
            self.config_store.save(korber_user=user, korber_pass=pwd, korber_url=url)

        try:
            import korber_login_bot
            korber_login_bot.save_credentials(user, pwd, url)
            korber_login_bot.USERNAME = user
            korber_login_bot.PASSWORD = pwd
            korber_login_bot.KORBER_URL = url
        except Exception:
            pass

        is_configured = bool(user and pwd)
        status_text = "● Configured" if is_configured else "● Needs Setup"
        status_fg = AURORA_MINT if is_configured else "#f59e0b"
        if hasattr(self, 'korber_status_pill') and self.korber_status_pill.winfo_exists():
            self.korber_status_pill.config(text=status_text, fg=status_fg)

        if hasattr(self, 'korber_msg_lbl') and self.korber_msg_lbl.winfo_exists():
            self.korber_msg_lbl.config(text="✓ Credentials saved successfully!", fg=AURORA_MINT)
            self.root.after(3500, lambda: self.korber_msg_lbl.config(text="") if hasattr(self, 'korber_msg_lbl') and self.korber_msg_lbl.winfo_exists() else None)

    def _save_kpi_profile(self):
        try:
            user_id, user_code = validate_profile(
                self.kpi_user_id_entry.get(), self.kpi_user_code_entry.get()
            )
        except ValueError as error:
            self.kpi_msg_lbl.config(text=str(error), fg="#dc2626")
            return False

        if not self.config_store:
            self.kpi_msg_lbl.config(text="Settings store unavailable.", fg="#dc2626")
            return False

        old_config = self.config_store.config.copy()
        if not self.config_store.save(kpi_user_id=user_id, kpi_user_code=user_code):
            self.config_store.config = old_config
            self.kpi_msg_lbl.config(text="Could not save KPI profile. Check file access.", fg="#dc2626")
            return False

        self.kpi_user_id_entry.delete(0, "end")
        self.kpi_user_id_entry.insert(0, user_id)
        self.kpi_status_pill.config(text="● Configured", fg=AURORA_MINT)
        self.kpi_msg_lbl.config(text="KPI profile saved.", fg=AURORA_MINT)
        if self.tool4_app is not None:
            self.tool4_app.set_profile((user_id, user_code))
        return True

    def _toggle_auditship_password_visibility(self):
        if self.auditship_pass_entry.cget("show"):
            self.auditship_pass_entry.config(show="")
            self.auditship_pass_toggle_btn.config(text="🔒 Hide")
        else:
            self.auditship_pass_entry.config(show="•")
            self.auditship_pass_toggle_btn.config(text="👁 Show")

    def _save_auditship_settings(self):
        user = self.auditship_user_entry.get().strip()
        password = self.auditship_pass_entry.get().strip()
        fork_id = self.auditship_fork_entry.get().strip()
        if not user or not password or not fork_id:
            messagebox.showwarning("Incomplete Credentials", "Please enter User Name, Password, and Fork ID for Korber AuditShip.")
            return
        if not self.config_store or not self.config_store.save(auditship_user=user, auditship_pass=password, auditship_fork_id=fork_id):
            messagebox.showerror("Save Failed", "AuditShip credentials could not be saved. Check access to config.json.")
            return
        self.auditship_status_pill.config(text="● Configured", fg=AURORA_MINT)
        self.auditship_msg_lbl.config(text="✓ Credentials saved successfully!", fg=AURORA_MINT)
        self.root.after(
            3500,
            lambda: self.auditship_msg_lbl.config(text="")
            if self.auditship_msg_lbl.winfo_exists() else None
        )

    def _toggle_grabber_password_visibility(self):
        if self.grabber_pass_entry.cget("show"):
            self.grabber_pass_entry.config(show="")
            self.grabber_pass_toggle_btn.config(text="🔒 Hide")
        else:
            self.grabber_pass_entry.config(show="•")
            self.grabber_pass_toggle_btn.config(text="👁 Show")

    def _save_data_grabber_settings(self):
        login_url = self.grabber_login_url_entry.get().strip()
        username = self.grabber_user_entry.get().strip()
        password = self.grabber_pass_entry.get()
        reconciliation_url = self.grabber_reconciliation_url_entry.get().strip()
        refresh_seconds = self.grabber_refresh_seconds_entry.get().strip() if hasattr(self, "grabber_refresh_seconds_entry") else "5"
        sound_enabled = bool(self.grabber_sound_enabled_var.get()) if hasattr(self, "grabber_sound_enabled_var") else True
        sound_path = self.grabber_sound_path_entry.get().strip() if hasattr(self, "grabber_sound_path_entry") else ""
        if not login_url.startswith(("https://", "http://")) or not reconciliation_url.startswith(("https://", "http://")):
            messagebox.showwarning("Invalid URL", "Enter complete https:// login and reconciliation URLs for Tool 6.")
            return
        if not username or not password:
            messagebox.showwarning("Incomplete credentials", "Enter the Tool 6 username/email and password.")
            return
        try:
            from website_data_grabber import _save_password
            _save_password(password, username)
        except Exception as exc:
            messagebox.showerror("Save Failed", f"Tool 6 credentials could not be saved in Windows Credential Manager: {exc}")
            return

        saved_config = False
        if self.config_store:
            try:
                saved_config = bool(self.config_store.save(
                    data_grabber_login_url=login_url,
                    data_grabber_user=username,
                    data_grabber_reconciliation_url=reconciliation_url,
                    data_grabber_refresh_seconds=refresh_seconds,
                    data_grabber_sound_enabled=sound_enabled,
                    data_grabber_sound_path=sound_path,
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
                data["data_grabber_reconciliation_url"] = reconciliation_url
                data["data_grabber_refresh_seconds"] = refresh_seconds
                data["data_grabber_sound_enabled"] = sound_enabled
                data["data_grabber_sound_path"] = sound_path
                cfg_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                saved_config = True
            except Exception as exc:
                print(f"[MainApp] Warning: Could not save Tool 6 connection settings to config.json: {exc}")

        self.grabber_status_pill.config(text="● Configured", fg=AURORA_MINT)
        self.grabber_msg_lbl.config(text="✓ Tool 6 settings saved securely!", fg=AURORA_MINT)
        if self.tool6_app is not None:
            self.tool6_app.set_connection_settings(
                login_url, username, password, reconciliation_url, refresh_seconds, sound_enabled, sound_path
            )
        self.root.after(3500, lambda: self.grabber_msg_lbl.config(text="") if self.grabber_msg_lbl.winfo_exists() else None)

    def _browse_grabber_sound(self):
        filename = filedialog.askopenfilename(
            title="Select Pending Notification Sound",
            filetypes=[("Audio Files", "*.mp3 *.wav *.wma *.ogg"), ("All Files", "*.*")],
        )
        if filename:
            if hasattr(self, "grabber_sound_path_entry"):
                self.grabber_sound_path_entry.delete(0, tk.END)
                self.grabber_sound_path_entry.insert(0, filename)

    def _test_grabber_sound(self):
        try:
            from website_data_grabber import play_notification_sound
            custom_path = self.grabber_sound_path_entry.get().strip() if hasattr(self, "grabber_sound_path_entry") else ""
            play_notification_sound(custom_path or None)
        except Exception as exc:
            messagebox.showwarning("Sound Test", f"Could not play notification sound: {exc}")

    def _clear_data_grabber_credentials(self):
        if not messagebox.askyesno("Clear Tool 6 credentials", "Remove the saved Tool 6 username and password from this computer?"):
            return
        try:
            from website_data_grabber import _clear_saved_password
            _clear_saved_password()
            if self.config_store:
                self.config_store.save(data_grabber_user="")
        except Exception as exc:
            messagebox.showerror("Clear Failed", f"Tool 6 credentials could not be removed: {exc}")
            return
        self.grabber_user_entry.delete(0, tk.END)
        self.grabber_pass_entry.delete(0, tk.END)
        self.grabber_status_pill.config(text="● Needs Setup", fg="#f59e0b")
        self.grabber_msg_lbl.config(text="Saved Tool 6 credentials removed.", fg="#64748b")
        if self.tool6_app is not None:
            self.tool6_app.set_connection_settings(
                self.grabber_login_url_entry.get().strip(), "", "", self.grabber_reconciliation_url_entry.get().strip()
            )

    def _save_gsheet_settings(self):
        webapp_url = self.webapp_entry.get().strip()
        sheet_url = self.sheet_entry.get().strip()

        if self.config_store:
            self.config_store.save(webapp_url, sheet_url)

        # Update live Tool 3 instance if active
        if self.tool3_app is not None and hasattr(self.tool3_app, "config_store"):
            try:
                self.tool3_app.config_store.config = self.config_store.load()
                self.tool3_app._refresh_counts_label()
            except Exception:
                pass

        is_configured = bool(webapp_url and sheet_url)
        status_text = "● Configured" if is_configured else "● Needs Setup"
        status_fg = AURORA_MINT if is_configured else "#f59e0b"
        if hasattr(self, 'gsheet_status_pill') and self.gsheet_status_pill.winfo_exists():
            self.gsheet_status_pill.config(text=status_text, fg=status_fg)

        if hasattr(self, 'gsheet_msg_lbl') and self.gsheet_msg_lbl.winfo_exists():
            self.gsheet_msg_lbl.config(text="✓ Settings saved successfully!", fg=AURORA_MINT)
            self.root.after(3500, lambda: self.gsheet_msg_lbl.config(text="") if hasattr(self, 'gsheet_msg_lbl') and self.gsheet_msg_lbl.winfo_exists() else None)

    def _open_google_sheet(self):
        sheet_url = self.sheet_entry.get().strip() if hasattr(self, 'sheet_entry') else ""
        if not sheet_url and self.config_store:
            sheet_url = self.config_store.get_sheet_url()
        if not sheet_url:
            messagebox.showwarning("Missing URL", "Please enter and save your Google Sheet URL first.")
            return

        # Ensure latest date order sync before opening
        try:
            import outlook_email_gui
            if hasattr(outlook_email_gui, 'SentLogStore'):
                store = outlook_email_gui.SentLogStore(self.config_store)
                threading.Thread(target=store.get_counts, daemon=True).start()
        except Exception:
            pass

        try:
            webbrowser.open(sheet_url)
        except Exception as exc:
            messagebox.showerror("Browser Error", f"Could not open browser:\n\n{exc}")

    def _make_diag_row(self, parent, label, value):
        row = tk.Frame(parent, bg="#ffffff", pady=3)
        row.pack(fill="x")
        tk.Label(row, text=label, bg="#ffffff", fg="#64748b", font=("Segoe UI", 9, "bold"), width=18, anchor="w").pack(side="left")
        tk.Label(row, text=value, bg="#ffffff", fg="#0f172a", font=("Segoe UI", 9), anchor="w").pack(side="left")

    def open_clear_cache_dialog(self):
        """Opens the Storage & Cache Management modal dialog."""
        if getattr(sys, 'frozen', False):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).resolve().parent
        ClearCacheDialog(self.root, app_dir=app_dir, on_complete=self._on_cache_cleared)

    def _on_cache_cleared(self):
        """Callback after clearing storage to refresh in-memory state."""
        if self.tool3_app is not None and hasattr(self.tool3_app, '_refresh_template_dropdown'):
            try:
                self.tool3_app._refresh_template_dropdown()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def on_close(self):
        self._stop_network_monitor.set()
        if self.tool2_app is not None:
            try:
                self.tool2_app.save_settings()
            except Exception:
                pass
        if self.tool4_app is not None:
            try:
                self.tool4_app.close()
            except Exception:
                pass
        if self.tool5_process is not None and self.tool5_process.poll() is None:
            try:
                self.tool5_process.terminate()
            except Exception:
                pass
        if self.tool6_app is not None:
            if hasattr(self.tool6_app, "close_browser"):
                try:
                    self.tool6_app.close_browser()
                except Exception:
                    pass
            browser_process = getattr(self.tool6_app, "browser_process", None)
            if browser_process is not None and browser_process.poll() is None:
                try:
                    browser_process.terminate()
                except Exception:
                    pass
        self.root.destroy()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--internal-browser":
        from website_data_grabber import run_internal_browser, DEFAULT_LOGIN_URL
        run_internal_browser(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else DEFAULT_LOGIN_URL)
        raise SystemExit(0)
    try:
        import ctypes
        myappid = 'efl.nexus.app.unified'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()
