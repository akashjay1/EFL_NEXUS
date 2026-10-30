"""GRN photo review. Capture and OCR never invoke the Korber automation."""

import sqlite3
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

from whatsapp_grn import GRNInboxStore, GRN_WAREHOUSES, fill_grn_request, validate_grn_fields, grn_photo_is_recent, grn_message_epoch
from whatsapp_gdn import launch_gatepass, received_label, recover_gatepass_runs
from grn_cloud_ocr import PENDING_STATES, cloud_settings, retry_cloud, usage_today
from grn_ocr_settings import GRNOCRSettings


class WhatsAppGRNInbox:
    def __init__(self, root, container, controller, lanes, ensure_lanes=None):
        self.root, self.controller, self.lanes, self.ensure_lanes = root, controller, lanes, ensure_lanes
        self.store = GRNInboxStore(controller.store.path)
        recover_gatepass_runs(self.store, self.lanes, "GRN")
        self.selected_id = None
        self._run_states = {}
        self.selected_source_id = None
        self.closed = False
        self.after_id = None
        self.selected_revision = None
        self.dirty = False
        self.loading = False
        self.frame = ttk.Frame(container, padding=12)
        self.frame.pack(fill="both", expand=True)
        self.frame.bind("<Destroy>", self._destroyed, add="+")
        self.status = tk.StringVar(value="Review the photo and number before filling or running a GRN. Run Gatepass starts the selected lane's GRN flow.")
        self.capture_status = tk.StringVar()
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x")
        ttk.Button(bar, text="Scan GRN", command=self.import_visible).pack(side="left")
        ttk.Button(bar, text="Retry Capture", command=self.retry_capture).pack(side="left", padx=6)
        ttk.Button(bar, text="Clear List", command=self.clear_list).pack(side="left")
        ttk.Button(bar, text='OCR Settings', command=lambda: GRNOCRSettings(self.root, self.store)).pack(side='left', padx=6)
        ttk.Button(bar, text='Retry Cloud', command=self.retry_cloud).pack(side='left')
        ttk.Label(bar, text="Scans loaded GRN photos received within the last hour.").pack(side="left", padx=8)
        ttk.Label(self.frame, textvariable=self.capture_status, wraplength=1300, foreground="#b45309").pack(anchor="w", pady=6)
        panes = ttk.Panedwindow(self.frame, orient="horizontal")
        panes.pack(fill="both", expand=True)
        listing, original, details = ttk.Frame(panes), ttk.Frame(panes, padding=10), ttk.Frame(panes, padding=10)
        panes.add(listing, weight=2)
        panes.add(original, weight=3)
        panes.add(details, weight=2)
        self.tree = ttk.Treeview(listing, columns=("gatepass", "state", "run_state", "received"), show="headings", selectmode="browse")
        self.tree.heading("gatepass", text="Gate Pass")
        self.tree.heading("state", text="Status")
        self.tree.column("gatepass", width=95, minwidth=70)
        self.tree.column("state", width=150, minwidth=100)
        self.tree.heading("run_state", text="State")
        self.tree.column("run_state", width=95, minwidth=80)
        self.tree.heading("received", text="Received")
        self.tree.column("received", width=195, minwidth=130)
        scroll = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        ttk.Label(original, text="Original photo", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.original = ttk.Label(original, text="Select a photo", anchor="center")
        self.original.pack(fill="both", expand=True, pady=8)
        ttk.Button(original, text="View Full Photo", command=self.view_original).pack(anchor="w")
        ttk.Label(details, text="Detected header", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.crop = ttk.Label(details, text="Header crop appears after extraction", anchor="center")
        self.crop.pack(fill="x", pady=(6, 16))
        self.warehouse = tk.StringVar()
        self.gatepass = tk.StringVar()
        ttk.Label(details, text="Warehouse ID").pack(anchor="w")
        ttk.Combobox(details, textvariable=self.warehouse, values=GRN_WAREHOUSES, state="readonly").pack(fill="x", pady=(3, 10))
        ttk.Label(details, text="Gate Pass Number").pack(anchor="w")
        ttk.Entry(details, textvariable=self.gatepass, font=("Segoe UI", 15)).pack(fill="x", pady=(3, 10))
        self.warehouse.trace_add("write", self._edited)
        self.gatepass.trace_add("write", self._edited)
        self.confirmed = tk.BooleanVar()
        ttk.Checkbutton(details, text="I checked the number and warehouse", variable=self.confirmed).pack(anchor="w", pady=6)
        self.warnings = tk.StringVar(value="Select a document to review.")
        ttk.Label(details, textvariable=self.warnings, wraplength=370, foreground="#b45309").pack(fill="x", pady=8)
        ttk.Label(details, text="Target lane").pack(anchor="w")
        self.lane = ttk.Combobox(details, values=list(lanes), state="readonly")
        self.lane.pack(fill="x", pady=(3, 10))
        if lanes:
            self.lane.current(0)
        ttk.Button(details, text="Save Review", command=self.save_review).pack(fill="x", pady=3)
        ttk.Button(details, text="Fill GRN Form", command=self.fill_form).pack(fill="x", pady=3)
        ttk.Button(details, text="Run Gatepass", command=lambda: self.fill_form(start_run=True)).pack(fill="x", pady=3)
        ttk.Button(details, text="Retry Extraction", command=self.retry_extraction).pack(fill="x", pady=3)
        ttk.Label(self.frame, textvariable=self.status, wraplength=1400).pack(fill="x", pady=(10, 0))
        self.version = -1
        self._poll()

    def _edited(self, *_):
        if not self.loading:
            self.dirty = True
            self.confirmed.set(False)

    def _poll(self):
        if self.closed:
            return
        try:
            version = self.store.version()
            if version != self.version:
                self.version = version
                self.refresh()
            errors = self.store.capture_errors()
            notice = self.store.setting("grn_capture_notice", "")
            ocr_status = self.store.setting("grn_ocr_status", "")
            if ocr_status.startswith("OCR worker stopped"):
                notice = ocr_status
            group = self.store.setting("group", {})
            if not self.store.default_warehouse(group.get("id", "")):
                notice = "Choose and save the default GRN warehouse above before importing photos."
            self.capture_status.set("\n".join(filter(None, [notice, self.store.setting('grn_scan_status', ''), self.store.setting("done_reply_notice", "")]
                + [self.store.setting('grn_cloud_status', ''),
                   f"Cloud OCR: {'enabled' if cloud_settings(self.store)['enabled'] else 'disabled'}; uploads today: {usage_today(self.store)} / {cloud_settings(self.store)['daily_limit'] or 'not set'}"]
                + [f"{e['source']}: {e['capture_error']}" for e in errors[:3]])))
        except (sqlite3.Error, OSError) as exc:
            self.status.set(f"Could not refresh GRN inbox: {exc}")
        self.after_id = self.frame.after(250, self._poll)

    def refresh(self):
        # Render detections before media retrieval/OCR, and update rows in place
        # so heartbeat writes do not reset scrolling or the user's selection.
        if self.selected_source_id is not None:
            source = self.store.db.execute("SELECT document_id FROM grn_sources WHERE id=?", (self.selected_source_id,)).fetchone()
            if source and source[0]:
                self.selected_id, self.selected_source_id = source[0], None
                self.load_selected()
        rows = []
        previous_states, self._run_states = self._run_states, {}
        for source in self.store.pending_entries():
            state = "Waiting for original photo" if source["incoming_verified"] else "Sender verification required"
            if source["capture_error"]:
                state = source['capture_error']
            if grn_message_epoch(source['message_time']) is None:
                state = 'Received time unverified; not scanned'
            elif not grn_photo_is_recent(source['message_time']):
                state = 'Outside last hour; not scanned'
            rows.append((f"source:{source['id']}", ("Incoming photo", state, "New", received_label(source))))
        for record in self.store.documents():
            self._run_states[record["id"]] = record["run_state"]
            state = record["action"] if record["action"] != "New" else record["state"]
            rows.append((str(record["id"]), (record["gatepass"] or "Unread", state, record["run_state"], received_label(record))))
        wanted = {key for key, _ in rows}
        selection_key = str(self.selected_id) if self.selected_id is not None else (
            f"source:{self.selected_source_id}" if self.selected_source_id is not None else None)
        if selection_key is not None and selection_key not in wanted:
            self.reset_selection()
        for key in self.tree.get_children():
            if key not in wanted:
                self.tree.delete(key)
        for index, (key, values) in enumerate(rows):
            if not self.tree.exists(key):
                self.tree.insert("", index, iid=key, values=values)
            else:
                if tuple(self.tree.item(key, "values")) != values:
                    self.tree.item(key, values=values)
                self.tree.move(key, "", index)
        selected = self.selected_id
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
            current = self.store.document(selected)
            revision = (current["state"], current["image_path"], current["extraction"])
            if revision != self.selected_revision and not self.dirty:
                self.load_selected()
            state = current["run_state"]
            if previous_states.get(selected) == "Running" and state != "Running":
                self.status.set(f"GRN state: {state}. You can use Run Gatepass again.")

    def reset_selection(self):
        self.selected_id = self.selected_source_id = self.selected_revision = None
        self.tree.selection_remove(*self.tree.selection())
        self.loading = True
        self.warehouse.set("")
        self.gatepass.set("")
        self.loading = False
        self.dirty = False
        self.confirmed.set(False)
        for label in (self.original, self.crop):
            label.configure(image="", text="Select a photo")
            label.image = None
        self.warnings.set("Select a document to review.")

    def clear_list(self):
        try:
            count = self.store.clear_list()
            self.reset_selection()
            self.refresh()
            self.status.set(f"Cleared {count} photos from this list. History and duplicate protection are retained.")
        except sqlite3.Error as exc:
            self.status.set(f"Could not clear the list: {exc}")

    def _selected(self, _=None):
        selection = self.tree.selection()
        if not selection:
            return
        if selection[0].startswith("source:"):
            self.selected_source_id = int(selection[0].split(":")[1])
            self.selected_id = None
            source = self.store.db.execute("SELECT * FROM grn_sources WHERE id=?", (self.selected_source_id,)).fetchone()
            self.loading = True
            self.warehouse.set(source["warehouse"] if source else "")
            self.gatepass.set("")
            self.loading = False
            self.dirty = False
            self.confirmed.set(False)
            for label in (self.original, self.crop):
                label.configure(image="", text="Waiting for the original photo")
                label.image = None
            self.warnings.set(source["capture_error"] or ("Waiting for WhatsApp to load the original photo." if source["incoming_verified"] else "Sender is not verified as incoming. Keep the message and adjacent incoming messages visible."))
            self.status.set("Photo detected and saved in the inbox. Download and extraction are pending.")
            if source and not grn_photo_is_recent(source['message_time']):
                self.warnings.set('Only photos with a verified WhatsApp received time within the last hour are scanned.')
                self.status.set('Photo skipped by the last-hour capture filter. Existing history is retained.')
        elif int(selection[0]) != self.selected_id:
            self.selected_id = int(selection[0])
            self.selected_source_id = None
            self.load_selected()

    def show_image(self, label, path, size):
        try:
            with Image.open(path) as source:
                picture = ImageOps.exif_transpose(source).convert("RGB")
            picture.thumbnail(size, Image.Resampling.LANCZOS)
            image = ImageTk.PhotoImage(picture)
            label.configure(image=image, text="")
            label.image = image
        except (OSError, ValueError):
            label.configure(image="", text="Image unavailable" if path else "No header detected")
            label.image = None

    def load_selected(self):
        record = self.store.document(self.selected_id)
        if not record or record["hidden_reason"]:
            self.reset_selection()
            return
        self.loading = True
        self.warehouse.set(record["warehouse"])
        self.gatepass.set(record["gatepass"])
        self.loading = False
        self.confirmed.set(False)
        self.dirty = False
        self.selected_revision = (record["state"], record["image_path"], record["extraction"])
        self.show_image(self.original, record["image_path"], (470, min(530, max(220, self.root.winfo_height() - 440))))
        self.show_image(self.crop, record["extraction"].get("header_path", ""), (380, 165))
        warnings = list(record["extraction"].get("warnings", []))
        readings = record["extraction"]
        if readings.get("ocr_candidates"):
            warnings.append("Printed reading: " + ", ".join(readings["ocr_candidates"]))
        if readings.get("barcode_candidates"):
            warnings.append("Header barcode: " + ", ".join(readings["barcode_candidates"]))
        if readings.get('azure_candidates'):
            warnings.append('Azure reading: ' + ', '.join(readings['azure_candidates']))
        if readings.get('ocr_space_candidates'):
            warnings.append('OCR.space reading: ' + ', '.join(readings['ocr_space_candidates']))
        if readings.get('recognition_source'):
            warnings.insert(0, 'Reading source: ' + readings['recognition_source'])
        if any(other["id"] != record["id"] and record["gatepass"] and other["warehouse"] == record["warehouse"]
               and other["gatepass"] == record["gatepass"] for other in self.store.documents()):
            warnings.append("Another photo has this warehouse and gate pass. Compare the originals.")
        sources = self.store.db.execute("SELECT count(*) FROM grn_sources WHERE document_id=?", (record["id"],)).fetchone()[0]
        if sources > 1:
            warnings.append(f"This same image was received {sources} times; it is one review record.")
        self.warnings.set("\n".join(warnings) or "Compare every digit and the warehouse with the original.")
        self.status.set(record["state"] + " — " + record["action"] + ". Save edits before selecting another photo.")

    def _values(self):
        return self.warehouse.get().strip().upper(), self.gatepass.get().strip()

    def save_review(self):
        if self.selected_id is None:
            self.status.set("Select a photo first.")
            return False
        record = self.store.document(self.selected_id)
        if record is None or record["hidden_reason"]:
            self.reset_selection()
            self.status.set("This photo was cleared or marked DONE.")
            return False
        if record["state"] in ('Awaiting original photo', *PENDING_STATES):
            self.status.set("Wait for original-photo capture and cloud reading before saving the review.")
            return False
        if record["run_state"] == "Running" or record["action"].startswith("Replaced"):
            self.status.set("This document is running or has been replaced. Select an idle active photo.")
            return False
        warehouse, gatepass = self._values()
        errors = validate_grn_fields(warehouse, gatepass)
        if errors or not self.confirmed.get():
            self.status.set("\n".join(errors + ([] if self.confirmed.get() else ["Check the photo, then tick the review confirmation."])))
            return False
        try:
            self.store.save_grn_review(self.selected_id, warehouse, gatepass)
            self.dirty = False
            self.refresh()
            self.status.set("Review saved. Fill GRN Form when ready.")
            return True
        except (ValueError, sqlite3.Error) as exc:
            self.status.set(f"Review could not be saved: {exc}")
            return False

    def fill_form(self, start_run=False):
        recover_gatepass_runs(self.store, self.lanes, "GRN")
        if not self.confirmed.get():
            self.status.set("Check the photo and warehouse, then tick the review confirmation.")
            return False
        if not self.lanes and self.ensure_lanes:
            self.lanes = self.ensure_lanes()
            self.lane.configure(values=list(self.lanes))
            if self.lanes and not self.lane.get():
                self.lane.current(0)
        try:
            fill_grn_request(self.store, self.selected_id, *self._values(), self.lane.get(), self.lanes, allow_repeat=start_run)
            if start_run:
                launch_gatepass(self.store, self.selected_id, "GRN", self.lane.get(), self.lanes[self.lane.get()])
        except (ValueError, RuntimeError, OSError, sqlite3.Error, tk.TclError) as exc:
            self.refresh()
            self.status.set(str(exc))
            return False
        self.dirty = False
        self.refresh()
        self.status.set(f"GRN running in {self.lane.get()}. You can run it again after it finishes or stops."
                        if start_run else f"Filled {self.lane.get()}. Open that lane tab and click Create GRN when ready.")
        return True

    def import_visible(self):
        group = self.store.setting("group", {})
        if not group:
            self.status.set("Select a WhatsApp group before scanning GRNs.")
            return
        if not self.store.default_warehouse(group.get("id", "")):
            self.status.set("Choose and save the default GRN warehouse above first.")
            return
        self.controller.start()
        self.store.command(self.controller.run_id, "import_photos")
        self.status.set("Scanning loaded incoming GRN photos received within the last hour. Older photos and unverified received times are skipped.")

    def retry_capture(self):
        try:
            if self.selected_id is not None:
                self.store.refresh_photo(self.selected_id, recent_only=True)
            self.store.retry()
        except (ValueError, sqlite3.Error) as exc:
            self.status.set(str(exc))
            return
        self.controller.start()
        self.status.set("Capture retry requested. Keep the photo message loaded in the Browser tab.")

    def retry_extraction(self):
        if self.selected_id is not None:
            if self.store.document(self.selected_id)["state"] == "Awaiting original photo":
                self.status.set("Wait for original-photo capture before retrying extraction.")
                return
            self.store.retry(self.selected_id)
            self.controller.start()
            self.store.command(self.controller.run_id, "retry_ocr")
            self.status.set("Extraction retry requested. Saved review corrections are preserved.")

    def retry_cloud(self):
        if self.selected_id is None:
            self.status.set('Select an unreviewed photo with a previous cloud request.')
            return
        try:
            retry_cloud(self.store, self.selected_id)
            self.controller.start()
            self.store.command(self.controller.run_id, 'retry_cloud')
            self.refresh()
            self.status.set('Cloud retry requested. OCR.space receives a new upload if no completed result is cached.')
        except (ValueError, sqlite3.Error) as exc:
            self.status.set(str(exc))

    def view_original(self):
        if self.selected_id is None:
            return
        record = self.store.document(self.selected_id)
        window = tk.Toplevel(self.root)
        window.title("GRN original photo")
        try:
            with Image.open(record["image_path"]) as source:
                picture = ImageOps.exif_transpose(source).convert("RGB")
        except (OSError, ValueError):
            ttk.Label(window, text="Original photo is not available yet.").pack(padx=30, pady=30)
            return
        width = min(1100, self.root.winfo_screenwidth() - 100)
        height = min(850, self.root.winfo_screenheight() - 120)
        window.geometry(f"{width}x{height}")
        controls = ttk.Frame(window)
        controls.pack(fill="x")
        ttk.Label(controls, text=f"Captured image: {picture.width} × {picture.height} pixels").pack(side="left", padx=8)
        area = ttk.Frame(window)
        area.pack(fill="both", expand=True)
        canvas = tk.Canvas(area, highlightthickness=0, background="#333333")
        xscroll = ttk.Scrollbar(area, orient="horizontal", command=canvas.xview)
        yscroll = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        xscroll.pack(side="bottom", fill="x")
        yscroll.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)

        def draw(scale):
            size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
            canvas.image = ImageTk.PhotoImage(picture if size == picture.size else picture.resize(size, Image.Resampling.LANCZOS))
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=canvas.image)
            canvas.configure(scrollregion=(0, 0, *size))

        fit = min(1, (width - 25) / picture.width, (height - 60) / picture.height)
        ttk.Button(controls, text="Fit", command=lambda: draw(fit)).pack(side="right", padx=4, pady=4)
        ttk.Button(controls, text="100%", command=lambda: draw(1)).pack(side="right", padx=4)
        ttk.Button(controls, text="200%", command=lambda: draw(2)).pack(side="right", padx=4)
        draw(fit)

    def _destroyed(self, event):
        if event.widget is self.frame and not self.closed:
            self.closed = True
            if self.after_id:
                self.frame.after_cancel(self.after_id)
            self.store.close()
