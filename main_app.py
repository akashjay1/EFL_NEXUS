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
    ("tool4", "👥", "User Data Manager"),
    ("settings", "⚙", "Settings"),
]


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
        self.root.geometry("1420x920")
        self.root.minsize(1000, 650)
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
        self.tool1_error = None
        self.tool2_error = None
        self.tool3_error = None
        self.tool4_error = None

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

        # Pre-instantiate Tool 4 in idle time so opening User Data Manager is instant without stutter
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
            for mod in ("requests", "korber_tool", "reconciliation_tool", "outlook_email_gui", "efldatamanager"):
                try:
                    __import__(mod)
                except Exception:
                    pass

            # Pre-warm efldatamanager data in background thread
            try:
                import efldatamanager
                if hasattr(efldatamanager, "preload_data"):
                    efldatamanager.preload_data()
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

    def get_current_build(self) -> int:
        """Read the installed hotfix build number from build.txt in app_dir.

        Returns 0 when build.txt is absent (fresh install or pre-hotfix release).
        This number is compared against the highest build number found among
        patch assets on the current GitHub Release.
        """
        if getattr(sys, 'frozen', False):
            build_path = Path(sys.executable).parent / "build.txt"
        else:
            build_path = Path(__file__).resolve().parent / "build.txt"

        if build_path.exists():
            try:
                return int(build_path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass
        return 0

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
        import re as _re
        import requests
        api_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
        current_version = self.get_current_version()
        current_build   = self.get_current_build()

        try:
            headers = {"User-Agent": "EFL-Nexus-Updater"}
            response = requests.get(api_url, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()

            latest_version = data.get("tag_name", "").strip().lstrip("v")

            # ---------------------------------------------------------------
            # Pass 1 — collect assets, categorised by type:
            #   * hotfix_patches : Patch_v<current_ver>_b<N>.zip  (same version)
            #   * upgrade_patch  : Patch_v<latest_ver>_b*.zip     (newer version)
            #   * full_zip       : first non-patch .zip            (full fallback)
            # ---------------------------------------------------------------
            # Regex that matches patch assets for a SPECIFIC version:
            #   EFL_Nexus_Patch_v1.0.5_b3.zip
            hotfix_pat = _re.compile(
                r"EFL_Nexus_Patch_v"
                + _re.escape(current_version)
                + r"_b(\d+)\.zip$",
                _re.IGNORECASE,
            )
            upgrade_patch_pat = _re.compile(
                r"EFL_Nexus_Patch_v[\d.]+_b(\d+)\.zip$",
                _re.IGNORECASE,
            )

            hotfix_patches = []   # list of (build_int, url, size)
            upgrade_patch_url  = None
            upgrade_patch_size = 0
            full_url  = None
            full_size = 0

            for asset in data.get("assets", []):
                name = asset.get("name", "")
                url  = asset.get("browser_download_url", "")
                size = asset.get("size", 0)
                if not name.lower().endswith(".zip"):
                    continue

                hm = hotfix_pat.match(name)
                if hm:
                    hotfix_patches.append((int(hm.group(1)), url, size))
                    continue

                if upgrade_patch_pat.match(name):
                    if upgrade_patch_url is None:  # take first upgrade patch
                        upgrade_patch_url  = url
                        upgrade_patch_size = size
                    continue

                # Plain non-patch ZIP — treat as full-release fallback
                if full_url is None:
                    full_url  = url
                    full_size = size

            # ---------------------------------------------------------------
            # Pass 2a — Version upgrade check (existing behaviour)
            # ---------------------------------------------------------------
            try:
                from packaging.version import Version
                is_newer_version = Version(latest_version) > Version(current_version)
            except Exception:
                try:
                    is_newer_version = (
                        tuple(map(int, latest_version.split('.'))) >
                        tuple(map(int, current_version.split('.')))
                    )
                except Exception:
                    is_newer_version = latest_version > current_version

            if is_newer_version:
                # Prefer upgrade patch ZIP over full ZIP for version upgrades
                is_patch      = upgrade_patch_url is not None
                download_url  = upgrade_patch_url  if is_patch else full_url
                download_size = upgrade_patch_size if is_patch else full_size

                if download_url:
                    self.root.after(
                        0,
                        lambda lv=latest_version, cv=current_version,
                               du=download_url, ip=is_patch, ds=download_size:
                            self._prompt_update(lv, cv, du, ip, ds,
                                                is_hotfix=False)
                    )
                elif not silent:
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Update Error",
                            "No .zip asset found in the latest GitHub release."
                        )
                    )
                return  # version upgrade takes priority; skip hotfix check

            # ---------------------------------------------------------------
            # Pass 2b — Same-version hotfix check
            # Only runs when the release version == current installed version.
            # ---------------------------------------------------------------
            if hotfix_patches:
                # Pick the highest build number available on the release
                hotfix_patches.sort(key=lambda t: t[0], reverse=True)
                best_build, best_url, best_size = hotfix_patches[0]

                if best_build > current_build:
                    self.root.after(
                        0,
                        lambda cv=current_version, cb=current_build,
                               bb=best_build, du=best_url, ds=best_size:
                            self._prompt_update(
                                cv, cv, du,
                                is_patch=True,
                                download_size=ds,
                                is_hotfix=True,
                                current_build=cb,
                                new_build=bb,
                            )
                    )
                    return

            # No update of any kind
            if not silent:
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Up to Date",
                        f"You are running the latest version\n"
                        f"v{current_version}  build {current_build}."
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

    def _prompt_update(self, latest_version, current_version, download_url,
                        is_patch=False, download_size=0,
                        is_hotfix=False, current_build=0, new_build=0):
        """Prompt the user to install an available update or hotfix.

        Parameters
        ----------
        latest_version : str
            The new version string (without leading 'v').
        current_version : str
            The currently installed version string.
        download_url : str
            Direct URL to the ZIP asset (patch preferred, full as fallback).
        is_patch : bool
            True when *download_url* points to a differential patch ZIP.
        download_size : int
            Reported byte size of the asset (0 when unknown).
        is_hotfix : bool
            True when the version number is unchanged but a higher build is
            available on the same release (same-version hotfix).
        current_build : int
            The locally installed build number (used for hotfix display).
        new_build : int
            The remote build number being offered (used for hotfix display).
        """
        # Build the size hint string
        if download_size > 0:
            size_mb = download_size / (1024 * 1024)
            size_hint = f"{size_mb:.1f} MB"
        else:
            size_hint = "unknown size"

        if is_hotfix:
            title = "Hotfix Available"
            heading = (
                f"A hotfix is available for v{current_version}!\n\n"
                f"Installed : v{current_version}  build {current_build}\n"
                f"Available : v{current_version}  build {new_build}\n\n"
                f"Hotfix patch — {size_hint}\n"
                f"Only changed files will be downloaded (fast).\n\n"
                f"Would you like to install the hotfix now?"
            )
        else:
            update_type = "Patch update" if is_patch else "Full update"
            type_note = (
                "Only changed files will be downloaded (fast)."
                if is_patch else
                "The complete application package will be downloaded."
            )
            title = "Update Available"
            heading = (
                f"A new version (v{latest_version}) is available!\n\n"
                f"Current Version : v{current_version}\n"
                f"New Version     : v{latest_version}\n\n"
                f"{update_type} — {size_hint}\n"
                f"{type_note}\n\n"
                f"Would you like to download and install the update now?"
            )

        if messagebox.askyesno(title, heading):
            if getattr(sys, 'frozen', False):
                app_dir = Path(sys.executable).parent
            else:
                app_dir = Path(__file__).resolve().parent

            updater_exe = app_dir / "updater.exe"

            if not updater_exe.exists():
                messagebox.showerror(
                    "Update Error",
                    "updater.exe was not found in the application directory."
                )
                return

            cmd = [
                str(updater_exe),
                "--url", download_url,
                "--version", latest_version,
                "--pid", str(os.getpid()),
                "--appdir", str(app_dir),
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

        if key == "tool1":
            self._ensure_tool1()
        elif key == "tool2":
            self._ensure_tool2()
        elif key == "tool3":
            self._ensure_tool3()
        elif key == "tool4":
            self._ensure_tool4()

        self.pages[key].tkraise()

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

        # Card 4: User Data Manager
        self._make_aurora_card(
            parent=cards_row,
            icon="👥",
            badge="TASK & METRIC LOGS",
            badge_color=AURORA_AMBER,
            accent_color=AURORA_AMBER,
            title="User Data Manager",
            desc="Operator task logging, job record management, Google Sheets live sync, and daily KPI tracking.",
            page_key="tool4",
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
            import efldatamanager
        except Exception:
            self.tool4_error = traceback.format_exc()
            self._show_tool_error(page, "Tool 4: User Data Manager", self.tool4_error)
            return

        try:
            page.configure(bg="#060d17")
            self.tool4_app = efldatamanager.EFLApp(
                self.root, container=page, standalone=False
            )
        except Exception:
            self.tool4_error = traceback.format_exc()
            self.tool4_app = None
            self._show_tool_error(page, "Tool 4: User Data Manager", self.tool4_error)

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
                self.tool4_app.close_popup_safely()
                self.tool4_app.cancel_all_timers()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    try:
        import ctypes
        myappid = 'efl.nexus.app.unified'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()
