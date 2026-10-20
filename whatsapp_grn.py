"""Durable photo capture and local GRN review records, separate from GDN requests."""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from datetime import datetime, timezone

from PIL import Image

from whatsapp_gdn import GDNInboxStore

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
GRN_WAREHOUSES = ("EGDC", "ESKD", "NUGE", "LPPL", "LPSP", "INMM01")


def validate_grn_fields(warehouse, gatepass, warehouses=GRN_WAREHOUSES):
    errors = []
    if warehouse not in warehouses:
        errors.append("Choose a valid GRN Warehouse ID.")
    if not gatepass or not gatepass.isascii() or not gatepass.isdigit():
        errors.append("Enter the printed gate pass using digits only; leading zeroes are preserved.")
    return errors


def fill_grn_request(store, record_id, warehouse, gatepass, lane_name, lanes):
    errors = validate_grn_fields(warehouse, gatepass)
    if errors:
        raise ValueError("\n".join(errors))
    record = store.document(record_id)
    if record is None:
        raise ValueError("Select a captured photo first.")
    if record["state"] in ("Pending", "Extracting", "Awaiting original photo"):
        raise ValueError("Wait for extraction to finish before transferring the reviewed number.")
    if store.db.execute("SELECT 1 FROM grn_sources WHERE document_id=? AND capture_refresh=1 LIMIT 1", (record_id,)).fetchone():
        raise ValueError("Wait for original-photo capture before transferring the reviewed number.")
    if record["action"].startswith(("Filled:", "Filling:", "Transfer uncertain:", "Replaced")):
        raise ValueError("This document was already transferred. Check the target lane before processing it again.")
    lane = lanes.get(lane_name)
    if lane is None:
        raise ValueError("Select an available target lane.")
    if lane.queue_running or str(lane.grn_btn.cget("state")) == "disabled":
        raise ValueError(f"{lane_name} is busy. Choose another lane or wait.")
    for other in store.documents():
        if (other["id"] != record_id and other["warehouse"] == warehouse and other["gatepass"] == gatepass
                and other["action"].startswith(("Filled:", "Filling:", "Transfer uncertain:"))):
            raise ValueError("This warehouse and gate pass were already transferred from another photo. Check the existing request.")
    if any(item["doc_type"] == "GRN" and str(item["warehouse_id"]).strip().upper() == warehouse
           and str(item["gate_pass_number"]).strip() == gatepass
           for other_lane in lanes.values() for item in other_lane.queue):
        raise ValueError("This warehouse and gate pass are already in a GRN queue.")
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
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(grn_sources)")}
        if "capture_refresh" not in columns:
            with self.db:
                self.db.execute("ALTER TABLE grn_sources ADD COLUMN capture_refresh INTEGER NOT NULL DEFAULT 0")

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

    def discover(self, snapshot, baseline=False, import_visible=False):
        group = snapshot["group_id"]
        warehouse = self.default_warehouse(group)
        with self.db:
            for photo in snapshot.get("photos", []):
                args = (group, photo["message_id"], photo["index"])
                self.db.execute("""INSERT INTO grn_sources
                    (group_id,message_id,photo_index,source,warehouse,skipped) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(group_id,message_id,photo_index) DO NOTHING""",
                    (*args, snapshot["name"], warehouse, int(baseline)))
                if import_visible:
                    self.db.execute("""UPDATE grn_sources SET skipped=0,next_try=0,warehouse=?
                        WHERE group_id=? AND message_id=? AND photo_index=? AND document_id IS NULL""", (warehouse, *args))

    def pending_capture(self, group_id):
        return [dict(r) for r in self.db.execute("""SELECT * FROM grn_sources WHERE group_id=?
            AND skipped=0 AND (document_id IS NULL OR capture_refresh=1) AND next_try<=? ORDER BY id LIMIT 1""", (group_id, time.time()))]

    def capture_failed(self, source_id, error):
        with self.db:
            self.db.execute("UPDATE grn_sources SET capture_error=?,next_try=? WHERE id=?",
                            (str(error)[:500], time.time() + 30, source_id))

    def save_image(self, source_id, encoded):
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
            source = self.db.execute("SELECT * FROM grn_sources WHERE id=?", (source_id,)).fetchone()
            if source is None:
                raise ValueError("Photo source no longer exists.")
            if source["capture_refresh"] and source["document_id"]:
                previous = self.document(source["document_id"])
                if previous["reviewed"] or previous["action"] != "New":
                    raise ValueError("A saved review cannot be replaced by capture. Keep the reviewed values.")
                duplicate = self.db.execute("SELECT id FROM grn_documents WHERE image_hash=?", (digest,)).fetchone()
                if duplicate is None or duplicate[0] == previous["id"]:
                    self.db.execute("""UPDATE grn_documents SET image_hash=?,image_path=?,extraction='{}',
                        gatepass='',state='Pending' WHERE id=?""", (digest, str(destination), previous["id"]))
                else:
                    self.db.execute("UPDATE grn_documents SET action='Replaced by another captured photo',state='Replaced' WHERE id=?", (previous["id"],))
            self.db.execute("""INSERT INTO grn_documents (image_hash,image_path,received_at,warehouse)
                VALUES (?,?,?,?) ON CONFLICT(image_hash) DO NOTHING""",
                (digest, str(destination), datetime.now(timezone.utc).isoformat(), source["warehouse"]))
            record_id = self.db.execute("SELECT id FROM grn_documents WHERE image_hash=?", (digest,)).fetchone()[0]
            self.db.execute("UPDATE grn_sources SET document_id=?,capture_error='',capture_refresh=0 WHERE id=?", (record_id, source_id))
        return record_id

    def documents(self):
        return [self.decode(r) for r in self.db.execute("""SELECT d.*,
            (SELECT source FROM grn_sources WHERE document_id=d.id ORDER BY id LIMIT 1) AS source,
            (SELECT count(*) FROM grn_sources WHERE document_id=d.id) AS copies
            FROM grn_documents d ORDER BY d.id DESC""")]

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
            self.db.execute("UPDATE grn_documents SET warehouse=?,gatepass=?,reviewed=1,action=? WHERE id=?",
                            (warehouse, gatepass, action, record_id))

    def retry(self, record_id=None):
        with self.db:
            if record_id is not None:
                self.db.execute("UPDATE grn_documents SET state='Pending' WHERE id=? AND action NOT LIKE 'Filled:%'", (record_id,))
            self.db.execute("UPDATE grn_sources SET next_try=0 WHERE skipped=0 AND (document_id IS NULL OR capture_refresh=1)")

    def refresh_photo(self, record_id):
        record = self.document(record_id)
        if record is None or record["reviewed"] or record["action"] != "New":
            raise ValueError("Only an unreviewed photo can be recaptured. Saved review values are preserved.")
        if record["state"] in ("Pending", "Extracting"):
            raise ValueError("Wait for extraction to finish before recapturing the photo.")
        with self.db:
            self.db.execute("UPDATE grn_documents SET state='Awaiting original photo' WHERE id=?", (record_id,))
            self.db.execute("UPDATE grn_sources SET capture_refresh=1,next_try=0 WHERE document_id=?", (record_id,))

    def capture_errors(self):
        return [dict(r) for r in self.db.execute("""SELECT id,source,capture_error FROM grn_sources
            WHERE skipped=0 AND (document_id IS NULL OR capture_refresh=1) AND capture_error<>'' ORDER BY id DESC""")]


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
                row = store.db.execute("SELECT * FROM grn_documents WHERE state='Pending' ORDER BY id LIMIT 1").fetchone()
                if row is None:
                    self.stopping.wait(1)
                    continue
                with store.db:
                    store.db.execute("UPDATE grn_documents SET state='Extracting' WHERE id=?", (row["id"],))
                store.set_settings(grn_ocr_status=f"Extracting photo {row['id']}")
                try:
                    result = extract_gatepass(row["image_path"], store.path.parent / "grn_images" / row["image_hash"])
                    state = "Ready for review"
                except Exception as exc:
                    result = {"gatepass": "", "warnings": [f"Extraction failed: {str(exc)[:500]}"]}
                    state = "Extraction failed"
                with store.db:
                    # Retrying OCR must never overwrite a user's saved correction or transfer status.
                    store.db.execute("""UPDATE grn_documents SET state=?,extraction=?,
                        gatepass=CASE WHEN reviewed=0 THEN ? ELSE gatepass END WHERE id=?""",
                        (state, json.dumps(result), result["gatepass"], row["id"]))
                store.set_settings(grn_ocr_status="Local OCR worker ready")
        except Exception as exc:
            try:
                store.set_settings(grn_ocr_status=f"OCR worker stopped: {type(exc).__name__}: {str(exc)[:200]}. Reconnect WhatsApp to retry.")
            except sqlite3.Error:
                pass
        finally:
            store.close()


def photo_read_script(group_id, message_id, index):
    """Read only an observed message's locally rendered image; never fetch a private endpoint."""
    return r"""(async () => {
        if (location.origin !== 'https://web.whatsapp.com') return {error:'WhatsApp is not open.'};
        const title = document.querySelector('#main [data-testid="conversation-info-header-chat-title-name"]');
        if (!title || 'name:'+title.textContent.trim() !== %s) return {error:'Return to the selected group.'};
        const name=title.textContent.trim(), side=document.querySelector('#pane-side');
        const matches=side ? [...side.querySelectorAll('span[title]')].filter(e=>e.getAttribute('title')===name) : [];
        const selected=side ? [...side.querySelectorAll('[aria-selected="true"]')] : [];
        if(matches.length!==1 || selected.length!==1 || !selected[0].contains(matches[0]))
            return {error:'Selected group cannot be verified. Return to the saved group and retry.'};
        const row = [...document.querySelectorAll('#main [data-id][data-testid^="conv-msg-"]')]
            .find(r=>r.getAttribute('data-id') === %s);
        if (!row) return {error:'Photo is no longer visible. Open its message, then retry capture.'};
        const thumbs = [...row.querySelectorAll('[data-testid="image-thumb"]')]
            .filter(e=>!e.closest('[data-testid="quoted-message"]'));
        const thumb=thumbs[%d];
        // Allow lazy-loaded media to settle before selecting the image. Capture
        // remains asynchronous so this does not block text monitoring.
        await new Promise(resolve=>setTimeout(resolve,3000));
        const img=thumb && [...thumb.querySelectorAll('[data-testid="media-url-provider"] img')]
            .sort((a,b)=>b.naturalWidth*b.naturalHeight-a.naturalWidth*a.naturalHeight)[0];
        if (!img || !img.complete || img.naturalWidth < 300 || img.naturalHeight < 300)
            return {error:'Full photo is not loaded. Open the photo in WhatsApp, close it, then retry capture.'};
        const src=img.currentSrc || img.src;
        if (!src.startsWith('blob:https://web.whatsapp.com/')) return {error:'Full photo is not available as local media yet. Open it and retry.'};
        const abort=new AbortController(), timer=setTimeout(()=>abort.abort(),10000);
        try {
            const response=await fetch(src,{signal:abort.signal});
            if(!response.ok) throw Error('Photo could not be retrieved.');
            const blob=await response.blob();
            if(blob.size > %d) throw Error('Photo exceeds the 20 MB capture limit.');
            const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('Photo read failed.'));r.readAsDataURL(blob);});
            // A navigation during retrieval invalidates the result.
            const now=document.querySelector('#main [data-testid="conversation-info-header-chat-title-name"]');
            if(!now || 'name:'+now.textContent.trim() !== %s) throw Error('Group changed during capture. Retry in the selected group.');
            return {data:data.slice(data.indexOf(',')+1),width:img.naturalWidth,height:img.naturalHeight};
        } catch(e) {return {error:String(e.message || e)};} finally {clearTimeout(timer);}
    })()""" % (json.dumps(group_id), json.dumps(message_id), int(index), MAX_IMAGE_BYTES, json.dumps(group_id))
