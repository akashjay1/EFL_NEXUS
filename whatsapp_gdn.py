"""Local GDN extraction and durable review inbox; no WhatsApp credentials here."""

from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


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


def received_label(record):
    """WhatsApp's rendered date is authoritative; never infer its locale/zone."""
    if record.get("message_time"):
        return record["message_time"]
    captured = record.get("received_at") or record.get("captured_at")
    if captured:
        try:
            stamp = datetime.fromisoformat(captured).astimezone()
            return "Captured " + stamp.strftime("%d %b %Y %H:%M")
        except (ValueError, TypeError):
            pass
    return "Time unavailable"


def automation_lanes(lanes):
    """Include other lane owners in duplicate checks without routing to them."""
    found = {id(lane): lane for lane in lanes.values()}
    for lane in lanes.values():
        registered = getattr(getattr(lane, "root", None), "_whatsapp_gdn_lanes", {})
        if isinstance(registered, dict):
            found.update((id(other), other) for other in registered.values())
    return tuple(found.values())


def gatepass_is_active(lanes, doc_type, fields):
    """Only live runs and waiting/running queue entries block an intentional rerun."""
    keys = ("warehouse_id", "client_code", "gate_pass_number") if doc_type == "GDN" else ("warehouse_id", "gate_pass_number")
    identity = tuple(str(fields.get(k, "")).strip().casefold() for k in keys)
    for lane in automation_lanes(lanes):
        candidates = [item for item in lane.queue if item.get("status", "Queued") in ("Queued", "Running")]
        if getattr(lane, "_flow_request", None):
            candidates.append(lane._flow_request)
        if any(item["doc_type"] == doc_type and
               tuple(str(item.get(k, "")).strip().casefold() for k in keys) == identity for item in candidates):
            return True
    return False


def recover_gatepass_runs(store, lanes, doc_type):
    active = {getattr(lane, "whatsapp_run_id", "") for lane in automation_lanes(lanes)}
    store.recover_gatepass_runs(active, doc_type)


def launch_gatepass(store, record_id, doc_type, lane_name, lane):
    """Persist each attempt and receive its actual outcome, even after a view closes."""
    run_id = store.begin_gatepass_run(record_id, lane_name, doc_type)
    lane.whatsapp_run_id = run_id
    path, store_type = store.path, type(store)

    def finished(completed, detail):
        # The lane worker owns this connection; it never uses the view's Tk or DB.
        result_store = None
        try:
            result_store = store_type(path)
            result_store.finish_gatepass_run(run_id, completed, detail)
        finally:
            if result_store is not None:
                result_store.close()
            if getattr(lane, "whatsapp_run_id", "") == run_id:
                lane.whatsapp_run_id = ""

    try:
        if lane.run_flow(doc_type, on_complete=finished) is False:
            raise ValueError("The lane did not start. Check its required fields and current run.")
    except Exception as exc:
        finished(False, f"Could not start: {exc}")
        raise
    return run_id


class GDNInboxStore:
    """Each thread/process owns its connection; imports commit before display."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else data_directory() / "inbox.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        # Back up an existing inbox before the additive execution-state migration.
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(requests)")}
        if columns and "run_state" not in columns:
            backup_path = self.path.with_name(f"{self.path.stem}.before-gatepass-runs-{uuid.uuid4().hex}.sqlite3")
            with closing(sqlite3.connect(backup_path)) as backup:
                self.db.backup(backup)
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
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                group_id TEXT NOT NULL, message_id TEXT NOT NULL,
                message_time TEXT NOT NULL DEFAULT '', request_id INTEGER,
                done INTEGER NOT NULL DEFAULT 0, done_reply_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(group_id,message_id)
            );
            CREATE TABLE IF NOT EXISTS gdn_message_requests (
                group_id TEXT NOT NULL, message_id TEXT NOT NULL, request_id INTEGER NOT NULL,
                PRIMARY KEY(group_id,message_id,request_id)
            );
            CREATE TABLE IF NOT EXISTS gatepass_runs (
                run_id TEXT PRIMARY KEY, doc_type TEXT NOT NULL, record_id INTEGER NOT NULL,
                lane TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT ''
            );
            INSERT OR IGNORE INTO gdn_message_requests
                SELECT group_id,message_id,request_id FROM whatsapp_messages WHERE request_id IS NOT NULL;
        """)
        self.add_columns("requests", {"message_time": "TEXT NOT NULL DEFAULT ''",
                                     "hidden_reason": "TEXT NOT NULL DEFAULT ''",
                                     "run_state": "TEXT NOT NULL DEFAULT 'New'",
                                     "run_id": "TEXT NOT NULL DEFAULT ''"})
        self.db.commit()

    def add_columns(self, table, definitions):
        # Called under a write transaction so parallel helper/UI startup cannot
        # race between checking a column and adding it.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            columns = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name, definition in definitions.items():
                if name not in columns:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def close(self):
        self.db.close()

    @staticmethod
    def _run_table(doc_type):
        return {"GDN": "requests", "GRN": "grn_documents"}[doc_type]

    def begin_gatepass_run(self, record_id, lane, doc_type="GDN"):
        table = self._run_table(doc_type)
        run_id = uuid.uuid4().hex
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
            if row is None or row["hidden_reason"]:
                raise ValueError("This item was cleared or marked DONE. Select an active item.")
            if row["run_state"] == "Running":
                raise ValueError("This gate pass is already running. Wait for it to finish or stop the lane.")
            def identity(record):
                values = json.loads(record["fields"]) if doc_type == "GDN" else record
                keys = ("warehouse", "client", "gatepass") if doc_type == "GDN" else ("warehouse", "gatepass")
                return tuple(str(values[k]).strip().casefold() for k in keys)
            if any(identity(other) == identity(row) for other in self.db.execute(
                    f"SELECT * FROM {table} WHERE run_state='Running'")):
                raise ValueError("A matching gate pass is already running in another lane.")
            self.db.execute(f"UPDATE {table} SET run_state='Running',run_id=? WHERE id=?", (run_id, record_id))
            self.db.execute("INSERT INTO gatepass_runs(run_id,doc_type,record_id,lane,state,started_at) VALUES (?,?,?,?,?,?)",
                            (run_id, doc_type, record_id, lane, "Running", datetime.now(timezone.utc).isoformat()))
        return run_id

    def finish_gatepass_run(self, run_id, completed, detail=""):
        with self.db:
            row = self.db.execute("SELECT * FROM gatepass_runs WHERE run_id=? AND state='Running'", (run_id,)).fetchone()
            if row is None:
                return  # Duplicate/late callbacks cannot overwrite a newer run.
            state = "Completed" if completed else "New"
            self.db.execute("UPDATE gatepass_runs SET state=?,detail=?,finished_at=? WHERE run_id=? AND state='Running'",
                            (state, detail, datetime.now(timezone.utc).isoformat(), run_id))
            table = self._run_table(row["doc_type"])
            self.db.execute(f"UPDATE {table} SET run_state=? WHERE id=? AND run_id=? AND run_state='Running'",
                            (state, row["record_id"], run_id))

    def recover_gatepass_runs(self, active_ids, doc_type):
        table = self._run_table(doc_type)
        for row in self.db.execute(f"SELECT run_id FROM {table} WHERE run_state='Running'").fetchall():
            if row["run_id"] not in active_ids:
                self.finish_gatepass_run(row["run_id"], False, "Previous run ended without a confirmed result; ready to run again.")

    def add(self, text, source="Clipboard", message_id="", *, group_id="", message_time=""):
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
            if group_id and message_id:
                self.db.execute("""INSERT INTO whatsapp_messages(group_id,message_id,message_time,request_id)
                    VALUES (?,?,?,?) ON CONFLICT(group_id,message_id) DO UPDATE SET
                    request_id=excluded.request_id,
                    message_time=CASE WHEN excluded.message_time<>'' THEN excluded.message_time ELSE whatsapp_messages.message_time END""",
                    (group_id, message_id, message_time, row["id"]))
                self.db.execute("UPDATE requests SET message_time=? WHERE id=? AND message_time=''",
                                (message_time, row["id"]))
                self.db.execute("INSERT OR IGNORE INTO gdn_message_requests VALUES (?,?,?)", (group_id, message_id, row["id"]))
                self.db.execute("""UPDATE requests SET hidden_reason='done' WHERE id=? AND EXISTS
                    (SELECT 1 FROM gdn_message_requests a JOIN whatsapp_messages m
                     ON m.group_id=a.group_id AND m.message_id=a.message_id WHERE a.request_id=? AND m.done=1)""", (row["id"], row["id"]))
            hidden = self.db.execute("SELECT hidden_reason FROM requests WHERE id=?", (row["id"],)).fetchone()[0]
        if hidden:
            return None, "Request was cleared or marked DONE; retained in history."
        return row["id"], "Imported for review." if cursor.rowcount else "Duplicate message already in inbox."

    def observe_messages(self, snapshot):
        """Persist verified message identities and completion before importing."""
        group = snapshot["group_id"]
        with self.db:
            for reply in snapshot.get("replies", []):
                if str(reply.get("text", "")).strip().casefold() != "done" or not reply.get("reply_to"):
                    continue
                self.db.execute("""INSERT INTO whatsapp_messages(group_id,message_id,done,done_reply_id)
                    VALUES (?,?,1,?) ON CONFLICT(group_id,message_id) DO UPDATE SET
                    done=1,done_reply_id=excluded.done_reply_id""", (group, reply["reply_to"], reply["id"]))
            for message in snapshot.get("messages", []) + snapshot.get("observed_originals", []):
                mid, stamp = message["id"], message.get("message_time", "")
                self.db.execute("""INSERT INTO whatsapp_messages(group_id,message_id,message_time)
                    VALUES (?,?,?) ON CONFLICT(group_id,message_id) DO UPDATE SET
                    message_time=CASE WHEN excluded.message_time<>'' THEN excluded.message_time ELSE whatsapp_messages.message_time END""",
                    (group, mid, stamp))
                # Backfill legacy and deduplicated records only from an observed
                # original message with the matching persisted fingerprint.
                self.db.execute("""UPDATE whatsapp_messages SET request_id=coalesce(
                    (SELECT id FROM requests WHERE fingerprint=?),request_id) WHERE group_id=? AND message_id=?""",
                    (content_fingerprint(message["text"]), group, mid))
                self.db.execute("""INSERT OR IGNORE INTO gdn_message_requests
                    SELECT group_id,message_id,request_id FROM whatsapp_messages
                    WHERE group_id=? AND message_id=? AND request_id IS NOT NULL""", (group, mid))
                self.db.execute("""UPDATE requests SET message_time=? WHERE message_time='' AND id IN
                    (SELECT request_id FROM whatsapp_messages WHERE group_id=? AND message_id=?)""", (stamp, group, mid))
            self.db.execute("""UPDATE requests SET hidden_reason='done' WHERE hidden_reason<>'done' AND id IN
                (SELECT a.request_id FROM gdn_message_requests a JOIN whatsapp_messages m
                 ON m.group_id=a.group_id AND m.message_id=a.message_id WHERE m.done=1)""")
        notice = ("A DONE reply could not be linked to its original message; that request remains visible."
                  if snapshot.get("unresolved_done") else "")
        if not snapshot.get("reply_scan_pending") and self.setting("done_reply_notice", "") != notice:
            self.set_settings(done_reply_notice=notice)

    def clear_list(self):
        with self.db:
            return self.db.execute("UPDATE requests SET hidden_reason='cleared' WHERE hidden_reason=''").rowcount

    def known_done_replies(self):
        result = {}
        for row in self.db.execute("SELECT group_id,message_id,done_reply_id FROM whatsapp_messages WHERE done=1 AND done_reply_id<>''"):
            result.setdefault(row["group_id"], {})[row["done_reply_id"]] = row["message_id"]
        return result

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
        return tuple(self.db.execute("SELECT COUNT(*), COALESCE(SUM(action='New'), 0) FROM requests WHERE hidden_reason=''").fetchone())

    def version(self):
        return self.db.execute("PRAGMA data_version").fetchone()[0]

    def records(self, include_hidden=False):
        where = "" if include_hidden else " WHERE hidden_reason=''"
        return [self._decode(row) for row in self.db.execute("SELECT * FROM requests" + where + " ORDER BY id DESC")]

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
            changed = self.db.execute("UPDATE requests SET fields=?, action=? WHERE id=? AND hidden_reason='' AND run_state<>'Running'",
                                      (json.dumps(fields), action, record_id)).rowcount
            if not changed:
                raise ValueError("This request is running, cleared, or marked DONE. Select an idle active request.")

    def related(self, fields, exclude_id=None):
        keys = ("warehouse", "client", "gatepass")
        identity = tuple(str(fields.get(k, "")).strip().casefold() for k in keys)
        if not all(identity):
            return []
        return [r for r in self.records(include_hidden=True) if r["id"] != exclude_id and
                tuple(str(r["fields"].get(k, "")).strip().casefold() for k in keys) == identity]
