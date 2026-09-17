"""Local KPI identity shared by the dashboard and EFL data entry UI."""

import json
import sys
from pathlib import Path


def app_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def validate_profile(user_id, user_code, users_path=None):
    """Return the registered spelling and code, or raise a user-facing error."""
    user_id = str(user_id or "").strip()
    user_code = str(user_code or "").strip()
    if not user_id or not user_code:
        raise ValueError("Enter both KPI User ID and User Code.")

    path = Path(users_path) if users_path is not None else app_directory() / "efl_users.json"
    try:
        with path.open("r", encoding="utf-8") as file:
            users = json.load(file)["users"]
        if not isinstance(users, dict):
            raise ValueError("Invalid user list")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError("The registered KPI user list could not be loaded.") from error

    for registered_id in users:
        if registered_id.casefold() == user_id.casefold():
            return registered_id, user_code
    raise ValueError("KPI User ID was not found in the registered user list.")


def load_saved_profile(config_path=None, users_path=None):
    """Return a validated profile or None when setup is incomplete/invalid."""
    path = Path(config_path) if config_path is not None else app_directory() / "config.json"
    try:
        with path.open("r", encoding="utf-8") as file:
            config = json.load(file)
        return validate_profile(config.get("kpi_user_id"), config.get("kpi_user_code"), users_path)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def export_filename(user_id, start_date, end_date):
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id).strip("_-") or "User"
    return f"KPI_{safe_id}_{start_date:%Y-%m-%d}_to_{end_date:%Y-%m-%d}.xlsx"
