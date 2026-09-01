"""
EFL NEXUS - Modern Installation Wizard
Builds and installs the standalone EFL NEXUS application suite with desktop & start menu shortcuts.
"""

import os
import sys
import shutil
import time
import threading
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# Theme Colors & Palette ('Aurora Borealis' Theme)
# ---------------------------------------------------------------------------
BG_DARK = "#0b1420"
BG_DARK_SIDEBAR = "#08101a"
BG_LIGHT = "#f8fafc"
BG_CARD = "#ffffff"
BORDER_COLOR = "#e2e8f0"
TEXT_MAIN = "#0f172a"
TEXT_MUTED = "#64748b"
ACCENT_CYAN = "#00c8e6"
ACCENT_CYAN_HOVER = "#00e5ff"
ACCENT_SAPPHIRE = "#0284c7"
BTN_PRIMARY_BG = "#0f172a"
BTN_PRIMARY_HOVER = "#1e293b"
BTN_PRIMARY_FG = "#ffffff"

FONT_NAME = "Segoe UI"


def get_bundle_dir():
    """Returns the base directory of the bundled resources (PyInstaller MEIPASS or script folder)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def get_default_install_dir():
    """Default installation directory in LocalAppData\\Programs to avoid requiring admin privileges."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return os.path.join(local_app_data, "Programs", "EFL_NEXUS")
    user_profile = os.environ.get("USERPROFILE", "C:\\")
    return os.path.join(user_profile, "EFL_NEXUS")


def get_desktop_dir():
    user_profile = os.environ.get("USERPROFILE", "")
    desktop = os.path.join(user_profile, "Desktop")
    if os.path.exists(desktop):
        return desktop
    onedrive_desktop = os.path.join(user_profile, "OneDrive", "Desktop")
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    return desktop


def get_start_menu_dir():
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "EFL NEXUS")


def create_windows_shortcut(target_exe, shortcut_path, working_dir, icon_path=None, description="EFL NEXUS"):
    """Creates a Windows .lnk shortcut using WScript.Shell or PowerShell fallback."""
    os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_path))
        shortcut.TargetPath = str(target_exe)
        shortcut.WorkingDirectory = str(working_dir)
        if icon_path and os.path.exists(icon_path):
            shortcut.IconLocation = f"{str(icon_path)},0"
        shortcut.Description = description
        shortcut.save()
        return True
    except Exception:
        pass

    # Fallback using PowerShell
    try:
        icon_arg = f'$Shortcut.IconLocation = "{icon_path},0"' if (icon_path and os.path.exists(icon_path)) else ''
        ps_cmd = f'''
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
        $Shortcut.TargetPath = "{target_exe}"
        $Shortcut.WorkingDirectory = "{working_dir}"
        {icon_arg}
        $Shortcut.Description = "{description}"
        $Shortcut.Save()
        '''
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            check=True
        )
        return True
    except Exception:
        return False


def create_uninstaller_script(install_dir):
    """Generates an uninstaller batch script in the install directory."""
    uninstaller_path = os.path.join(install_dir, "uninstall.bat")
    script_content = r"""@echo off
title EFL NEXUS - Uninstaller
cls
echo ========================================================
echo              EFL NEXUS - Uninstaller
echo ========================================================
echo.
echo This will remove EFL NEXUS and its shortcuts from your computer.
echo.
set /p confirm="Are you sure you want to proceed? (Y/N): "
if /i "%confirm%" neq "y" (
    echo Uninstall cancelled.
    timeout /t 2 >nul
    exit /b
)

echo.
echo Closing any running EFL NEXUS processes...
taskkill /f /im EFL_NEXUS.exe 2>nul
taskkill /f /im updater.exe 2>nul
timeout /t 1 /nobreak >nul

echo Removing Desktop and Start Menu shortcuts...
set "DESK_LNK=%USERPROFILE%\Desktop\EFL NEXUS.lnk"
set "OD_DESK_LNK=%USERPROFILE%\OneDrive\Desktop\EFL NEXUS.lnk"
set "SM_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\EFL NEXUS"

if exist "%DESK_LNK%" del /f /q "%DESK_LNK%" 2>nul
if exist "%OD_DESK_LNK%" del /f /q "%OD_DESK_LNK%" 2>nul
if exist "%SM_DIR%" rd /s /q "%SM_DIR%" 2>nul

echo Removing program files...
cd /d "%TEMP%"
start "" /min cmd /c "timeout /t 2 >nul & rd /s /q \"%~dp0\" 2>nul"

echo.
echo ========================================================
echo   EFL NEXUS has been successfully uninstalled.
echo ========================================================
timeout /t 3 >nul
"""
    try:
        with open(uninstaller_path, "w", encoding="utf-8") as f:
            f.write(script_content)
    except Exception:
        pass


class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Setup - EFL NEXUS")
        self.geometry("640x480")
        self.minsize(620, 460)
        self.configure(bg=BG_LIGHT)

        # Set Icon
        self._set_window_icon()

        # Variables
        self.install_dir_var = tk.StringVar(value=get_default_install_dir())
        self.create_desktop_shortcut_var = tk.BooleanVar(value=True)
        self.create_startmenu_shortcut_var = tk.BooleanVar(value=True)
        self.launch_after_install_var = tk.BooleanVar(value=True)
        self.current_page = 0
        self.installed_exe_path = None

        self._setup_styles()
        self._build_layout()
        self._show_page(0)
        self._center_window()

    def _set_window_icon(self):
        bundle_dir = get_bundle_dir()
        for icon_name in ("icon_2.ico", "icon.ico", "favicon.ico"):
            for candidate in (
                bundle_dir / icon_name,
                bundle_dir / "payload" / icon_name,
                Path(sys.executable).parent / icon_name,
                Path(__file__).parent / icon_name
            ):
                if candidate.exists():
                    try:
                        self.iconbitmap(default=str(candidate))
                        return
                    except Exception:
                        try:
                            self.iconbitmap(str(candidate))
                            return
                        except Exception:
                            pass

    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_reqwidth() or 640
        h = self.winfo_reqheight() or 480
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Wizard.Horizontal.TProgressbar",
            troughcolor="#e2e8f0",
            background=ACCENT_CYAN,
            darkcolor=ACCENT_CYAN,
            lightcolor=ACCENT_CYAN,
            bordercolor="#cbd5e1",
            thickness=14
        )

    def _build_layout(self):
        # Top / Left Brand Sidebar
        self.sidebar = tk.Frame(self, bg=BG_DARK, width=200)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Sidebar Content
        sb_inner = tk.Frame(self.sidebar, bg=BG_DARK, padx=16, pady=24)
        sb_inner.pack(fill="both", expand=True)

        # App Logo Icon / Text
        self._load_sidebar_logo(sb_inner)

        tk.Label(
            sb_inner, text="EFL NEXUS", font=(FONT_NAME, 14, "bold"),
            bg=BG_DARK, fg="#ffffff"
        ).pack(anchor="w", pady=(12, 2))

        tk.Label(
            sb_inner, text="Version 1.0.1", font=(FONT_NAME, 9),
            bg=BG_DARK, fg="#94a3b8"
        ).pack(anchor="w")

        # Step Indicator List
        self.step_labels = []
        steps = ["1. Welcome", "2. Destination", "3. Shortcut Tasks", "4. Ready to Install", "5. Installing", "6. Finish"]
        steps_frame = tk.Frame(sb_inner, bg=BG_DARK)
        steps_frame.pack(anchor="w", fill="x", pady=(36, 0))

        for step in steps:
            lbl = tk.Label(
                steps_frame, text=step, font=(FONT_NAME, 9),
                bg=BG_DARK, fg="#64748b", anchor="w"
            )
            lbl.pack(fill="x", pady=4)
            self.step_labels.append(lbl)

        # Bottom Sidebar Tag
        tk.Label(
            sb_inner, text="Enterprise Suite", font=(FONT_NAME, 8),
            bg=BG_DARK, fg="#475569"
        ).pack(side="bottom", anchor="w")

        # Main Container
        self.main_container = tk.Frame(self, bg=BG_LIGHT)
        self.main_container.pack(side="right", fill="both", expand=True)

        # Content Area
        self.content_frame = tk.Frame(self.main_container, bg=BG_LIGHT, padx=28, pady=24)
        self.content_frame.pack(side="top", fill="both", expand=True)

        # Divider
        divider = tk.Frame(self.main_container, bg=BORDER_COLOR, height=1)
        divider.pack(side="top", fill="x")

        # Bottom Button Bar
        self.button_bar = tk.Frame(self.main_container, bg="#ffffff", padx=20, pady=12)
        self.button_bar.pack(side="bottom", fill="x")

        self.btn_cancel = tk.Button(
            self.button_bar, text="Cancel", font=(FONT_NAME, 9),
            bg="#ffffff", fg=TEXT_MAIN, activebackground="#f1f5f9",
            bd=1, relief="solid", padx=14, pady=4, cursor="hand2",
            command=self._on_cancel
        )
        self.btn_cancel.pack(side="right", padx=(8, 0))

        self.btn_next = tk.Button(
            self.button_bar, text="Next >", font=(FONT_NAME, 9, "bold"),
            bg=BTN_PRIMARY_BG, fg=BTN_PRIMARY_FG, activebackground=BTN_PRIMARY_HOVER,
            activeforeground="#ffffff", bd=0, relief="flat", padx=18, pady=5, cursor="hand2",
            command=self._on_next
        )
        self.btn_next.pack(side="right", padx=(8, 0))

        self.btn_back = tk.Button(
            self.button_bar, text="< Back", font=(FONT_NAME, 9),
            bg="#ffffff", fg=TEXT_MAIN, activebackground="#f1f5f9",
            bd=1, relief="solid", padx=14, pady=4, cursor="hand2",
            command=self._on_back
        )
        self.btn_back.pack(side="right")

    def _load_sidebar_logo(self, parent):
        bundle_dir = get_bundle_dir()
        for icon_name in ("icon_2.ico", "icon.ico", "favicon.ico"):
            for candidate in (
                bundle_dir / icon_name,
                bundle_dir / "payload" / icon_name,
                Path(sys.executable).parent / icon_name,
                Path(__file__).parent / icon_name
            ):
                if candidate.exists():
                    try:
                        img = Image.open(candidate).convert("RGBA")
                        img = img.resize((48, 48), Image.Resampling.LANCZOS)
                        self.sidebar_img = ImageTk.PhotoImage(img)
                        lbl = tk.Label(parent, image=self.sidebar_img, bg=BG_DARK)
                        lbl.pack(anchor="w")
                        return
                    except Exception:
                        pass
        # Fallback circle placeholder
        lbl = tk.Label(parent, text="⚡", font=(FONT_NAME, 24), bg=BG_DARK, fg=ACCENT_CYAN)
        lbl.pack(anchor="w")

    def _update_step_indicator(self, page_index):
        for i, lbl in enumerate(self.step_labels):
            if i == page_index:
                lbl.config(fg=ACCENT_CYAN, font=(FONT_NAME, 9, "bold"))
            elif i < page_index:
                lbl.config(fg="#94a3b8", font=(FONT_NAME, 9))
            else:
                lbl.config(fg="#475569", font=(FONT_NAME, 9))

    def _clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _show_page(self, page_index):
        self.current_page = page_index
        self._update_step_indicator(page_index)
        self._clear_content()

        if page_index == 0:
            self._build_welcome_page()
        elif page_index == 1:
            self._build_destination_page()
        elif page_index == 2:
            self._build_tasks_page()
        elif page_index == 3:
            self._build_ready_page()
        elif page_index == 4:
            self._build_installing_page()
        elif page_index == 5:
            self._build_finish_page()

    # --- Page 0: Welcome ---
    def _build_welcome_page(self):
        self.btn_back.config(state="disabled")
        self.btn_next.config(text="Next >", state="normal")
        self.btn_cancel.config(state="normal")

        tk.Label(
            self.content_frame, text="Welcome to the EFL NEXUS Setup Wizard",
            font=(FONT_NAME, 14, "bold"), bg=BG_LIGHT, fg=TEXT_MAIN, wraplength=400, justify="left"
        ).pack(anchor="w", pady=(0, 12))

        desc_text = (
            "This wizard will install EFL NEXUS on your computer.\n\n"
            "EFL NEXUS is a unified desktop suite featuring:\n"
            "  • Körber Automation Bot (Dual Lane Engine)\n"
            "  • Load Reconciliation & Variance Analyzer\n"
            "  • Automated Outlook Email Dispatch\n"
            "  • Google Cloud Sync Integration\n\n"
            "It is recommended that you close other applications before continuing.\n\n"
            "Click Next to continue, or Cancel to exit Setup."
        )
        tk.Label(
            self.content_frame, text=desc_text, font=(FONT_NAME, 9),
            bg=BG_LIGHT, fg="#334155", justify="left", wraplength=390
        ).pack(anchor="w", pady=(0, 10))

    # --- Page 1: Destination Folder ---
    def _build_destination_page(self):
        self.btn_back.config(state="normal")
        self.btn_next.config(text="Next >", state="normal")

        tk.Label(
            self.content_frame, text="Select Destination Location",
            font=(FONT_NAME, 13, "bold"), bg=BG_LIGHT, fg=TEXT_MAIN
        ).pack(anchor="w")

        tk.Label(
            self.content_frame, text="Where should EFL NEXUS be installed?",
            font=(FONT_NAME, 9), bg=BG_LIGHT, fg=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 14))

        tk.Label(
            self.content_frame, text="Setup will install EFL NEXUS into the following folder:",
            font=(FONT_NAME, 9), bg=BG_LIGHT, fg=TEXT_MAIN
        ).pack(anchor="w", pady=(0, 6))

        # Folder Input Frame
        folder_card = tk.Frame(self.content_frame, bg=BG_CARD, highlightbackground=BORDER_COLOR, highlightthickness=1, padx=12, pady=12)
        folder_card.pack(fill="x", pady=(0, 14))

        entry_frame = tk.Frame(folder_card, bg=BG_CARD)
        entry_frame.pack(fill="x")

        self.dir_entry = tk.Entry(
            entry_frame, textvariable=self.install_dir_var, font=(FONT_NAME, 9),
            bg="#f8fafc", fg=TEXT_MAIN, bd=1, relief="solid"
        )
        self.dir_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))

        browse_btn = tk.Button(
            entry_frame, text="Browse...", font=(FONT_NAME, 9),
            bg="#ffffff", fg=TEXT_MAIN, activebackground="#f1f5f9",
            bd=1, relief="solid", padx=12, pady=3, cursor="hand2",
            command=self._on_browse_dir
        )
        browse_btn.pack(side="right")

        # Space info
        space_frame = tk.Frame(self.content_frame, bg=BG_LIGHT)
        space_frame.pack(fill="x", pady=(8, 0))

        tk.Label(
            space_frame, text="At least 120 MB of free disk space is required.",
            font=(FONT_NAME, 8), bg=BG_LIGHT, fg=TEXT_MUTED
        ).pack(anchor="w")

    def _on_browse_dir(self):
        chosen = filedialog.askdirectory(
            title="Select Installation Folder",
            initialdir=self.install_dir_var.get()
        )
        if chosen:
            # If the user chose a folder that doesn't end with EFL_NEXUS, append it
            chosen_path = Path(chosen)
            if chosen_path.name.lower() != "efl_nexus":
                chosen_path = chosen_path / "EFL_NEXUS"
            self.install_dir_var.set(str(chosen_path))

    # --- Page 2: Tasks & Shortcuts ---
    def _build_tasks_page(self):
        self.btn_back.config(state="normal")
        self.btn_next.config(text="Next >", state="normal")

        tk.Label(
            self.content_frame, text="Select Additional Tasks",
            font=(FONT_NAME, 13, "bold"), bg=BG_LIGHT, fg=TEXT_MAIN
        ).pack(anchor="w")

        tk.Label(
            self.content_frame, text="Which shortcuts should Setup create?",
            font=(FONT_NAME, 9), bg=BG_LIGHT, fg=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 14))

        card = tk.Frame(self.content_frame, bg=BG_CARD, highlightbackground=BORDER_COLOR, highlightthickness=1, padx=16, pady=16)
        card.pack(fill="x", pady=(0, 10))

        tk.Label(
            card, text="Additional shortcuts:", font=(FONT_NAME, 9, "bold"),
            bg=BG_CARD, fg=TEXT_MAIN
        ).pack(anchor="w", pady=(0, 8))

        cb_desktop = tk.Checkbutton(
            card, text="Create a Desktop shortcut", variable=self.create_desktop_shortcut_var,
            font=(FONT_NAME, 9), bg=BG_CARD, activebackground=BG_CARD, fg=TEXT_MAIN, selectcolor="#ffffff"
        )
        cb_desktop.pack(anchor="w", pady=3)

        cb_sm = tk.Checkbutton(
            card, text="Create a Start Menu shortcut", variable=self.create_startmenu_shortcut_var,
            font=(FONT_NAME, 9), bg=BG_CARD, activebackground=BG_CARD, fg=TEXT_MAIN, selectcolor="#ffffff"
        )
        cb_sm.pack(anchor="w", pady=3)

        tip_card = tk.Frame(self.content_frame, bg="#eff6ff", highlightbackground="#bfdbfe", highlightthickness=1, padx=12, pady=10)
        tip_card.pack(fill="x", pady=(10, 0))

        tk.Label(
            tip_card, text="An uninstaller will automatically be created in the application folder.",
            font=(FONT_NAME, 8), bg="#eff6ff", fg="#1e40af"
        ).pack(anchor="w")

    # --- Page 3: Ready to Install ---
    def _build_ready_page(self):
        self.btn_back.config(state="normal")
        self.btn_next.config(text="Install", state="normal")

        tk.Label(
            self.content_frame, text="Ready to Install",
            font=(FONT_NAME, 13, "bold"), bg=BG_LIGHT, fg=TEXT_MAIN
        ).pack(anchor="w")

        tk.Label(
            self.content_frame, text="Setup is now ready to begin installing EFL NEXUS on your computer.",
            font=(FONT_NAME, 9), bg=BG_LIGHT, fg=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 12))

        summary_card = tk.Frame(self.content_frame, bg=BG_CARD, highlightbackground=BORDER_COLOR, highlightthickness=1, padx=16, pady=14)
        summary_card.pack(fill="both", expand=True, pady=(0, 8))

        tk.Label(
            summary_card, text="Destination location:", font=(FONT_NAME, 8, "bold"),
            bg=BG_CARD, fg=TEXT_MUTED
        ).pack(anchor="w")

        tk.Label(
            summary_card, text=self.install_dir_var.get(), font=(FONT_NAME, 9),
            bg=BG_CARD, fg=TEXT_MAIN, wraplength=360, justify="left"
        ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            summary_card, text="Shortcuts:", font=(FONT_NAME, 8, "bold"),
            bg=BG_CARD, fg=TEXT_MUTED
        ).pack(anchor="w")

        sc_items = []
        if self.create_desktop_shortcut_var.get():
            sc_items.append("Desktop shortcut")
        if self.create_startmenu_shortcut_var.get():
            sc_items.append("Start Menu shortcut")
        if not sc_items:
            sc_items.append("None")

        for item in sc_items:
            tk.Label(
                summary_card, text=f"• {item}", font=(FONT_NAME, 9),
                bg=BG_CARD, fg=TEXT_MAIN
            ).pack(anchor="w", padx=4, pady=1)

        tk.Label(
            self.content_frame, text="Click Install to continue with the installation.",
            font=(FONT_NAME, 8), bg=BG_LIGHT, fg=TEXT_MUTED
        ).pack(anchor="w", pady=(6, 0))

    # --- Page 4: Installing ---
    def _build_installing_page(self):
        self.btn_back.config(state="disabled")
        self.btn_next.config(state="disabled")
        self.btn_cancel.config(state="disabled")

        tk.Label(
            self.content_frame, text="Installing EFL NEXUS",
            font=(FONT_NAME, 13, "bold"), bg=BG_LIGHT, fg=TEXT_MAIN
        ).pack(anchor="w")

        tk.Label(
            self.content_frame, text="Please wait while Setup installs EFL NEXUS on your computer...",
            font=(FONT_NAME, 9), bg=BG_LIGHT, fg=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 24))

        self.status_lbl = tk.Label(
            self.content_frame, text="Preparing installation...",
            font=(FONT_NAME, 9), bg=BG_LIGHT, fg=TEXT_MAIN, anchor="w"
        )
        self.status_lbl.pack(fill="x", pady=(0, 6))

        self.progressbar = ttk.Progressbar(
            self.content_frame, style="Wizard.Horizontal.TProgressbar",
            mode="determinate", maximum=100
        )
        self.progressbar.pack(fill="x", pady=(0, 12))

        self.detail_lbl = tk.Label(
            self.content_frame, text="",
            font=(FONT_NAME, 8), bg=BG_LIGHT, fg=TEXT_MUTED, anchor="w"
        )
        self.detail_lbl.pack(fill="x")

        # Launch Installation Thread
        threading.Thread(target=self._run_install_worker, daemon=True).start()

    def _run_install_worker(self):
        install_dir = Path(self.install_dir_var.get())
        bundle_dir = get_bundle_dir()

        try:
            self._update_progress(10, "Creating destination directory...", str(install_dir))
            install_dir.mkdir(parents=True, exist_ok=True)
            time.sleep(0.3)

            # Discover payload source
            dev_root = Path(__file__).resolve().parent
            payload_dir = bundle_dir / "payload" if (bundle_dir / "payload").exists() else bundle_dir

            # Check if directory mode build exists (e.g. payload/EFL_NEXUS or payload with _internal / EFL_NEXUS.exe)
            onedir_source = None
            for cand in [
                payload_dir / "EFL_NEXUS",
                payload_dir,
                bundle_dir / "EFL_NEXUS",
                dev_root / "dist" / "EFL_NEXUS",
            ]:
                if cand.exists() and (cand / "EFL_NEXUS.exe").exists():
                    onedir_source = cand
                    break

            if onedir_source:
                items = [p for p in onedir_source.iterdir() if p.name not in ("__pycache__", "config.json", ".env")]
                total_items = len(items) + 2
                for i, item in enumerate(items):
                    prog = 15 + int(((i + 1) / total_items) * 65)
                    self._update_progress(prog, f"Extracting {item.name}...", f"Deploying {item.name} to destination...")
                    dst = install_dir / item.name
                    if item.is_dir():
                        shutil.copytree(item, dst, dirs_exist_ok=True)
                    else:
                        try:
                            shutil.copy2(item, dst)
                        except Exception:
                            pass
                    time.sleep(0.04)
            else:
                files_to_copy = [
                    ("EFL_NEXUS.exe", [payload_dir / "EFL_NEXUS.exe", dev_root / "dist" / "EFL_NEXUS.exe", dev_root / "EFL_NEXUS.exe"]),
                    ("updater.exe", [payload_dir / "updater.exe", dev_root / "dist" / "updater.exe", dev_root / "dist" / "EFL_NEXUS" / "updater.exe", dev_root / "updater.exe"]),
                    ("icon_2.ico", [payload_dir / "icon_2.ico", dev_root / "icon_2.ico"]),
                    ("icon.ico", [payload_dir / "icon.ico", dev_root / "icon.ico"]),
                    ("version.txt", [payload_dir / "version.txt", dev_root / "version.txt"]),
                    ("aurora_bg.png", [payload_dir / "aurora_bg.png", dev_root / "aurora_bg.png"]),
                    ("templates.xlsx", [payload_dir / "templates.xlsx", dev_root / "templates.xlsx"]),
                    ("variance_templates.xlsx", [payload_dir / "variance_templates.xlsx", dev_root / "variance_templates.xlsx"]),
                ]

                total_items = len(files_to_copy) + 3
                current_item = 0

                for target_name, candidates in files_to_copy:
                    current_item += 1
                    prog = 10 + int((current_item / total_items) * 60)
                    self._update_progress(prog, f"Extracting {target_name}...", f"Copying to {install_dir / target_name}")

                    copied = False
                    for src in candidates:
                        if src.exists() and src.is_file():
                            try:
                                shutil.copy2(src, install_dir / target_name)
                                copied = True
                                break
                            except Exception:
                                pass

                    if not copied and target_name in ("version.txt",):
                        if target_name == "version.txt":
                            (install_dir / "version.txt").write_text(get_app_version(), encoding="utf-8")

                    time.sleep(0.05)

                # Copy assets directory if exists
                self._update_progress(75, "Deploying UI assets...", "Copying assets folder...")
                for assets_src in [payload_dir / "assets", dev_root / "assets"]:
                    if assets_src.exists() and assets_src.is_dir():
                        shutil.copytree(assets_src, install_dir / "assets", dirs_exist_ok=True)
                        break

            # Extra check: ensure templates, version.txt, icons exist in install_dir
            for extra_name in ("templates.xlsx", "variance_templates.xlsx", "version.txt", "icon_2.ico", "icon.ico", "aurora_bg.png"):
                if not (install_dir / extra_name).exists():
                    for cand_extra in [payload_dir / extra_name, dev_root / extra_name]:
                        if cand_extra.exists() and cand_extra.is_file():
                            try:
                                shutil.copy2(cand_extra, install_dir / extra_name)
                            except Exception:
                                pass
                            break

            time.sleep(0.2)

            # Create Shortcuts
            target_exe = install_dir / "EFL_NEXUS.exe"
            self.installed_exe_path = target_exe
            icon_file = install_dir / "icon_2.ico"

            self._update_progress(85, "Creating program shortcuts...", "Setting up desktop and start menu...")

            if self.create_desktop_shortcut_var.get():
                desktop_lnk = Path(get_desktop_dir()) / "EFL NEXUS.lnk"
                create_windows_shortcut(
                    target_exe=target_exe,
                    shortcut_path=desktop_lnk,
                    working_dir=install_dir,
                    icon_path=icon_file if icon_file.exists() else None,
                    description="EFL NEXUS Enterprise Automation Suite"
                )

            if self.create_startmenu_shortcut_var.get():
                sm_dir = Path(get_start_menu_dir())
                sm_dir.mkdir(parents=True, exist_ok=True)
                sm_lnk = sm_dir / "EFL NEXUS.lnk"
                create_windows_shortcut(
                    target_exe=target_exe,
                    shortcut_path=sm_lnk,
                    working_dir=install_dir,
                    icon_path=icon_file if icon_file.exists() else None,
                    description="EFL NEXUS Enterprise Automation Suite"
                )

            # Generate uninstaller
            self._update_progress(95, "Configuring uninstaller...", "Writing uninstall.bat...")
            create_uninstaller_script(str(install_dir))
            time.sleep(0.3)

            self._update_progress(100, "Installation complete!", "Finalizing setup...")
            time.sleep(0.4)

            self.after(0, lambda: self._show_page(5))

        except Exception as e:
            self.after(0, lambda err=e: self._on_install_error(err))

    def _update_progress(self, percent, status_text, detail_text=""):
        self.after(0, lambda: self._set_progress_ui(percent, status_text, detail_text))

    def _set_progress_ui(self, percent, status_text, detail_text):
        self.progressbar["value"] = percent
        self.status_lbl.config(text=status_text)
        self.detail_lbl.config(text=detail_text)

    def _on_install_error(self, err):
        messagebox.showerror(
            "Installation Error",
            f"An error occurred while installing EFL NEXUS:\n\n{err}\n\nPlease check folder permissions and try again."
        )
        self.btn_cancel.config(state="normal")
        self.btn_back.config(state="normal")

    # --- Page 5: Finish ---
    def _build_finish_page(self):
        self.btn_back.config(state="disabled")
        self.btn_cancel.config(state="disabled")
        self.btn_next.config(text="Finish", state="normal", command=self._on_finish)

        tk.Label(
            self.content_frame, text="Completing EFL NEXUS Setup",
            font=(FONT_NAME, 14, "bold"), bg=BG_LIGHT, fg=TEXT_MAIN, wraplength=400, justify="left"
        ).pack(anchor="w", pady=(0, 12))

        finish_text = (
            "Setup has finished installing EFL NEXUS on your computer.\n\n"
            "The application may be launched by selecting the installed shortcuts or from the installation directory.\n\n"
            "Click Finish to exit Setup."
        )
        tk.Label(
            self.content_frame, text=finish_text, font=(FONT_NAME, 9),
            bg=BG_LIGHT, fg="#334155", justify="left", wraplength=390
        ).pack(anchor="w", pady=(0, 16))

        finish_card = tk.Frame(self.content_frame, bg=BG_CARD, highlightbackground=BORDER_COLOR, highlightthickness=1, padx=16, pady=12)
        finish_card.pack(fill="x")

        cb_launch = tk.Checkbutton(
            finish_card, text="Launch EFL NEXUS now", variable=self.launch_after_install_var,
            font=(FONT_NAME, 9, "bold"), bg=BG_CARD, activebackground=BG_CARD, fg=TEXT_MAIN, selectcolor="#ffffff"
        )
        cb_launch.pack(anchor="w")

    def _on_next(self):
        if self.current_page == 1:
            # Validate Destination Directory
            dir_str = self.install_dir_var.get().strip()
            if not dir_str:
                messagebox.showwarning("Invalid Path", "Please enter or browse to a valid destination folder.")
                return
        if self.current_page < 5:
            self._show_page(self.current_page + 1)

    def _on_back(self):
        if self.current_page > 0:
            self._show_page(self.current_page - 1)

    def _on_cancel(self):
        if self.current_page == 4:
            return  # Can't cancel while extracting
        if messagebox.askyesno("Exit Setup", "Are you sure you want to exit the EFL NEXUS Setup Wizard?"):
            self.destroy()

    def _on_finish(self):
        if self.launch_after_install_var.get() and self.installed_exe_path and self.installed_exe_path.exists():
            try:
                subprocess.Popen([str(self.installed_exe_path)], cwd=str(self.installed_exe_path.parent))
            except Exception as e:
                messagebox.showwarning("Launch Warning", f"Could not automatically launch EFL NEXUS:\n{e}")
        self.destroy()


if __name__ == "__main__":
    app = SetupWizard()
    app.mainloop()
