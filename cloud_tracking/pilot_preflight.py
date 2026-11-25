"""Read-only local pilot inventory. Never provisions or starts monitoring.

Run as each designated workstation's ordinary Windows account from the repository
root: python -m cloud_tracking.pilot_preflight --config <actual-config-path>
--expected-installation-uuid <owner-designated-machine-uuid>
"""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
from uuid import UUID

from cloud_monitoring import READY_FOR_DEVICE_PILOT
from cloud_monitoring.device_identity import identity_path, read_identity
from cloud_monitoring.security import load_machine_credential, machine_credential_path
from cloud_monitoring.operator_identity import identity


def inspect(config_path, expected_uuid):
    result = {
        'computer_name': socket.gethostname(),
        'monitoring_started_by_preflight': False,
        'default_pilot_gate_enabled': READY_FOR_DEVICE_PILOT,
        'identity_file_exists': identity_path().is_file(),
        'machine_credential_file_exists': machine_credential_path().is_file(),
        'server_enrollment_status': 'Requires owner AAL2 dashboard verification',
        'background_worker_and_lifecycle': 'Requires separately authorized runtime observation',
    }
    installation_uuid = None
    try:
        installation_uuid = read_identity()
        result['installation_uuid'] = installation_uuid
        result['designated_uuid_matches'] = installation_uuid == str(UUID(expected_uuid))
    except Exception as error:
        result['identity_check_error_type'] = type(error).__name__
        result['designated_uuid_matches'] = False

    try:
        record = load_machine_credential()
        result['credential_decryptable_in_this_windows_account'] = bool(record)
        if record:
            # Never serialize record, secret, key, enrollment code or machine binding.
            result['credential_matches_machine_uuid'] = record.get('installation_uuid') == installation_uuid
            result['credential_targets_existing_project'] = record.get('url') == 'https://wykmgymitdxkqbpywpzh.supabase.co'
            result['credential_has_device_id'] = bool(record.get('device_id'))
            result['credential_has_authentication_fields'] = bool(record.get('credential_id') and record.get('secret'))
            del record
    except Exception as error:
        result['credential_decryptable_in_this_windows_account'] = False
        result['credential_check_error_type'] = type(error).__name__

    result['config_file_exists'] = config_path.is_file()
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding='utf-8'))
            result['monitoring_requested_in_config'] = str(config.get('cloud_monitoring_enabled', 'false')).lower() == 'true'
            result['operator_identity'] = identity(str(config_path), socket.gethostname())
        except Exception as error:
            result['config_check_error_type'] = type(error).__name__

    root = os.environ.get('LOCALAPPDATA')
    queue_path = Path(root) / 'EFL_NEXUS' / 'Monitoring' / 'outbox.sqlite3' if root else None
    result['sqlite_queue_exists'] = bool(queue_path and queue_path.is_file())
    if result['sqlite_queue_exists']:
        try:
            # Do not instantiate OfflineQueue: its constructor creates/updates tables.
            connection = sqlite3.connect(queue_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
            try:
                connection.execute('PRAGMA query_only=ON')
                result['sqlite_quick_check_ok'] = connection.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                result['queued_events'] = connection.execute('SELECT count(*) FROM outbox').fetchone()[0]
                result['unclosed_launches'] = connection.execute('SELECT count(*) FROM launches WHERE ended=0').fetchone()[0]
                result['blocked_launches'] = connection.execute('SELECT count(*) FROM launches WHERE blocked<>0').fetchone()[0]
            finally:
                connection.close()
        except Exception as error:
            result['queue_check_error_type'] = type(error).__name__
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--expected-installation-uuid', type=lambda value: str(UUID(value)), required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.config, args.expected_installation_uuid), indent=2))


if __name__ == '__main__':
    main()
