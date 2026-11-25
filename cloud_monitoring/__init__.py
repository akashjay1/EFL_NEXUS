"""Optional desktop monitoring; importing this package performs no I/O."""
import os
from pathlib import Path


def is_monitoring_authorized():
    """Returns True only if this specific machine has been provisioned with a valid
    DPAPI machine credential and an explicit machine-level activation token or pilot flag.
    When a fresh, non-revoked company workstation is detected, attempts zero-touch auto-registration.
    """
    if os.environ.get("EFL_PILOT_DEVICE_ACTIVE", "").lower() in ("1", "true"):
        return True
    try:
        from .security import is_machine_active, load_machine_credential
        cred = load_machine_credential()
        if cred is not None and is_machine_active():
            return True
        from .device_identity import auto_register_machine
        return auto_register_machine()
    except Exception:
        return False


# Global default is strictly False for unprovisioned/unauthorized installations
READY_FOR_DEVICE_PILOT = False
