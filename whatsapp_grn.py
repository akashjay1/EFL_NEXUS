"""Durable photo capture and local GRN review records, separate from GDN requests."""

import base64
import hashlib
import io
import json
import os
import re
from pathlib import Path
import sqlite3
import threading
import time
from datetime import datetime, timezone

from PIL import Image

from whatsapp_gdn import GDNInboxStore, gatepass_is_active
from grn_cloud_ocr import initialize_cloud_tables, queue_cloud, PENDING_STATES
from whatsapp_media import MEDIA_ADAPTER_JS

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
GRN_WAREHOUSES = ("EGDC", "ESKD", "NUGE", "LPPL", "LPSP", "INMM01")
GRN_SCAN_WINDOW_SECONDS = 60 * 60


def grn_message_epoch(value):
    """Parse the adapter's verified D/M/Y display format in the PC/browser zone.

    Do not substitute capture time when WhatsApp's received time is missing.
    Explicitly zoned ISO timestamps are also accepted for canonical sources.
    """
    text = ' '.join(str(value or '').replace('\u200e', '').replace('\u200f', '').split())
    try:
        stamp = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if stamp.tzinfo is not None:
            return stamp.timestamp()
    except ValueError:
        pass
    if re.fullmatch(r'\d{1,2}:\d{2}(?: [AP]M)?, \d{1,2}/\d{1,2}/\d{4}', text, re.IGNORECASE):
        for pattern in ('%H:%M, %d/%m/%Y', '%I:%M %p, %d/%m/%Y'):
            try:
                return datetime.strptime(text.upper(), pattern).timestamp()
            except (ValueError, OSError, OverflowError):
                pass
    return None


def grn_photo_is_recent(message_time, now=None):
    received = grn_message_epoch(message_time)
    current = time.time() if now is None else now
    return received is not None and 0 <= current - received <= GRN_SCAN_WINDOW_SECONDS


def validate_grn_fields(warehouse, gatepass, warehouses=GRN_WAREHOUSES):
    errors = []
    if warehouse not in warehouses:
        errors.append("Choose a valid GRN Warehouse ID.")
    if not gatepass or not gatepass.isascii() or not gatepass.isdigit():
        errors.append("Enter the printed gate pass using digits only; leading zeroes are preserved.")
    return errors


def fill_grn_request(store, record_id, warehouse, gatepass, lane_name, lanes, *, allow_repeat=False):
    errors = validate_grn_fields(warehouse, gatepass)
    if errors:
        raise ValueError("\n".join(errors))
    record = store.document(record_id)
    if record is None:
        raise ValueError("Select a captured photo first.")
    if record["hidden_reason"]:
        raise ValueError("This photo was cleared or marked DONE. Select an active photo.")
    if record["state"] in ("Pending", "Extracting", "Awaiting original photo", *PENDING_STATES):
        raise ValueError("Wait for extraction to finish before transferring the reviewed number.")
    if store.db.execute("SELECT 1 FROM grn_sources WHERE document_id=? AND capture_refresh=1 LIMIT 1", (record_id,)).fetchone():
        raise ValueError("Wait for original-photo capture before transferring the reviewed number.")
    if record["run_state"] == "Running":
        raise ValueError("This gate pass is running. Wait for it to finish or stop its lane.")
    if record["action"].startswith("Replaced") or (not allow_repeat and
            record["action"].startswith(("Filled:", "Filling:", "Transfer uncertain:"))):
        raise ValueError("This document was already transferred. Check the target lane before processing it again.")
    lane = lanes.get(lane_name)
    if lane is None:
        raise ValueError("Select an available target lane.")
    if lane.queue_running or str(lane.grn_btn.cget("state")) == "disabled":
        raise ValueError(f"{lane_name} is busy. Choose another lane or wait.")
    for other in store.documents(include_hidden=True):
        if (other["id"] != record_id and other["warehouse"] == warehouse and other["gatepass"] == gatepass
                and (other["run_state"] == "Running" or (not allow_repeat and
                     other["action"].startswith(("Filled:", "Filling:", "Transfer uncertain:"))))):
            raise ValueError("This warehouse and gate pass were already transferred from another photo. Check the existing request.")
    if gatepass_is_active(lanes, "GRN", {"warehouse_id": warehouse, "gate_pass_number": gatepass}):
        raise ValueError("This warehouse and gate pass are already in a GRN queue or running.")
    # Persist reviewed inputs and intent before touching a lane. Never start automation here.
    store.save_grn_review(record_id, warehouse, gatepass, f"Filling: {lane_name}")
    try:
        lane.prefill_grn(warehouse=warehouse, gatepass=gatepass)
        lane.set_status(f"Reviewed WhatsApp GRN (GP={gatepass}). Click Create GRN when ready.")
        store.save_grn_review(record_id, warehouse, gatepass, f"Filled: {lane_name}")
    except Exception:
        store.save_grn_review(record_id, warehouse, gatepass, f"Transfer uncertain: {lane_name}")
        raise


class GRNInboxStore(GDNInboxStore):
    def __init__(self, path=None):
        super().__init__(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS grn_documents (
                id INTEGER PRIMARY KEY, image_hash TEXT NOT NULL UNIQUE,
                image_path TEXT NOT NULL, received_at TEXT NOT NULL,
                warehouse TEXT NOT NULL DEFAULT '', gatepass TEXT NOT NULL DEFAULT '',
                extraction TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT 'Pending',
                action TEXT NOT NULL DEFAULT 'New', reviewed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS grn_sources (
                id INTEGER PRIMARY KEY, group_id TEXT NOT NULL, message_id TEXT NOT NULL,
                photo_index INTEGER NOT NULL, source TEXT NOT NULL, warehouse TEXT NOT NULL DEFAULT '',
                document_id INTEGER REFERENCES grn_documents(id), skipped INTEGER NOT NULL DEFAULT 0,
                capture_error TEXT NOT NULL DEFAULT '', next_try REAL NOT NULL DEFAULT 0,
                capture_refresh INTEGER NOT NULL DEFAULT 0,
                UNIQUE(group_id, message_id, photo_index)
            );
        """)
        self.add_columns("grn_sources", {
            "capture_refresh": "INTEGER NOT NULL DEFAULT 0", "incoming_verified": "INTEGER NOT NULL DEFAULT 1",
            "capture_attempts": "INTEGER NOT NULL DEFAULT 0", "message_time": "TEXT NOT NULL DEFAULT ''",
            "captured_at": "TEXT NOT NULL DEFAULT ''", "hidden_reason": "TEXT NOT NULL DEFAULT ''"})
        self.add_columns('grn_sources', {'message_received_at': 'REAL'})
        self.add_columns("grn_documents", {"message_time": "TEXT NOT NULL DEFAULT ''",
                                          "hidden_reason": "TEXT NOT NULL DEFAULT ''",
                                          "run_state": "TEXT NOT NULL DEFAULT 'New'",
                                          "run_id": "TEXT NOT NULL DEFAULT ''",
                                          "ocr_revision": "INTEGER NOT NULL DEFAULT 0"})
        initialize_cloud_tables(self)

    def observe_messages(self, snapshot):
        super().observe_messages(snapshot)
        with self.db:
            self.db.execute("""UPDATE grn_sources SET hidden_reason='done' WHERE hidden_reason<>'done' AND EXISTS
                (SELECT 1 FROM whatsapp_messages m WHERE m.group_id=grn_sources.group_id
                 AND m.message_id=grn_sources.message_id AND m.done=1)""")
            self.db.execute("""UPDATE grn_documents SET hidden_reason='done' WHERE hidden_reason<>'done' AND id IN
                (SELECT document_id FROM grn_sources WHERE hidden_reason='done')""")

    def clear_list(self):
        with self.db:
            count = self.db.execute("SELECT count(*) FROM grn_documents WHERE hidden_reason=''").fetchone()[0]
            count += self.db.execute("SELECT count(*) FROM grn_sources WHERE hidden_reason='' AND skipped=0 AND document_id IS NULL").fetchone()[0]
            self.db.execute("UPDATE grn_documents SET hidden_reason='cleared' WHERE hidden_reason=''")
            self.db.execute("UPDATE grn_sources SET hidden_reason='cleared' WHERE hidden_reason='' AND skipped=0")
        return count

    def grn_new_count(self):
        return self.db.execute("""SELECT
            (SELECT count(*) FROM grn_documents WHERE action='New' AND hidden_reason='') +
            (SELECT count(*) FROM grn_sources WHERE skipped=0 AND hidden_reason='' AND document_id IS NULL)""").fetchone()[0]

    def default_warehouse(self, group_id):
        return self.setting("grn_warehouses", {}).get(group_id, "")

    def set_default_warehouse(self, group_id, warehouse):
        if warehouse not in GRN_WAREHOUSES:
            raise ValueError("Choose a valid GRN warehouse.")
        mapping = self.setting("grn_warehouses", {})
        mapping[group_id] = warehouse
        self.set_settings(grn_warehouses=mapping)
        with self.db:
            self.db.execute("UPDATE grn_sources SET warehouse=? WHERE group_id=? AND warehouse=''", (warehouse, group_id))
            self.db.execute("""UPDATE grn_documents SET warehouse=? WHERE warehouse='' AND reviewed=0
                AND id IN (SELECT document_id FROM grn_sources WHERE group_id=?)""", (warehouse, group_id))

    def discover(self, snapshot, baseline=False, import_visible=False, recent_only=False):
        self.observe_messages(snapshot)
        group = snapshot["group_id"]
        warehouse = self.default_warehouse(group)
        now = time.time()
        counts = {'eligible': 0, 'outside_window': 0, 'unknown_time': 0}
        with self.db:
            # Keep uncertain senders visible, without treating their media as
            # incoming or allowing it through to OCR/form filling.
            candidates = [(p, 1) for p in snapshot.get("photos", [])]
            candidates += [(p, 0) for p in snapshot.get("unclassifiedPhotos", [])]
            for photo, verified in candidates:
                received = grn_message_epoch(photo.get('message_time', ''))
                if recent_only and (received is None or not 0 <= now - received <= GRN_SCAN_WINDOW_SECONDS):
                    counts['unknown_time' if received is None else 'outside_window'] += 1
                    continue
                counts['eligible'] += 1
                args = (group, photo["message_id"], photo["index"])
                self.db.execute("""INSERT INTO grn_sources
                    (group_id,message_id,photo_index,source,warehouse,skipped,incoming_verified,message_time,captured_at,hidden_reason,message_received_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(group_id,message_id,photo_index) DO UPDATE SET
                    incoming_verified=max(grn_sources.incoming_verified,excluded.incoming_verified),
                    message_time=CASE WHEN excluded.message_time<>'' THEN excluded.message_time ELSE grn_sources.message_time END,
                    message_received_at=CASE WHEN excluded.message_time<>'' THEN excluded.message_received_at ELSE grn_sources.message_received_at END""",
                    (*args, snapshot["name"], warehouse, int(baseline), verified, photo.get("message_time", ""),
                     datetime.now(timezone.utc).isoformat(), "done" if self.db.execute(
                         "SELECT 1 FROM whatsapp_messages WHERE group_id=? AND message_id=? AND done=1", args[:2]).fetchone() else "", received))
                self.db.execute("""UPDATE grn_documents SET message_time=? WHERE message_time='' AND id IN
                    (SELECT document_id FROM grn_sources WHERE group_id=? AND message_id=? AND photo_index=?)""",
                    (photo.get("message_time", ""), *args))
                if import_visible:
                    self.db.execute("""UPDATE grn_sources SET skipped=0,next_try=0,warehouse=?
                        WHERE group_id=? AND message_id=? AND photo_index=? AND document_id IS NULL AND hidden_reason=''""", (warehouse, *args))
        return counts

    def pending_capture(self, group_id, limit=1, exclude_ids=(), visible_ids=None, owner_id=None, recent_only=False):
        query = """SELECT * FROM grn_sources WHERE group_id=? AND incoming_verified=1
            AND skipped=0 AND hidden_reason='' AND (document_id IS NULL OR capture_refresh=1) AND next_try<=?
            AND NOT EXISTS (SELECT 1 FROM whatsapp_messages m WHERE m.group_id=grn_sources.group_id
                            AND m.message_id=grn_sources.message_id AND m.done=1)
            AND NOT EXISTS (SELECT 1 FROM grn_documents d WHERE d.id=grn_sources.document_id AND d.hidden_reason<>'')"""
        args = [group_id, time.time()]
        if recent_only:
            query += ' AND message_received_at BETWEEN ? AND ?'
            args.extend((args[1] - GRN_SCAN_WINDOW_SECONDS, args[1]))
        if owner_id is not None:
            query += ' AND id=?'
            args.append(owner_id)
        for column, values, operator in (("id", exclude_ids, "NOT IN"),
                                          ("message_id", visible_ids, "IN")):
            if values is not None:
                values = tuple(values)
                if not values:
                    if operator == "IN":
                        return []
                    continue
                query += f" AND {column} {operator} ({','.join('?' for _ in values)})"
                args.extend(values)
        query += " ORDER BY next_try,id LIMIT ?"
        return [dict(r) for r in self.db.execute(query, (*args, int(limit)))]

    def pending_entries(self):
        """List durable detections immediately, before download or OCR completes."""
        return [dict(r) for r in self.db.execute("""SELECT * FROM grn_sources
            WHERE skipped=0 AND hidden_reason='' AND document_id IS NULL ORDER BY id DESC""")]

    def capture_failed(self, source_id, error):
        row = self.db.execute("SELECT capture_attempts FROM grn_sources WHERE id=?", (source_id,)).fetchone()
        attempts = row[0] if row else 0
        delay = (1, 2, 5, 15, 30)[min(attempts, 4)]
        with self.db:
            self.db.execute("UPDATE grn_sources SET capture_error=?,next_try=?,capture_attempts=capture_attempts+1 WHERE id=? AND hidden_reason=''",
                            (str(error)[:500], time.time() + delay, source_id))

    def capture_waiting(self, source_id, detail):
        with self.db:
            self.db.execute("UPDATE grn_sources SET capture_error=?,next_try=? WHERE id=? AND hidden_reason=''",
                            (str(detail)[:500], time.time() + .25, source_id))

    def save_image(self, source_id, encoded):
        source = self.db.execute("SELECT * FROM grn_sources WHERE id=?", (source_id,)).fetchone()
        if source is None or source["hidden_reason"]:
            raise ValueError("Photo source was cleared or marked DONE.")
        if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 4:
            raise ValueError("Photo exceeds the 20 MB capture limit.")
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Photo exceeds the 20 MB capture limit.")
        with Image.open(io.BytesIO(data)) as picture:
            if picture.width * picture.height > MAX_IMAGE_PIXELS:
                raise ValueError("Photo exceeds the 30 megapixel limit.")
            if picture.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Unsupported photo format; send a JPEG, PNG or WebP photo.")
            picture.verify()
        digest = hashlib.sha256(data).hexdigest()
        folder = self.path.parent / "grn_images"
        folder.mkdir(exist_ok=True)
        destination = folder / (digest + ".image")
        # Atomic replacement, with each process owning a distinct temporary file.
        temporary = destination.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        with self.db:
            # Serialize the visibility check and final insert/link with Clear
            # List and DONE updates from the UI/monitor's other connections.
            self.db.execute("BEGIN IMMEDIATE")
            source = self.db.execute("SELECT * FROM grn_sources WHERE id=?", (source_id,)).fetchone()
            if source is None or source["hidden_reason"]:
                raise ValueError("Photo source was cleared or marked DONE.")
            if self.db.execute("SELECT 1 FROM whatsapp_messages WHERE group_id=? AND message_id=? AND done=1",
                               (source["group_id"], source["message_id"])).fetchone():
                raise ValueError("Photo source was marked DONE.")
            if source["document_id"] and self.document(source["document_id"])["hidden_reason"]:
                raise ValueError("Photo was cleared or marked DONE.")
            if source["capture_refresh"] and source["document_id"]:
                previous = self.document(source["document_id"])
                if previous["reviewed"] or previous["action"] != "New":
                    raise ValueError("A saved review cannot be replaced by capture. Keep the reviewed values.")
                duplicate = self.db.execute("SELECT id FROM grn_documents WHERE image_hash=?", (digest,)).fetchone()
                if duplicate is None or duplicate[0] == previous["id"]:
                    self.db.execute("""UPDATE grn_documents SET image_hash=?,image_path=?,extraction='{}',
                        gatepass='',state='Pending',ocr_revision=ocr_revision+1 WHERE id=?""", (digest, str(destination), previous["id"]))
                else:
                    self.db.execute("UPDATE grn_documents SET action='Replaced by another captured photo',state='Replaced' WHERE id=?", (previous["id"],))
            self.db.execute("""INSERT INTO grn_documents (image_hash,image_path,received_at,warehouse,message_time)
                VALUES (?,?,?,?,?) ON CONFLICT(image_hash) DO NOTHING""",
                (digest, str(destination), datetime.now(timezone.utc).isoformat(), source["warehouse"], source["message_time"]))
            record_id = self.db.execute("SELECT id FROM grn_documents WHERE image_hash=?", (digest,)).fetchone()[0]
            self.db.execute("UPDATE grn_sources SET document_id=?,capture_error='',capture_refresh=0,capture_attempts=0,next_try=0 WHERE id=?", (record_id, source_id))
        return record_id

    def documents(self, include_hidden=False):
        where = "" if include_hidden else " WHERE d.hidden_reason=''"
        return [self.decode(r) for r in self.db.execute("""SELECT d.*,
            (SELECT source FROM grn_sources WHERE document_id=d.id ORDER BY id LIMIT 1) AS source,
            (SELECT count(*) FROM grn_sources WHERE document_id=d.id) AS copies
            FROM grn_documents d""" + where + " ORDER BY d.id DESC")]

    @staticmethod
    def decode(row):
        result = dict(row)
        result["extraction"] = json.loads(result["extraction"])
        return result

    def document(self, record_id):
        row = self.db.execute("SELECT * FROM grn_documents WHERE id=?", (record_id,)).fetchone()
        return self.decode(row) if row else None

    def save_grn_review(self, record_id, warehouse, gatepass, action="Reviewed"):
        with self.db:
            changed = self.db.execute("UPDATE grn_documents SET warehouse=?,gatepass=?,reviewed=1,action=? WHERE id=? AND hidden_reason='' AND run_state<>'Running'",
                                      (warehouse, gatepass, action, record_id)).rowcount
            if not changed:
                raise ValueError("This photo is running, cleared, or marked DONE. Select an idle active photo.")

    def retry(self, record_id=None):
        with self.db:
            if record_id is not None:
                self.db.execute("UPDATE grn_documents SET state='Pending',ocr_revision=ocr_revision+1 WHERE id=? AND hidden_reason='' AND state<>'Awaiting original photo' AND run_state<>'Running' AND action NOT LIKE 'Filled:%'", (record_id,))
            self.db.execute("UPDATE grn_sources SET next_try=0,capture_attempts=0 WHERE skipped=0 AND hidden_reason='' AND (document_id IS NULL OR capture_refresh=1)")

    def refresh_photo(self, record_id, recent_only=False):
        record = self.document(record_id)
        if record is None or record["hidden_reason"] or record["reviewed"] or record["action"] != "New":
            raise ValueError("Only an unreviewed photo can be recaptured. Saved review values are preserved.")
        if recent_only and not any(grn_photo_is_recent(row['message_time']) for row in self.db.execute(
                'SELECT message_time FROM grn_sources WHERE document_id=?', (record_id,))):
            raise ValueError('Only GRN photos received within the last hour can be captured. The received time must be available.')
        if record["state"] in ("Pending", "Extracting"):
            raise ValueError("Wait for extraction to finish before recapturing the photo.")
        with self.db:
            self.db.execute("UPDATE grn_documents SET state='Awaiting original photo' WHERE id=?", (record_id,))
            self.db.execute("UPDATE grn_sources SET capture_refresh=1,next_try=0 WHERE document_id=?", (record_id,))

    def capture_errors(self):
        return [dict(r) for r in self.db.execute("""SELECT id,source,capture_error FROM grn_sources
            WHERE skipped=0 AND hidden_reason='' AND (document_id IS NULL OR capture_refresh=1) AND capture_error<>'' ORDER BY id DESC""")]


class GRNExtractionWorker:
    def __init__(self, db_path, stopping):
        self.db_path, self.stopping = db_path, stopping
        self.thread = threading.Thread(target=self.run, name="GRN OCR", daemon=True)

    def run(self):
        from grn_ocr import extract_gatepass
        store = GRNInboxStore(self.db_path)
        try:
            store.set_settings(grn_ocr_status="Starting local OCR worker")
            with store.db:
                store.db.execute("UPDATE grn_documents SET state='Pending' WHERE state='Extracting'")
            while not self.stopping.is_set():
                row = store.db.execute("SELECT * FROM grn_documents WHERE state='Pending' AND hidden_reason='' ORDER BY id LIMIT 1").fetchone()
                if row is None:
                    self.stopping.wait(1)
                    continue
                with store.db:
                    changed = store.db.execute("UPDATE grn_documents SET state='Extracting' WHERE id=? AND ocr_revision=? AND state='Pending' AND hidden_reason=''", (row["id"], row['ocr_revision'])).rowcount
                if not changed:
                    continue
                store.set_settings(grn_ocr_status=f"Extracting photo {row['id']}")
                try:
                    result = extract_gatepass(row["image_path"], store.path.parent / "grn_images" / row["image_hash"])
                    state = "Ready for review"
                except Exception as exc:
                    result = {"gatepass": "", "warnings": [f"Extraction failed: {str(exc)[:500]}"]}
                    state = "Extraction failed"
                with store.db:
                    # Retrying OCR must never overwrite a user's saved correction or transfer status.
                    changed = store.db.execute("""UPDATE grn_documents SET state=?,extraction=?,
                        gatepass=CASE WHEN reviewed=0 THEN ? ELSE gatepass END
                        WHERE id=? AND hidden_reason='' AND image_hash=? AND ocr_revision=? AND state='Extracting'""",
                        (state, json.dumps(result), result["gatepass"], row["id"], row['image_hash'], row['ocr_revision'])).rowcount
                    if changed and (not result['gatepass'] or result.get('warnings')):
                        queue_cloud(store, row['id'], row['image_hash'], row['ocr_revision'])
                store.set_settings(grn_ocr_status="Local OCR worker ready")
        except Exception as exc:
            try:
                store.set_settings(grn_ocr_status=f"OCR worker stopped: {type(exc).__name__}: {str(exc)[:200]}. Reconnect WhatsApp to retry.")
            except sqlite3.Error:
                pass
        finally:
            store.close()


def photo_read_script(group_id, message_id, index):
    """Load this message's full viewer image; never copy the chat thumbnail."""
    return r"""(async () => {
        /*NEXUS_MEDIA_ADAPTER*/
        const groupId=%s, messageId=%s, photoIndex=%d;
        const waiting=error=>({error,waiting:true});
        if(window.__nexusDoneNavigation) return waiting('Checking DONE reply links before opening photos.');
        const title=()=>document.querySelector('#main [data-testid="conversation-info-header-chat-title-name"]');
        const validGroup=()=>{
            const header=title(),side=document.querySelector('#pane-side');
            if(!header || 'name:'+header.textContent.trim()!==groupId || !side) return false;
            const matches=[...side.querySelectorAll('span[title]')].filter(e=>e.getAttribute('title')===header.textContent.trim());
            const selected=[...side.querySelectorAll('[aria-selected="true"]')];
            return matches.length===1 && selected.length===1 && selected[0].contains(matches[0]);
        };
        if(location.origin!=='https://web.whatsapp.com' || !validGroup())
            return {error:'Return to the selected group to load the original photo.'};
        const row=[...document.querySelectorAll('#main '+nexusMedia.rows)]
            .find(e=>e.getAttribute('data-id')===messageId);
        const thumb=row && nexusPhotoThumbs(row)[photoIndex];
        let owner=window.__nexusGrnOriginal;
        if(!thumb && !owner) return {error:row?'Photo markup is unsupported or this album item is not loaded. Reopen the message and retry capture.':'Photo message is outside the rendered history. Open its message to complete capture.'};
        let modal=document.querySelector(nexusMedia.viewer);
        const finish=close=>{
            if(!owner || window.__nexusGrnOriginal!==owner) return;
            owner.events.abort();
            if(close && !owner.interrupted && owner.modal?.isConnected && validGroup()) {
                const buttons=[...owner.modal.querySelectorAll('button,[role="button"]')]
                    .filter(e=>e.getAttribute('aria-label')==='Close');
                if(buttons.length===1) buttons[0].click();
            }
            delete window.__nexusGrnOriginal;
        };
        if(owner && owner.interrupted){finish(false);return waiting('Photo loading paused while you use the WhatsApp viewer. Close it to continue.');}
        if(owner && Date.now()-owner.started>12000){finish(true);return {error:'Original photo did not finish loading. Capture will retry.'};}
        if(owner && (owner.messageId!==messageId || owner.photoIndex!==photoIndex || owner.groupId!==groupId))
            return waiting('Waiting for another original photo to finish loading.');
        if(!owner){
            if(modal) return waiting('Close WhatsApp?s photo viewer to let automatic original-photo capture continue.');
            owner={groupId,messageId,photoIndex,started:Date.now(),events:new AbortController(),modal:null,interrupted:false};
            window.__nexusGrnOriginal=owner;
            const interrupt=e=>{if(e.isTrusted && document.querySelector(nexusMedia.viewer)?.contains(e.target)) owner.interrupted=true;};
            document.addEventListener('pointerdown',interrupt,{capture:true,signal:owner.events.signal});
            document.addEventListener('keydown',interrupt,{capture:true,signal:owner.events.signal});
            thumb.click();
            modal=document.querySelector(nexusMedia.viewer);
            owner.modal=modal;
            return waiting('Loading the original photo from WhatsApp.');
        }
        if(!modal){finish(false);return waiting('Opening original photo. Capture will retry.');}
        if(owner.modal && owner.modal!==modal){finish(false);return waiting('WhatsApp?s photo viewer changed. Close it to continue capture.');}
        owner.modal=modal;
        const full=[...modal.querySelectorAll(nexusMedia.original)].filter(img=>{
            if(!img.complete || img.naturalWidth<300 || img.naturalHeight<300 || !(img.currentSrc||img.src).startsWith('blob:https://web.whatsapp.com/')) return false;
            for(let e=img;e && e!==modal;e=e.parentElement){
                const s=getComputedStyle(e);
                if(s.filter!=='none' || s.visibility==='hidden' || s.display==='none' || Number(s.opacity)===0) return false;
            }
            return true;
        });
        if(full.length!==1) return waiting('Waiting for WhatsApp to load the full photo, rather than its blurred preview.');
        const img=full[0],src=img.currentSrc||img.src;
        const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),10000);
        try {
            const response=await fetch(src,{signal:abort.signal});
            if(!response.ok) throw Error('Original photo could not be retrieved.');
            const blob=await response.blob();
            if(blob.size>%d) throw Error('Photo exceeds the 20 MB capture limit.');
            const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('Photo read failed.'));r.readAsDataURL(blob);});
            if(!validGroup() || owner.interrupted || !modal.isConnected || (img.currentSrc||img.src)!==src)
                throw Error('The group or photo changed during capture. Retry in the selected group.');
            return {data:data.slice(data.indexOf(',')+1),width:img.naturalWidth,height:img.naturalHeight,quality:'full_viewer'};
        } catch(e){return {error:String(e.message||e)};}
        finally{clearTimeout(timer);finish(true);}
    })()""".replace('/*NEXUS_MEDIA_ADAPTER*/', MEDIA_ADAPTER_JS) % (json.dumps(group_id), json.dumps(message_id), int(index), MAX_IMAGE_BYTES)
