"""GRN photo review. Capture and OCR never invoke the Korber automation."""

import sqlite3
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

from whatsapp_grn import GRNInboxStore, GRN_WAREHOUSES, fill_grn_request, validate_grn_fields


class WhatsAppGRNInbox:
    def __init__(self, root, container, controller, lanes, ensure_lanes=None):
        self.root, self.controller, self.lanes, self.ensure_lanes = root, controller, lanes, ensure_lanes
        self.store = GRNInboxStore(controller.store.path)
        self.selected_id = None
        self.closed = False
        self.after_id = None
        self.selected_revision = None
        self.dirty = False
        self.loading = False
        self.frame = ttk.Frame(container, padding=12)
        self.frame.pack(fill="both", expand=True)
        self.frame.bind("<Destroy>", self._destroyed, add="+")
        self.status = tk.StringVar(value="Review the photo and number before filling a GRN form. Each GRN starts only when you click Create GRN.")
        self.capture_status = tk.StringVar()
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x")
        ttk.Button(bar, text="Import Visible Photos", command=self.import_visible).pack(side="left")
        ttk.Button(bar, text="Retry Capture", command=self.retry_capture).pack(side="left", padx=6)
        ttk.Label(bar, text="For older photos: pause monitoring, scroll to the message, then import.").pack(side="left", padx=8)
        ttk.Label(self.frame, textvariable=self.capture_status, wraplength=1300, foreground="#b45309").pack(anchor="w", pady=6)
        panes = ttk.Panedwindow(self.frame, orient="horizontal")
        panes.pack(fill="both", expand=True)
        listing, original, details = ttk.Frame(panes), ttk.Frame(panes, padding=10), ttk.Frame(panes, padding=10)
        panes.add(listing, weight=2)
        panes.add(original, weight=3)
        panes.add(details, weight=2)
        self.tree = ttk.Treeview(listing, columns=("gatepass", "state"), show="headings", selectmode="browse")
        self.tree.heading("gatepass", text="Gate Pass")
        self.tree.heading("state", text="Status")
        self.tree.column("gatepass", width=95, minwidth=70)
        self.tree.column("state", width=150, minwidth=100)
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
        self.lane = ttk.Combobox(details, values=list(lanes) or ["Lane A", "Lane B"], state="readonly")
        self.lane.pack(fill="x", pady=(3, 10))
        self.lane.current(0)
        ttk.Button(details, text="Save Review", command=self.save_review).pack(fill="x", pady=3)
        ttk.Button(details, text="Fill GRN Form", command=self.fill_form).pack(fill="x", pady=3)
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
            self.capture_status.set("\n".join([notice] + [f"{e['source']}: {e['capture_error']}" for e in errors[:3]]).strip())
        except (sqlite3.Error, OSError) as exc:
            self.status.set(f"Could not refresh GRN inbox: {exc}")
        self.after_id = self.frame.after(750, self._poll)

    def refresh(self):
        selected = self.selected_id
        self.tree.delete(*self.tree.get_children())
        for record in self.store.documents():
            state = record["action"] if record["action"] != "New" else record["state"]
            self.tree.insert("", "end", iid=str(record["id"]), values=(record["gatepass"] or "Unread", state))
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
            current = self.store.document(selected)
            revision = (current["state"], current["extraction"])
            if revision != self.selected_revision and not self.dirty:
                self.load_selected()

    def _selected(self, _=None):
        selection = self.tree.selection()
        if selection and int(selection[0]) != self.selected_id:
            self.selected_id = int(selection[0])
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
        if not record:
            return
        self.loading = True
        self.warehouse.set(record["warehouse"])
        self.gatepass.set(record["gatepass"])
        self.loading = False
        self.confirmed.set(False)
        self.dirty = False
        self.selected_revision = (record["state"], record["extraction"])
        self.show_image(self.original, record["image_path"], (470, min(530, max(220, self.root.winfo_height() - 440))))
        self.show_image(self.crop, record["extraction"].get("header_path", ""), (380, 165))
        warnings = list(record["extraction"].get("warnings", []))
        readings = record["extraction"]
        if readings.get("ocr_candidates"):
            warnings.append("Printed reading: " + ", ".join(readings["ocr_candidates"]))
        if readings.get("barcode_candidates"):
            warnings.append("Header barcode: " + ", ".join(readings["barcode_candidates"]))
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
        if record["state"] == "Awaiting original photo":
            self.status.set("Wait for original-photo capture before saving the review.")
            return False
        if record["action"].startswith(("Filled:", "Filling:", "Transfer uncertain:", "Replaced")):
            self.status.set("This document was transferred. Check its target lane before processing it again.")
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
        except sqlite3.Error as exc:
            self.status.set(f"Review could not be saved: {exc}")
            return False

    def fill_form(self):
        if not self.confirmed.get():
            self.status.set("Check the photo and warehouse, then tick the review confirmation.")
            return
        if not self.lanes and self.ensure_lanes:
            self.lanes = self.ensure_lanes()
            self.lane.configure(values=list(self.lanes))
            if self.lanes and not self.lane.get():
                self.lane.current(0)
        try:
            fill_grn_request(self.store, self.selected_id, *self._values(), self.lane.get(), self.lanes)
        except (ValueError, OSError, sqlite3.Error, tk.TclError) as exc:
            self.status.set(str(exc))
            return
        self.dirty = False
        self.refresh()
        self.status.set(f"Filled {self.lane.get()}. Open Korber Automation and click Create GRN when ready.")

    def import_visible(self):
        group = self.store.setting("group", {})
        if not self.store.default_warehouse(group.get("id", "")):
            self.status.set("Choose and save the default GRN warehouse above first.")
            return
        self.controller.start()
        self.store.command(self.controller.run_id, "import_photos")
        self.status.set("Requested capture of visible incoming photos in the selected group.")

    def retry_capture(self):
        try:
            if self.selected_id is not None:
                self.store.refresh_photo(self.selected_id)
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

    def view_original(self):
        if self.selected_id is None:
            return
        record = self.store.document(self.selected_id)
        window = tk.Toplevel(self.root)
        window.title("GRN original photo")
        label = ttk.Label(window)
        label.pack(fill="both", expand=True)
        self.show_image(label, record["image_path"], (min(1100, self.root.winfo_screenwidth() - 100), self.root.winfo_screenheight() - 120))

    def _destroyed(self, event):
        if event.widget is self.frame and not self.closed:
            self.closed = True
            if self.after_id:
                self.frame.after_cancel(self.after_id)
            self.store.close()
