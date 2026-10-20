"""Local GDN extraction and durable review inbox; no WhatsApp credentials here."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time


GDN_FIELDS = ("warehouse", "client", "gatepass", "delivery_location", "seal")
FIELD_LABELS = {
    "warehouse": "Warehouse ID", "client": "Client Code", "gatepass": "Gate Pass No.",
    "delivery_location": "Delivery Location (Note)", "seal": "Seal No.",
    "door_location": "Door Location",
}
_LABEL = re.compile(
    r"^\s*[*_~`]*\s*(WH\s*ID|Warehouse(?:\s*ID)?|Client\s*Code|"
    r"Gate\s*Pass(?:\s*(?:No\.?|Number|#))?|Door\s*Location|"
    r"Seal\s*(?:Numbers?|Nos?\.?|#)|Note|Delivery\s*Location)"
    r"\s*[*_~`]*\s*[:#=\-]\s*[*_~`]*\s*(.*?)\s*$", re.IGNORECASE,
)


def data_directory():
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share"))
    return base / "EFL_NEXUS" / "whatsapp_gdn"


@dataclass
class ParsedGDN:
    fields: dict
    warnings: list
    candidate: bool


def parse_gdn_message(text):
    """Extract labelled values, preserving identifiers and flagging conflicts.

    Note is the delivery location. Door location is metadata only. Missing
    values remain empty, rather than being replaced with invented defaults.
    """
    fields = {key: "" for key in (*GDN_FIELDS, "door_location")}
    warnings = []
    active_note = False
    for line in str(text).replace("\r\n", "\n").splitlines():
        match = _LABEL.match(line)
        if not match:
            if active_note and line.strip() and ":" not in line:
                fields["delivery_location"] += "\n" + line.strip().strip("*_~`")
            else:
                active_note = False
            continue
        label = re.sub(r"[\s.#]", "", match[1]).casefold()
        if label.startswith(("wh", "warehouse")):
            key = "warehouse"
        elif label.startswith("client"):
            key = "client"
        elif label.startswith("gate"):
            key = "gatepass"
        elif label.startswith("door"):
            key = "door_location"
        elif label.startswith("seal"):
            key = "seal"
        else:
            key = "delivery_location"
        value = match[2].strip().strip("*_~`").strip()
        if value == "-":
            value = ""
        if fields[key] and fields[key] != value:
            warnings.append(f"Conflicting {FIELD_LABELS[key]} values: {fields[key]} / {value}")
        else:
            fields[key] = value
        active_note = key == "delivery_location" and bool(value)
    count = sum(bool(fields[key]) for key in GDN_FIELDS)
    candidate = count >= 2 and any(fields[key] for key in ("warehouse", "client", "gatepass"))
    return ParsedGDN(fields, warnings, candidate)


def validate_fields(fields, warehouses):
    errors = [f"Missing {FIELD_LABELS[key]}" for key in GDN_FIELDS
              if str(fields.get(key, "")).strip() in ("", "-")]
    for key in GDN_FIELDS:
        allowed = "\r\n" if key == "delivery_location" else ""
        if any(ord(char) < 32 and char not in allowed for char in str(fields.get(key, ""))):
            errors.append(f"Remove control characters from {FIELD_LABELS[key]}")
    warehouse = str(fields.get("warehouse", "")).strip().upper()
    if warehouse and warehouse not in warehouses:
        errors.append(f"Unknown Warehouse ID: {warehouse}")
    return errors


def form_fields(fields):
    """Korber uses single-line inputs; don't send Note line breaks as key presses."""
    result = {key: fields[key] for key in GDN_FIELDS}
    result["delivery_location"] = " ".join(line.strip() for line in result["delivery_location"].splitlines() if line.strip())
    return result


def content_fingerprint(text):
    normalized = " ".join(str(text).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class GDNInboxStore:
    """Each thread/process owns its connection; imports commit before display."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else data_directory() / "inbox.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL, message_id TEXT NOT NULL, received_at TEXT NOT NULL,
            raw_text TEXT NOT NULL, fields TEXT NOT NULL, warnings TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'New'
        )""")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS monitor_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS monitor_runtime (
                run_id TEXT PRIMARY KEY, heartbeat REAL NOT NULL, state TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '', gap INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS monitor_commands (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, action TEXT NOT NULL,
                payload TEXT NOT NULL
            );
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def add(self, text, source="Clipboard", message_id=""):
        parsed = parse_gdn_message(text)
        if not parsed.candidate:
            return None, "Not a GDN request: at least two labelled GDN fields are needed."
        fingerprint = content_fingerprint(text)
        with self.db:
            cursor = self.db.execute(
                """INSERT INTO requests
                (fingerprint, source, message_id, received_at, raw_text, fields, warnings)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(fingerprint) DO NOTHING""",
                (fingerprint, source, message_id, datetime.now(timezone.utc).isoformat(),
                 text, json.dumps(parsed.fields), json.dumps(parsed.warnings)),
            )
            row = self.db.execute("SELECT id FROM requests WHERE fingerprint=?", (fingerprint,)).fetchone()
        return row["id"], "Imported for review." if cursor.rowcount else "Duplicate message already in inbox."

    def setting(self, key, default=None):
        row = self.db.execute("SELECT value FROM monitor_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_settings(self, **settings):
        with self.db:
            self.db.executemany(
                "INSERT INTO monitor_settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(key, json.dumps(value)) for key, value in settings.items()],
            )

    def runtime(self, run_id):
        row = self.db.execute("SELECT * FROM monitor_runtime WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def report(self, run_id, state, detail="", gap=False):
        with self.db:
            self.db.execute("""INSERT INTO monitor_runtime VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET heartbeat=excluded.heartbeat,
                state=excluded.state, detail=excluded.detail, gap=excluded.gap""",
                (run_id, time.time(), state, detail, int(gap)))

    def command(self, run_id, action, **payload):
        with self.db:
            self.db.execute("INSERT INTO monitor_commands (run_id, action, payload) VALUES (?, ?, ?)",
                            (run_id, action, json.dumps(payload)))

    def take_commands(self, run_id):
        # Single consumer per run; remove only commands for that helper.
        with self.db:
            rows = list(self.db.execute("SELECT * FROM monitor_commands WHERE run_id=? ORDER BY id", (run_id,)))
            self.db.execute("DELETE FROM monitor_commands WHERE run_id=?", (run_id,))
        return [(row["action"], json.loads(row["payload"])) for row in rows]

    def counts(self):
        return tuple(self.db.execute("SELECT COUNT(*), COALESCE(SUM(action='New'), 0) FROM requests").fetchone())

    def version(self):
        return self.db.execute("PRAGMA data_version").fetchone()[0]

    def records(self):
        return [self._decode(row) for row in self.db.execute("SELECT * FROM requests ORDER BY id DESC")]

    def get(self, record_id):
        row = self.db.execute("SELECT * FROM requests WHERE id=?", (record_id,)).fetchone()
        return self._decode(row) if row else None

    @staticmethod
    def _decode(row):
        record = dict(row)
        for key in ("fields", "warnings"):
            record[key] = json.loads(record[key])
        return record

    def save_review(self, record_id, fields, action="Reviewed"):
        with self.db:
            self.db.execute("UPDATE requests SET fields=?, action=? WHERE id=?",
                            (json.dumps(fields), action, record_id))

    def related(self, fields, exclude_id=None):
        keys = ("warehouse", "client", "gatepass")
        identity = tuple(str(fields.get(k, "")).strip().casefold() for k in keys)
        if not all(identity):
            return []
        return [r for r in self.records() if r["id"] != exclude_id and
                tuple(str(r["fields"].get(k, "")).strip().casefold() for k in keys) == identity]
