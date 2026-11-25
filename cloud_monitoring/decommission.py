"""Enterprise workstation self-deprovisioning and clean uninstallation upon device revocation."""
import ctypes
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile

logger = logging.getLogger(__name__)


def is_self_destruct_enabled():
    """Safety guard: disable self-destruct during automated test runs."""
    return os.environ.get("EFL_DISABLE_SELF_DESTRUCT", "").lower() not in ("1", "true")


def show_revocation_dialog():
    """Display prominent corporate decommissioning message to operator (Option A)."""
    title = "EFL NEXUS - Device Authorization Revoked"
    message = (
        "This workstation has been decommissioned by the corporate administrator.\n\n"
        "EFL NEXUS will now close and remove itself from this PC."
    )
    try:
        # MB_ICONERROR (0x10) | MB_SYSTEMMODAL (0x1000) | MB_SETFOREGROUND (0x10000)
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10 | 0x1000 | 0x10000)
    except Exception as e:
        logger.warning("Could not display native revocation dialog: %s", e)


def wipe_local_monitoring_data():
    """Remove all local machine credentials, tokens, identity files, and offline queues."""
    from .security import delete_machine_credential, set_machine_active
    try:
        delete_machine_credential()
    except Exception:
        pass
    try:
        set_machine_active(False)
    except Exception:
        pass

    target_dirs = [
        Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'EFL_NEXUS_Monitoring',
        Path(os.environ.get('LOCALAPPDATA', '')) / 'EFL_NEXUS' / 'Monitoring',
    ]
    for d in target_dirs:
        if d.exists():
            for item in d.glob('*'):
                try:
                    if item.is_file():
                        item.unlink()
                except OSError:
                    pass


def trigger_self_destruct(install_dir=None, reason="Device revoked by administrator"):
    """Execute complete self-destruction: wipe secrets, inform user, schedule file purge, and exit."""
    logger.critical("Workstation decommission triggered: %s", reason)

    # 1. Wipe credentials and monitoring state first so re-runs never resume revoked sessions
    wipe_local_monitoring_data()

    if not is_self_destruct_enabled():
        logger.warning("Self-destruct uninstallation skipped (EFL_DISABLE_SELF_DESTRUCT is active).")
        return

    # 2. Display Option A notification dialog
    show_revocation_dialog()

    # 3. Schedule detached uninstallation of application binaries and shortcuts
    if install_dir is None:
        if getattr(sys, 'frozen', False):
            install_dir = Path(sys.executable).resolve().parent
        else:
            # When running from source in development, do not delete the project repository
            logger.info("Running from source tree; skipping directory purge to protect workspace.")
            os._exit(0)

    install_dir = Path(install_dir).resolve()
    user_profile = os.environ.get("USERPROFILE", "")
    appdata = os.environ.get("APPDATA", "")

    # Look for existing uninstall.bat in application directory
    uninstaller_bat = install_dir / "uninstall.bat"
    if uninstaller_bat.is_file():
        cmd = f'cmd.exe /c start "" /min "{uninstaller_bat}" --revocation'
    else:
        # Create a self-deleting standalone cleanup script in %TEMP%
        cleanup_lines = [
            '@echo off',
            'timeout /t 2 /nobreak >nul',
            f'taskkill /f /im EFL_NEXUS.exe 2>nul',
            f'taskkill /f /im updater.exe 2>nul',
            f'del /f /q "{user_profile}\\Desktop\\EFL NEXUS.lnk" 2>nul',
            f'del /f /q "{user_profile}\\OneDrive\\Desktop\\EFL NEXUS.lnk" 2>nul',
            f'rmdir /s /q "{appdata}\\Microsoft\\Windows\\Start Menu\\Programs\\EFL NEXUS" 2>nul',
            f'rmdir /s /q "{install_dir}" 2>nul',
            'del "%~f0" 2>nul',
        ]
        cleanup_file = Path(tempfile.gettempdir()) / f"efl_nexus_uninstall_{os.getpid()}.bat"
        cleanup_file.write_text('\r\n'.join(cleanup_lines), encoding='ascii', errors='ignore')
        cmd = f'cmd.exe /c "{cleanup_file}"'

    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    try:
        subprocess.Popen(
            cmd,
            shell=False,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True
        )
    except Exception as e:
        logger.error("Failed to spawn detached uninstaller: %s", e)

    # 4. Terminate immediately
    os._exit(0)
