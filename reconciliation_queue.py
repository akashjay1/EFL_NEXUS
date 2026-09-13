"""Persistent local queue shared by EFL NEXUS reconciliation tools."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path


_QUEUE_LOCK = threading.RLock()
_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def get_queue_file() -> Path:
    """Return the per-user queue file, with a home-folder fallback."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base_dir = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base_dir / "EFL_NEXUS" / "reconciliation_queue.json"


def _read_queue(queue_file: Path) -> list[dict]:
    if not queue_file.exists():
        return []
    try:
        with queue_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []

    entries = data.get("pending", []) if isinstance(data, dict) else []
    if not isinstance(entries, list):
        return []
    return [
        entry for entry in entries
        if isinstance(entry, dict) and str(entry.get("job_id", "")).strip()
    ]


def _write_queue(queue_file: Path, entries: list[dict]) -> None:
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "pending": entries}
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=queue_file.parent,
            prefix="reconciliation_queue_", suffix=".tmp", delete=False
        ) as handle:
            json.dump(payload, handle, indent=2)
            temp_name = handle.name
        os.replace(temp_name, queue_file)
    finally:
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def list_pending_jobs(queue_file: str | os.PathLike | None = None) -> list[dict]:
    """Return pending jobs in FIFO order as independent dictionaries."""
    path = Path(queue_file) if queue_file is not None else get_queue_file()
    with _QUEUE_LOCK:
        return [dict(entry) for entry in _read_queue(path)]


def enqueue_job(
    job_id: str,
    task_type: str,
    user_id: str,
    submitted_at: str | None = None,
    queue_file: str | os.PathLike | None = None,
) -> dict:
    """Add a job unless its ID is already pending (case-insensitive)."""
    clean_job_id = str(job_id).strip()
    if not clean_job_id:
        raise ValueError("Job ID cannot be blank")

    path = Path(queue_file) if queue_file is not None else get_queue_file()
    with _QUEUE_LOCK:
        entries = _read_queue(path)
        lookup = clean_job_id.casefold()
        for entry in entries:
            if str(entry.get("job_id", "")).strip().casefold() == lookup:
                return dict(entry)

        entry = {
            "job_id": clean_job_id,
            "task_type": str(task_type).strip().rstrip(":"),
            "user_id": str(user_id).strip(),
            "submitted_at": submitted_at or datetime.now().isoformat(timespec="seconds"),
        }
        entries.append(entry)
        _write_queue(path, entries)
        return dict(entry)


def complete_job(job_id: str, queue_file: str | os.PathLike | None = None) -> bool:
    """Remove all pending entries matching a Job ID. Return whether one existed."""
    clean_job_id = str(job_id).strip()
    if not clean_job_id:
        return False

    path = Path(queue_file) if queue_file is not None else get_queue_file()
    with _QUEUE_LOCK:
        entries = _read_queue(path)
        lookup = clean_job_id.casefold()
        remaining = [
            entry for entry in entries
            if str(entry.get("job_id", "")).strip().casefold() != lookup
        ]
        if len(remaining) == len(entries):
            return False
        _write_queue(path, remaining)
        return True


def clear_queue(queue_file: str | os.PathLike | None = None) -> int:
    """Remove every pending job and return the number removed."""
    path = Path(queue_file) if queue_file is not None else get_queue_file()
    with _QUEUE_LOCK:
        entries = _read_queue(path)
        if entries or path.exists():
            _write_queue(path, [])
        return len(entries)


def safe_job_folder_name(job_id: str) -> str:
    """Convert a Job ID to one safe Windows folder component."""
    folder_name = _INVALID_FOLDER_CHARS.sub("_", str(job_id).strip()).rstrip(" .")
    if not folder_name or folder_name in {".", ".."}:
        folder_name = "job"
    if folder_name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        folder_name = f"_{folder_name}"
    return folder_name


def is_reconciliation_task(task_type: str) -> bool:
    """Return whether a User Data Manager task belongs in this queue."""
    normalized_task = str(task_type).strip().rstrip(":").casefold()
    return normalized_task in {"gdn reconciliation", "grn reconciliation"}


def get_reconciliation_output_folder(base_folder: str | os.PathLike, job_id: str) -> Path:
    """Build the safe output folder for a selected queued job."""
    return Path(base_folder) / safe_job_folder_name(job_id)


def choose_pending_job(entries: list[dict], current_job_id: str = "") -> str:
    """Keep a valid selection or choose the oldest pending Job ID."""
    job_ids = [str(entry.get("job_id", "")).strip() for entry in entries]
    job_ids = [job_id for job_id in job_ids if job_id]
    current_lookup = str(current_job_id).strip().casefold()
    for job_id in job_ids:
        if job_id.casefold() == current_lookup:
            return job_id
    return job_ids[0] if job_ids else ""
