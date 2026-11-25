"""Administrator utility for inspecting, activating, and immediately rolling back
machine-scoped cloud monitoring on an EFL NEXUS Windows workstation.
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloud_monitoring import is_monitoring_authorized, READY_FOR_DEVICE_PILOT
from cloud_monitoring.device_identity import read_identity, identity_path, machine_binding
from cloud_monitoring.security import (
    load_machine_credential,
    machine_credential_path,
    is_machine_active,
    set_machine_active,
    activation_token_path
)


def get_status():
    status = {
        "global_default_ready": READY_FOR_DEVICE_PILOT,
        "is_monitoring_authorized": is_monitoring_authorized(),
        "is_machine_active": is_machine_active(),
        "activation_token_path": str(activation_token_path()),
        "token_exists": activation_token_path().is_file(),
        "credential_path": str(machine_credential_path()),
        "credential_exists": machine_credential_path().is_file(),
        "identity_path": str(identity_path()),
        "identity_exists": identity_path().is_file(),
        "installation_uuid": None,
        "device_id": None,
        "credential_id": None,
        "machine_binding_match": False
    }

    try:
        status["installation_uuid"] = read_identity()
        status["machine_binding_match"] = True
    except Exception as e:
        status["identity_error"] = str(e)

    try:
        cred = load_machine_credential()
        if cred:
            status["device_id"] = cred.get("device_id")
            status["credential_id"] = cred.get("credential_id")
    except Exception as e:
        status["credential_error"] = str(e)

    return status


def main():
    parser = argparse.ArgumentParser(description="EFL NEXUS Machine Monitoring Manager")
    parser.add_argument("action", choices=["status", "activate", "deactivate"], help="Action to execute")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    if args.action == "status":
        info = get_status()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("========================================")
            print("EFL NEXUS Machine Monitoring Status")
            print("========================================")
            print(f"Global Default Ready     : {info['global_default_ready']}")
            print(f"Monitoring Authorized    : {info['is_monitoring_authorized']}")
            print(f"Machine Active Token     : {info['is_machine_active']}")
            print(f"Installation UUID        : {info['installation_uuid']}")
            print(f"Device ID                : {info['device_id']}")
            print(f"Credential ID            : {info['credential_id']}")
            print(f"Machine Binding Verified : {info['machine_binding_match']}")
            print("========================================")

    elif args.action == "activate":
        set_machine_active(True)
        print("Machine monitoring activation token enabled.")
        print(f"Monitoring authorized: {is_monitoring_authorized()}")

    elif args.action == "deactivate":
        set_machine_active(False)
        print("ROLLBACK: Machine monitoring activation token removed.")
        print(f"Monitoring authorized: {is_monitoring_authorized()}")


if __name__ == "__main__":
    main()
