"""Dormant PyInstaller hook for a separately authorized, two-device pilot build.

Not used by EFL_NEXUS.spec. Keep this template disabled in the ordinary checkout.
Only set the two real UUIDs and authorization flag in an isolated pilot build
after the owner separately authorizes monitoring. Never publish that build to
the general updater. This hook performs no network calls or provisioning.
"""
import re
from uuid import UUID

OWNER_AUTHORIZED = False
PILOT_INSTALLATION_UUIDS = frozenset()
PROJECT_URL = 'https://wykmgymitdxkqbpywpzh.supabase.co'


def eligible():
    if not OWNER_AUTHORIZED or len(PILOT_INSTALLATION_UUIDS) != 2:
        return False
    try:
        allowed = {str(UUID(value)) for value in PILOT_INSTALLATION_UUIDS}
        if len(allowed) != 2:
            return False
        from cloud_monitoring.device_identity import read_identity
        installation_uuid = read_identity()
        if installation_uuid not in allowed:
            return False
        from cloud_monitoring.security import load_machine_credential
        record = load_machine_credential()
        if not record or record.get('installation_uuid') != installation_uuid:
            return False
        if record.get('url') != PROJECT_URL:
            return False
        UUID(record['device_id'])
        UUID(record['credential_id'])
        return bool(re.fullmatch(r'[0-9a-f]{64}', record.get('secret', '')))
    except Exception:
        # Fail closed without printing credentials or local machine binding.
        return False


if eligible():
    import cloud_monitoring
    # In-memory gate for this pilot process only. The distributed default stays False.
    # main_app still also requires cloud_monitoring_enabled in its actual config.
    cloud_monitoring.READY_FOR_DEVICE_PILOT = True
