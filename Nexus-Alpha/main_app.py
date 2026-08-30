"""
EFL NEXUS - unified launcher for the Korber Automation tool, the Load
Reconciliation tool, and the Outlook Email Sender tool, behind one
sidebar-navigated window.

RUN:
    python main_app.py

Requires korber_tool.py, reconciliation_tool.py, and outlook_email_gui.py
(and, for Tool 1, korber_login_bot.py + selenium; for Tool 3, pywin32 +
openpyxl) to sit alongside this file.
"""

import os
import sys
import threading
import subprocess
import traceback
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# GitHub Repository Configuration (Replace with your repository details)
# ---------------------------------------------------------------------------
GITHUB_USER = "akashjay1"
GITHUB_REPO = "EFL_NEXUS"

# ---------------------------------------------------------------------------
# Palette / layout constants for the shell chrome (sidebar, dashboard, etc).
# The two tools keep their own internal theming; this only styles the parts
# that belong to the shell itself.
# ---------------------------------------------------------------------------
SIDEBAR_BG = "#152438"
SIDEBAR_BG_HOVER = "#20334c"
SIDEBAR_BG_ACTIVE = "#1c3f60"
SIDEBAR_FG = "#cbd5e1"
SIDEBAR_FG_ACTIVE = "#ffffff"
SIDEBAR_BORDER = "#0d1826"
CONTENT_BG = "#f4f6f8"
BRAND_ACCENT = "#1c3f60"

SIDEBAR_WIDTH_EXPANDED = 210
SIDEBAR_WIDTH_COLLAPSED = 56

NAV_ITEMS = [
    ("dashboard", "🏠", "Dashboard"),
    ("tool1", "🔧", "Tool 1: Korber Automation"),
    ("tool2", "⚡", "Tool 2: Load Reconciliation"),
    ("tool3", "📧", "Tool 3: Outlook Email Sender"),
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


class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EFL NEXUS")
        self.root.geometry("1400x900")
        self.root.minsize(900, 600)
        self.root.configure(bg=CONTENT_BG)

        # Set window / taskbar icon
        for icon_name in ("favicon.ico", "icon.ico"):
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

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Lazily-created tool instances
        self.tool1_lanes = {"a": None, "b": None}
        self.tool1_ready = False
        self.tool2_app = None
        self.tool3_app = None
        self.tool1_error = None
        self.tool2_error = None
        self.tool3_error = None

        self.sidebar_collapsed = False
        self.active_page = None
        self.nav_buttons = {}  # key -> {"frame":..., "icon":..., "label":...}

        self._build_layout()
        self._build_sidebar()
        self._build_pages()

        self.show_page("dashboard")

        # Warm up heavy tool modules in the background right after startup
        # so when the user clicks any tool, it opens instantaneously.
        self.root.after(150, self._start_background_warmup)

        # Silent update check 2 seconds after startup (runs in background thread)
        self.root.after(2000, lambda: self.check_for_updates(silent=True))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------
    # Background Module Warmup
    # ------------------------------------------------------------------
    def _start_background_warmup(self):
        """Pre-imports heavy dependencies in a background daemon thread so navigation is instant."""
        def _warmup():
            for mod in ("requests", "korber_tool", "reconciliation_tool", "outlook_email_gui"):
                try:
                    __import__(mod)
                except Exception:
                    pass

        threading.Thread(target=_warmup, daemon=True).start()

    # ------------------------------------------------------------------
    # Update Checker Functions
    # ------------------------------------------------------------------
    def get_current_version(self):
        """Reads the current version from version.txt sitting next to this script."""
        if getattr(sys, 'frozen', False):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).resolve().parent
            
        version_file = app_dir / "version.txt"
        try:
            with open(version_file, "r") as f:
                return f.read().strip()
        except Exception:
            return "1.0.0"

    def check_for_updates(self, silent=False):
        """Asynchronously checks GitHub for updates without freezing the GUI."""
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

        self.sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=SIDEBAR_WIDTH_EXPANDED)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)

        self.content_outer = tk.Frame(self.root, bg=CONTENT_BG)
        self.content_outer.grid(row=0, column=1, sticky="nsew")
        self.content_outer.columnconfigure(0, weight=1)
        self.content_outer.rowconfigure(0, weight=1)

        self.pages = {}

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    def _build_sidebar(self):
        for w in self.sidebar.winfo_children():
            w.destroy()

        # --- Brand row ---
        brand_row = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        brand_row.pack(fill="x", pady=(14, 18), padx=10)

        if not self.sidebar_collapsed:
            tk.Label(
                brand_row, text="EFL NEXUS", bg=SIDEBAR_BG, fg="#ffffff",
                font=("Segoe UI", 13, "bold"), anchor="w"
            ).pack(side="left")
        else:
            tk.Label(
                brand_row, text="EN", bg=SIDEBAR_BG, fg="#ffffff",
                font=("Segoe UI", 13, "bold")
            ).pack()

        # --- Nav items ---
        self.nav_buttons = {}
        for key, icon, label in NAV_ITEMS:
            self.nav_buttons[key] = self._make_nav_button(key, icon, label)

        # --- Spacer ---
        spacer = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        spacer.pack(fill="both", expand=True)

        toggle_row = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        toggle_row.pack(fill="x", pady=(0, 14), padx=10)
        toggle_text = "☰" if self.sidebar_collapsed else "◀  Hide"
        self.toggle_btn = tk.Label(
            toggle_row, text=toggle_text, bg=SIDEBAR_BG, fg=SIDEBAR_FG,
            font=("Segoe UI", 10), cursor="hand2", anchor="w", padx=6, pady=6
        )
        self.toggle_btn.pack(fill="x")
        self.toggle_btn.bind("<Button-1>", lambda e: self.toggle_sidebar())
        self.toggle_btn.bind("<Enter>", lambda e: self.toggle_btn.config(bg=SIDEBAR_BG_HOVER))
        self.toggle_btn.bind("<Leave>", lambda e: self.toggle_btn.config(bg=SIDEBAR_BG))

        self._refresh_nav_highlight()

    def _make_nav_button(self, key, icon, label):
        row = tk.Frame(self.sidebar, bg=SIDEBAR_BG, cursor="hand2")
        row.pack(fill="x", padx=8, pady=2)

        text = icon if self.sidebar_collapsed else f"{icon}   {label}"
        anchor = "center" if self.sidebar_collapsed else "w"
        lbl = tk.Label(
            row, text=text, bg=SIDEBAR_BG, fg=SIDEBAR_FG,
            font=("Segoe UI", 10), anchor=anchor, padx=10, pady=9
        )
        lbl.pack(fill="x")

        def on_click(e, k=key):
            self.show_page(k)

        def on_enter(e):
            if self.active_page != key:
                lbl.config(bg=SIDEBAR_BG_HOVER)
                row.config(bg=SIDEBAR_BG_HOVER)

        def on_leave(e):
            if self.active_page != key:
                lbl.config(bg=SIDEBAR_BG)
                row.config(bg=SIDEBAR_BG)

        for widget in (row, lbl):
            widget.bind("<Button-1>", on_click)
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

        return {"row": row, "label": lbl}

    def _refresh_nav_highlight(self):
        for key, widgets in self.nav_buttons.items():
            active = (key == self.active_page)
            bg = SIDEBAR_BG_ACTIVE if active else SIDEBAR_BG
            fg = SIDEBAR_FG_ACTIVE if active else SIDEBAR_FG
            widgets["row"].config(bg=bg)
            widgets["label"].config(bg=bg, fg=fg)

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        new_w = SIDEBAR_WIDTH_COLLAPSED if self.sidebar_collapsed else SIDEBAR_WIDTH_EXPANDED
        self.sidebar.configure(width=new_w)
        self._build_sidebar()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def _build_pages(self):
        for key, _, _ in NAV_ITEMS:
            frame = tk.Frame(self.content_outer, bg=CONTENT_BG)
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

        self.pages[key].tkraise()

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def _build_dashboard_page(self, parent):
        wrap = tk.Frame(parent, bg=CONTENT_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=40)

        tk.Label(
            wrap, text="Welcome to EFL NEXUS ", bg=CONTENT_BG, fg="#1f2937",
            font=("Segoe UI", 20, "bold")
        ).pack(anchor="w")
        tk.Label(
            wrap, text="Pick a tool from the sidebar, or jump in below.",
            bg=CONTENT_BG, fg="#6b7280", font=("Segoe UI", 11)
        ).pack(anchor="w", pady=(4, 24))

        cards_row = tk.Frame(wrap, bg=CONTENT_BG)
        cards_row.pack(anchor="w")

        self._make_dashboard_card(
            cards_row, "🔧", "Tool 1: Korber Automation",
            "Create GDN / GRN entries in Korber, with a run queue and "
            "auto-retry.", "tool1"
        ).pack(side="left", padx=(0, 20))

        self._make_dashboard_card(
            cards_row, "⚡", "Tool 2: Load Reconciliation",
            "Reconcile Loading History against Load Plan and export a "
            "formatted variance report.", "tool2"
        ).pack(side="left")

        self._make_dashboard_card(
            cards_row, "📧", "Tool 3: Outlook Email Sender",
            "Send GDN/GRN emails through your real Outlook account, with "
            "recipient templates, attachments, and a send log.", "tool3"
        ).pack(side="left", padx=(20, 0))

    def _make_dashboard_card(self, parent, icon, title, desc, page_key):
        card = tk.Frame(parent, bg="#ffffff", highlightbackground="#e5e7eb",
                         highlightthickness=1, width=320, height=170)
        card.pack_propagate(False)

        tk.Label(card, text=icon, bg="#ffffff", font=("Segoe UI", 22)).pack(
            anchor="w", padx=18, pady=(16, 0)
        )
        tk.Label(
            card, text=title, bg="#ffffff", fg="#1f2937",
            font=("Segoe UI", 12, "bold"), wraplength=280, justify="left"
        ).pack(anchor="w", padx=18, pady=(6, 4))
        tk.Label(
            card, text=desc, bg="#ffffff", fg="#6b7280",
            font=("Segoe UI", 9), wraplength=280, justify="left"
        ).pack(anchor="w", padx=18)

        open_btn = tk.Label(
            card, text="Open  →", bg="#ffffff", fg=BRAND_ACCENT,
            font=("Segoe UI", 9, "bold"), cursor="hand2"
        )
        open_btn.pack(anchor="w", padx=18, pady=(10, 0))

        def go(e=None, k=page_key):
            self.show_page(k)

        for w in (card, open_btn):
            w.bind("<Button-1>", go)
        card.configure(cursor="hand2")

        return card

    # ------------------------------------------------------------------
    # Tool 1 / Tool 2 Lazy Loading
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
            notice = tk.Label(
                page,
                text="Lane A and Lane B run fully independently -- each opens "
                "its own browser/login. Use Lane B for jobs that need to jump "
                "ahead instead of waiting behind Lane A's queue.",
                bg="#eef2f7", fg="#374151", font=("Segoe UI", 9),
                anchor="w", padx=12, pady=6
            )
            notice.pack(fill="x")

            notebook = ttk.Notebook(page)
            notebook.pack(fill="both", expand=True)

            lane_a_frame = tk.Frame(notebook, bg="#f4f6f8")
            lane_b_frame = tk.Frame(notebook, bg="#f4f6f8")
            notebook.add(lane_a_frame, text="Lane A")
            notebook.add(lane_b_frame, text="Lane B  (Priority)")

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
                self.root, container=page, standalone=False
            )
        except Exception:
            self.tool3_error = traceback.format_exc()
            self.tool3_app = None
            self._show_tool_error(page, "Tool 3: Outlook Email Sender", self.tool3_error)

    def _show_tool_error(self, page, tool_name, error_text):
        for w in page.winfo_children():
            w.destroy()
        wrap = tk.Frame(page, bg=CONTENT_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=40)
        tk.Label(
            wrap, text=f"⚠️  {tool_name} couldn't start", bg=CONTENT_BG,
            fg="#b3392c", font=("Segoe UI", 14, "bold")
        ).pack(anchor="w")
        tk.Label(
            wrap, text="This is usually a missing dependency (e.g. selenium, "
            "pandas, openpyxl) or a missing helper module. Details:",
            bg=CONTENT_BG, fg="#6b7280", font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(6, 10))

        text_box = tk.Text(wrap, height=14, font=("Consolas", 9), wrap="word")
        text_box.insert("1.0", error_text)
        text_box.configure(state="disabled")
        text_box.pack(fill="both", expand=True)



    # ------------------------------------------------------------------
    # Settings Page
    # ------------------------------------------------------------------
    def _build_settings_page(self, parent):
        wrap = tk.Frame(parent, bg=CONTENT_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=40)

        tk.Label(
            wrap, text="Settings", bg=CONTENT_BG, fg="#1f2937",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 20))

        # --- Software Updates Frame ---
        update_box = ttk.LabelFrame(wrap, text="Software Updates", padding=16)
        update_box.pack(fill="x", pady=(0, 16))

        tk.Label(
            update_box,
            text=f"Current Version: v{self.get_current_version()}",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            update_box,
            text="Check GitHub Releases for new updates and application fixes.",
            font=("Segoe UI", 9), foreground="#6b7280"
        ).pack(anchor="w", pady=(0, 10))

        ttk.Button(
            update_box,
            text="🔄 Check for Updates",
            command=lambda: self.check_for_updates(silent=False)
        ).pack(anchor="w")

        # --- About Box ---
        about_box = ttk.LabelFrame(wrap, text="About EFL NEXUS (Beta)", padding=16)
        about_box.pack(fill="x")
        tk.Label(
            about_box,
            text="EFL NEXUS is currently in its active Beta Testing phase.\n\n"
            "This application unifies the Korber Automation tool, the Load Reconciliation "
            "tool, and the Outlook Email Sender tool behind a single sidebar. As features "
            "and workflows are actively being refined, please report any bugs, edge cases, "
            "or feedback to help improve future releases.",
            font=("Segoe UI", 9), foreground="#6b7280", wraplength=700, justify="left"
        ).pack(anchor="w")

    # ------------------------------------------------------------------
    def on_close(self):
        if self.tool2_app is not None:
            try:
                self.tool2_app.save_settings()
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
