"""
Updater for EFL_Nexus
Usage: updater.exe --url <download_url> --version <new_version> --pid <main_pid> --appdir <app_directory>
"""

import sys
import os
import time
import shutil
import subprocess
import tempfile
import zipfile
import threading
import logging
import traceback
import tkinter as tk
from tkinter import ttk, messagebox
import requests

# ----------------------------------------------------------------------
# Parse command line arguments
# ----------------------------------------------------------------------
def parse_args():
    args = {}
    for i, arg in enumerate(sys.argv):
        if arg.startswith("--"):
            key = arg[2:]
            if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
                args[key] = sys.argv[i + 1]
    return args


def _setup_logger(app_dir):
    log_path = os.path.join(app_dir, "updater.log")
    logger = logging.getLogger("updater")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    return logger


# ----------------------------------------------------------------------
# GUI updater
# ----------------------------------------------------------------------
class UpdaterApp:
    def __init__(self, root, url, new_version, pid, app_dir):
        self.root = root
        self.url = url
        self.new_version = new_version
        self.pid = pid
        self.app_dir = app_dir
        self.temp_dir = None
        self.download_path = None
        self.log = _setup_logger(app_dir)
        self.log.info(f"Updater started: url={url} version={new_version} pid={pid} appdir={app_dir}")

        # A previous run may have left updater.exe.old behind (it couldn't
        # delete it while it was still the running exe). It's safe to
        # remove now since that old process has long since exited.
        if getattr(sys, "frozen", False):
            stale = os.path.join(app_dir, os.path.basename(sys.executable) + ".old")
            try:
                if os.path.exists(stale):
                    os.remove(stale)
                    self.log.info(f"Cleaned up stale {stale} from a previous update.")
            except Exception as e:
                self.log.warning(f"Could not clean up stale {stale}: {e}")

        root.title("Update EFL Nexus")
        root.geometry("500x250")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        for icon_name in ("icon_2.ico", "icon.ico", "favicon.ico"):
            icon_path = os.path.join(app_dir, icon_name)
            if not os.path.exists(icon_path) and getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                icon_path = os.path.join(sys._MEIPASS, icon_name)
            if os.path.exists(icon_path):
                try:
                    root.iconbitmap(default=icon_path)
                    break
                except Exception:
                    try:
                        root.iconbitmap(icon_path)
                        break
                    except Exception:
                        pass

        main = ttk.Frame(root, padding="20")
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=f"Update to version {new_version}", font=("Segoe UI", 12, "bold")).pack(pady=(0, 10))
        self.status_var = tk.StringVar(value="Preparing update...")
        ttk.Label(main, textvariable=self.status_var).pack()

        self.progress = ttk.Progressbar(main, mode='determinate', maximum=100)
        self.progress.pack(fill=tk.X, pady=(10, 4))

        self.size_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.size_var, foreground="#6b7280", font=("Segoe UI", 9)).pack()

        self.button = ttk.Button(main, text="Cancel", command=self.on_close)
        self.button.pack(pady=(15, 5))

        threading.Thread(target=self.do_update, daemon=True).start()

    def on_close(self):
        if self.download_path is None:
            self.root.destroy()
        else:
            messagebox.showinfo("Update in progress", "The update is already running and cannot be cancelled.")

    def update_status(self, msg, value=None):
        self.log.info(f"STATUS: {msg}" + (f" ({value}%)" if value is not None else ""))
        self.status_var.set(msg)
        if value is not None:
            self.progress['value'] = value
        self.root.update_idletasks()

    def do_update(self):
        try:
            self.update_status("Downloading update...", 0)
            self.download_path = self.download_file(self.url)
            self.size_var.set("")
            self.update_status("Download complete.", 30)

            self.update_status("Extracting files...", 40)
            self.temp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(self.download_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)
            self.update_status("Extraction complete.", 60)

            self.update_status("Closing the main application...", 70)
            self.terminate_main_app()

            self.update_status("Installing new files...", 80)
            self.copy_new_files()

            # Written LAST, only after copy has provably succeeded, so a
            # failed copy can never leave a bumped version number pointing
            # at old/half-copied files.
            self.update_status("Updating version file...", 90)
            version_path = os.path.join(self.app_dir, "version.txt")
            with open(version_path, "w") as f:
                f.write(self.new_version.strip())
            self.log.info(f"Wrote version.txt -> {self.new_version.strip()} at {version_path}")

            self.update_status("Starting the updated application...", 100)
            self.restart_main_app()

            self.log.info("Update completed successfully.")
            self.root.after(0, self.root.destroy)

        except Exception as e:
            self.log.error("UPDATE FAILED", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror(
                "Update failed",
                f"{e}\n\nDetails were written to updater.log next to the app."
            ))
            self.root.after(0, self.root.destroy)

    def download_file(self, url):
        """Download the zip file, updating progress %, MB downloaded/total,
        and current speed as it goes."""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            block_size = 8192
            downloaded = 0

            start_time = time.time()
            last_ui_update = 0.0  # throttle UI/log updates to a few times a second

            fd, path = tempfile.mkstemp(suffix='.zip')
            with os.fdopen(fd, 'wb') as f:
                for chunk in response.iter_content(chunk_size=block_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.time()
                        if now - last_ui_update >= 0.2 or downloaded == total_size:
                            last_ui_update = now
                            elapsed = now - start_time
                            speed_mb_s = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                            self._set_download_progress(downloaded, total_size, speed_mb_s)

                        if total_size:
                            self.progress['value'] = 30 * (downloaded / total_size)
                            self.root.update_idletasks()

            self.log.info(f"Download finished: {downloaded / (1024 * 1024):.1f}MB")
            return path
        except Exception as e:
            raise Exception(f"Download failed: {e}")

    def _set_download_progress(self, downloaded, total_size, speed_mb_s):
        downloaded_mb = downloaded / (1024 * 1024)
        if total_size:
            total_mb = total_size / (1024 * 1024)
            text = f"{downloaded_mb:.1f}MB / {total_mb:.1f}MB   •   {speed_mb_s:.1f} MB/s"
        else:
            # Server didn't send content-length, so we don't know the total
            text = f"{downloaded_mb:.1f}MB downloaded   •   {speed_mb_s:.1f} MB/s"
        self.size_var.set(text)
        self.root.update_idletasks()

    def terminate_main_app(self):
        """Terminate the process, then wait for it to actually exit
        (not just a blind sleep) before returning, so we don't race the
        OS releasing the file lock on the exe we're about to overwrite."""
        try:
            import psutil
            proc = psutil.Process(int(self.pid)) if self.pid else None
        except Exception:
            proc = None

        if self.pid:
            subprocess.run(['taskkill', '/F', '/PID', str(self.pid)], capture_output=True)
        else:
            subprocess.run(['taskkill', '/F', '/IM', 'EFL_Nexus.exe'], capture_output=True)

        if proc is not None:
            try:
                proc.wait(timeout=10)
                self.log.info("Confirmed main app process exited.")
            except Exception:
                self.log.warning("Could not confirm process exit via psutil; falling back to delay.")
                time.sleep(2)
        else:
            self.log.warning("No pid/psutil wait available; using fixed delay.")
            time.sleep(2)

    def copy_new_files(self):
        """Copy files from temp_dir to app_dir, overwriting existing.
        Handles a zip with a single top-level folder instead of files at
        the zip root, and retries briefly on PermissionError."""
        if not os.path.exists(self.app_dir):
            os.makedirs(self.app_dir)

        entries = os.listdir(self.temp_dir)
        self.log.info(f"Top-level entries in extracted zip: {entries}")

        source_dir = self.temp_dir
        if len(entries) == 1:
            only_path = os.path.join(self.temp_dir, entries[0])
            if os.path.isdir(only_path):
                self.log.info(f"Zip has a single top-level folder '{entries[0]}' -- flattening.")
                source_dir = only_path
                entries = os.listdir(source_dir)

        expected = {"version.txt"}  # exe name casing varies (EFL_NEXUS.exe vs EFL_Nexus.exe);
                                     # Windows paths are case-insensitive so that's not a real problem
        missing = expected - {e.lower() for e in entries}
        if missing:
            self.log.warning(f"Expected files not found at copy source: {missing}. "
                              f"Actual contents: {entries}")

        # If running as a frozen exe, this process's own exe file is
        # currently locked by the OS and can't be overwritten with a
        # normal copy -- it needs the rename-then-copy trick below.
        self_exe_name = os.path.basename(sys.executable) if getattr(sys, "frozen", False) else None

        for item in entries:
            if item.lower() in ("config.json", ".env"):
                self.log.info(f"Skipping user config file '{item}' during update to preserve user settings.")
                continue
            src = os.path.join(source_dir, item)
            dst = os.path.join(self.app_dir, item)
            if self_exe_name and item.lower() == self_exe_name.lower():
                self._replace_self(src, dst)
            else:
                self._copy_with_retry(src, dst)
            self.log.info(f"Copied {src} -> {dst}")

    def _replace_self(self, src, dst):
        """The updater can't overwrite its own running exe with a normal
        copy -- Windows keeps an exclusive lock on it while it's executing.
        Renaming it out of the way first works even while running, since
        rename doesn't need the write lock that copy does. The old file
        gets cleaned up on the *next* run (it can't delete itself now
        either, while still running)."""
        old_path = dst + ".old"
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
        except Exception as e:
            self.log.warning(f"Could not remove stale {old_path}: {e}")

        try:
            os.rename(dst, old_path)
            self.log.info(f"Renamed running updater {dst} -> {old_path} to free up the path")
        except Exception as e:
            self.log.warning(f"Could not rename current updater exe out of the way: {e}")

        self._copy_with_retry(src, dst)

    def _copy_with_retry(self, src, dst, attempts=5, delay=1.0):
        last_err = None
        for i in range(attempts):
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                return
            except PermissionError as e:
                last_err = e
                self.log.warning(f"Locked on attempt {i + 1}/{attempts} copying {dst}: {e}")
                time.sleep(delay)
        

    def restart_main_app(self):
        """Launch the main application."""
        main_exe = os.path.join(self.app_dir, "EFL_Nexus.exe")
        if os.path.exists(main_exe):
            subprocess.Popen([main_exe], cwd=self.app_dir)
        else:
            raise Exception("EFL_Nexus.exe not found after update.")


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Log to a fixed, always-writable location FIRST -- before we even
    # know app_dir, and before Tk/anything else runs -- so a --noconsole
    # build can never hide a crash from us again.
    crash_log_path = os.path.join(tempfile.gettempdir(), "efl_nexus_updater_crash.log")

    def log_crash(msg):
        try:
            with open(crash_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.ctime()} {msg}\n")
        except Exception:
            pass

    try:
        args = parse_args()
        log_crash(f"Parsed args: {args}")

        url = args.get('url')
        new_version = args.get('version')
        pid = args.get('pid')
        app_dir = args.get('appdir')

        if not url or not new_version or not app_dir:
            log_crash(f"Missing required args. Got url={url!r} version={new_version!r} appdir={app_dir!r}. "
                       f"Full sys.argv={sys.argv}")
            print("Usage: updater.exe --url <download_url> --version <version> --pid <pid> --appdir <app_dir>")
            sys.exit(1)

        try:
            pid = int(pid) if pid else None
        except ValueError:
            pid = None

        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('efl.nexus.updater')
        except Exception:
            pass

        root = tk.Tk()
        app = UpdaterApp(root, url, new_version, pid, app_dir)
        root.mainloop()

    except Exception:
        log_crash("UNHANDLED EXCEPTION:\n" + traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Updater crashed. Details written to:\n{crash_log_path}",
                "Update Error", 0
            )
        except Exception:
            pass
        sys.exit(1)
