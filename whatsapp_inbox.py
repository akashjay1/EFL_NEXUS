"""WhatsApp review and dispatch UI. Browser events never call Tk directly."""

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from whatsapp_gdn import (FIELD_LABELS, GDN_FIELDS, GDNInboxStore, form_fields,
                          gatepass_is_active, launch_gatepass, received_label,
                          recover_gatepass_runs, validate_fields)


class WhatsAppGDNInbox:
    def __init__(self, root, lanes, store=None, container=None, controller=None, ensure_lanes=None):
        self.root, self.lanes = root, lanes
        self.store = store if store is not None else GDNInboxStore()
        self.controller = controller
        self.ensure_lanes = ensure_lanes
        recover_gatepass_runs(self.store, self.lanes, "GDN")
        self.selected_id = None
        self._run_states = {}
        self.closed = False
        self.after_id = None
        self.window = ttk.Frame(container) if container is not None else tk.Toplevel(root)
        if container is not None:
            self.window.pack(fill="both", expand=True)
        else:
            self.window.title("WhatsApp GDN Inbox")
            self.window.geometry("1120x840")
            self.window.minsize(940, 740)
            self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)
        self.window.bind("<Destroy>", self._destroyed, add="+")
        self.status = tk.StringVar(value="Review captured requests or import a message manually.")

        outer = ttk.Frame(self.window, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="WhatsApp GDN Inbox", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            outer, wraplength=1040,
            text="Monitoring continues while you review requests or use other NEXUS tools. "
                 "Note is the delivery location. Save edits before selecting another request.",
        ).pack(anchor="w", fill="x", pady=(4, 10))

        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes), ttk.Frame(panes, padding=(14, 0, 0, 0))
        panes.add(left, weight=1)
        panes.add(right, weight=1)
        ttk.Label(left, text="Requests (saved locally)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Button(left, text="Clear List", command=self.clear_list).pack(anchor="w", pady=(4, 0))
        table = ttk.Frame(left)
        table.pack(fill="both", expand=True, pady=(6, 10))
        self.tree = ttk.Treeview(table, columns=("gatepass", "source", "action", "received"), show="headings", height=9, selectmode="browse")
        for key, label, width in (("gatepass", "Gate Pass", 85), ("source", "Source", 115), ("action", "State", 110), ("received", "Received", 195)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        ttk.Label(left, text="Paste a single WhatsApp message").pack(anchor="w")
        self.paste_text = tk.Text(left, height=8, wrap="word", font=("Segoe UI", 10))
        self.paste_text.pack(fill="x", pady=(4, 6))
        paste_actions = ttk.Frame(left)
        paste_actions.pack(fill="x")
        ttk.Button(paste_actions, text="Import Pasted Text", command=self.import_pasted).pack(side="left")
        ttk.Button(paste_actions, text="Import from Clipboard", command=self.import_clipboard).pack(side="left", padx=8)

        right.columnconfigure(1, weight=1)
        self.editors = {}
        for row, key in enumerate(GDN_FIELDS):
            ttk.Label(right, text=FIELD_LABELS[key]).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=(0, 8))
            if key == "delivery_location":
                editor = tk.Text(right, height=3, wrap="word", width=28, font=("Segoe UI", 10))
            else:
                editor = ttk.Entry(right)
            editor.grid(row=row, column=1, sticky="ew", pady=(0, 8))
            self.editors[key] = editor
        self.door = tk.StringVar(value="")
        ttk.Label(right, text="Door Location").grid(row=5, column=0, sticky="nw")
        ttk.Label(right, textvariable=self.door).grid(row=5, column=1, sticky="w")
        self.warnings = tk.StringVar(value="Select a request to review. Note is the delivery location.")
        ttk.Label(right, textvariable=self.warnings, wraplength=440, foreground="#b45309").grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=10)
        lane_actions = ttk.Frame(right)
        lane_actions.grid(row=7, column=0, columnspan=2, sticky="ew")
        ttk.Label(lane_actions, text="Target lane").pack(side="left")
        self.lane_choice = ttk.Combobox(lane_actions, state="readonly", values=list(lanes), width=19)
        self.lane_choice.pack(side="left", padx=8)
        if lanes:
            self.lane_choice.current(0)
        actions = ttk.Frame(right)
        actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Button(actions, text="Save Review", command=self.save_review).pack(side="left")
        ttk.Button(actions, text="Fill Form", command=lambda: self.apply_request(False)).pack(side="left", padx=6)
        ttk.Button(actions, text="Run Gatepass", command=lambda: self.apply_request(False, start_run=True)).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Add to Queue", command=lambda: self.apply_request(True)).pack(side="left")
        ttk.Label(right, text="Original message").grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 4))
        self.raw_text = tk.Text(right, height=9, width=38, wrap="word", state="disabled", font=("Segoe UI", 9))
        self.raw_text.grid(row=10, column=0, columnspan=2, sticky="nsew")
        right.rowconfigure(10, weight=1)
        ttk.Label(outer, textvariable=self.status, wraplength=1040).pack(anchor="w", fill="x", pady=(12, 0))
        self.refresh()
        self._version = self.store.version()
        self.after_id = self.window.after(750, self._poll)

    def _destroyed(self, event):
        if event.widget is not self.window or self.closed:
            return
        self.closed = True
        if self.after_id:
            self.window.after_cancel(self.after_id)
            self.after_id = None
        self.store.close()

    def _poll(self):
        if self.closed:
            return
        try:
            version = self.store.version()
            if version != self._version:
                self._version = version
                self.refresh()
        except sqlite3.Error as exc:
            self.status.set(f"Could not refresh inbox ({exc}).")
        self.after_id = self.window.after(750, self._poll)

    def refresh(self, select_id=None):
        selected = select_id if select_id is not None else self.selected_id
        previous_states, self._run_states = self._run_states, {}
        self.tree.delete(*self.tree.get_children())
        for record in self.store.records():
            self._run_states[record["id"]] = record["run_state"]
            self.tree.insert("", "end", iid=str(record["id"]), values=(
                record["fields"]["gatepass"], record["source"], record["run_state"], received_label(record)))
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
            self.tree.see(str(selected))
            state = self._run_states[selected]
            if previous_states.get(selected) == "Running" and state != "Running":
                self.status.set(f"GDN state: {state}. You can use Run Gatepass again.")
        elif selected is not None:
            self.reset_selection()

    def reset_selection(self):
        self.selected_id = None
        self.tree.selection_remove(*self.tree.selection())
        for editor in self.editors.values():
            editor.delete("1.0" if isinstance(editor, tk.Text) else 0, "end")
        self.door.set("")
        self.raw_text.configure(state="normal")
        self.raw_text.delete("1.0", "end")
        self.raw_text.configure(state="disabled")
        self.warnings.set("Select a request to review.")

    def clear_list(self):
        try:
            count = self.store.clear_list()
            self.reset_selection()
            self.refresh()
            self.status.set(f"Cleared {count} requests from this list. History and duplicate protection are retained.")
        except sqlite3.Error as exc:
            self.status.set(f"Could not clear the list: {exc}")

    def _selected(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        record_id = int(selection[0])
        if record_id == self.selected_id:
            return  # Incoming requests must not overwrite unsaved review edits.
        self.selected_id = record_id
        self.load_selected()

    def load_selected(self):
        record = self.store.get(self.selected_id)
        if record is None or record["hidden_reason"]:
            self.reset_selection()
            return
        for key, editor in self.editors.items():
            if isinstance(editor, tk.Text):
                editor.delete("1.0", "end")
                editor.insert("1.0", record["fields"][key])
            else:
                editor.delete(0, "end")
                editor.insert(0, record["fields"][key])
        self.door.set(record["fields"].get("door_location", ""))
        self.raw_text.configure(state="normal")
        self.raw_text.delete("1.0", "end")
        self.raw_text.insert("1.0", record["raw_text"])
        self.raw_text.configure(state="disabled")
        self.show_warnings(record, record["fields"])

    def _fields(self):
        fields = {key: (editor.get("1.0", "end-1c") if isinstance(editor, tk.Text) else editor.get()).strip()
                  for key, editor in self.editors.items()}
        fields["warehouse"] = fields["warehouse"].upper()
        fields["door_location"] = self.door.get()
        return fields

    def _warehouses(self):
        if not self.lanes and self.ensure_lanes:
            self.lanes = self.ensure_lanes()
            self.lane_choice.configure(values=list(self.lanes))
            if self.lanes:
                self.lane_choice.current(0)
        return {str(v).upper() for lane in self.lanes.values() for v in lane.warehouse_entry.cget("values")}

    def show_warnings(self, record, fields):
        warnings = list(record["warnings"]) + validate_fields(fields, self._warehouses())
        related = self.store.related(fields, record["id"])
        if related:
            warnings.append("Another request uses this warehouse, client, and gate pass. Compare the originals.")
        self.warnings.set("\n".join(warnings) if warnings else "Check the values against the original, then fill the form or queue.")

    def import_message(self, text, source="Clipboard", message_id="", select=True):
        record_id, result = self.store.add(text, source, message_id)
        # Ignore unrelated chat messages without replacing useful UI status.
        if record_id is not None:
            self.status.set(result)
            self.refresh(select_id=record_id if select else None)
            if select:
                self.selected_id = record_id
                self.load_selected()
        elif select:
            self.status.set(result)
        return record_id

    def import_pasted(self):
        try:
            self.import_message(self.paste_text.get("1.0", "end-1c"), source="Pasted text")
        except (OSError, sqlite3.Error) as exc:
            messagebox.showerror("Import failed", str(exc), parent=self.window)

    def import_clipboard(self):
        try:
            self.import_message(self.window.clipboard_get())
        except tk.TclError:
            self.status.set("Clipboard has no text. Copy a WhatsApp message first.")
        except (OSError, sqlite3.Error) as exc:
            messagebox.showerror("Import failed", str(exc), parent=self.window)

    def save_review(self):
        if self.selected_id is None:
            self.status.set("Select a request first.")
            return
        record = self.store.get(self.selected_id)
        if record is None or record["hidden_reason"]:
            self.reset_selection()
            self.status.set("This request was cleared or marked DONE.")
            return
        if record["run_state"] == "Running":
            self.status.set("This request is running. Wait for it to finish or stop its lane.")
            return
        fields = self._fields()
        try:
            self.store.save_review(self.selected_id, fields)
        except (ValueError, sqlite3.Error) as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.window)
            return
        self.refresh()
        self.show_warnings(record, fields)
        self.status.set("Review saved. Complete any missing fields before filling or queuing.")

    def apply_request(self, enqueue, start_run=False):
        recover_gatepass_runs(self.store, self.lanes, "GDN")
        if self.selected_id is None:
            self.status.set("Select a request first.")
            return False
        record = self.store.get(self.selected_id)
        if record is None or record["hidden_reason"]:
            self.reset_selection()
            self.status.set("This request was cleared or marked DONE.")
            return False
        if record["run_state"] == "Running":
            self.status.set("This request is running. Wait for it to finish or stop its lane.")
            return False
        fields = self._fields()
        errors = validate_fields(fields, self._warehouses())
        if errors:
            self.warnings.set("\n".join(errors))
            self.status.set("Complete the highlighted details. Enter N/A explicitly if appropriate.")
            return False
        lane_name = self.lane_choice.get()
        lane = self.lanes.get(lane_name)
        if lane is None:
            self.status.set("Select an available target lane.")
            return False
        if lane.queue_running or str(lane.gdn_btn.cget("state")) == "disabled":
            self.status.set(f"{lane_name} is busy. Choose another lane or wait for it to finish.")
            return False
        related_running = any(r["run_state"] == "Running" for r in self.store.related(fields, self.selected_id))
        if related_running or gatepass_is_active(self.lanes, "GDN", {
                "warehouse_id": fields["warehouse"], "client_code": fields["client"], "gate_pass_number": fields["gatepass"]}):
            self.status.set("This warehouse, client, and gate pass is already queued or running. Wait for that job to finish or stop it.")
            return False
        try:
            # Persist edits before changing any lane state.
            self.store.save_review(self.selected_id, fields)
            lane.prefill_gdn(**form_fields(fields))
            lane.set_status(f"Prefilled GDN from WhatsApp inbox (GP={fields['gatepass']})")
            if enqueue:
                lane.add_to_queue("GDN")
            action = f"Queued: {lane_name}" if enqueue else f"Filled: {lane_name}"
            self.store.save_review(self.selected_id, fields, action)
            if start_run:
                launch_gatepass(self.store, self.selected_id, "GDN", lane_name, lane)
        except (ValueError, RuntimeError, OSError, sqlite3.Error, tk.TclError) as exc:
            self.refresh()
            self.status.set(f"Could not start the action: {exc}")
            return False
        self.refresh()
        self.show_warnings(record, fields)
        self.status.set(f"GDN running in {lane_name}. Its state changes to Completed when the flow finishes; you can then run it again."
                        if start_run else f"{action}. No GDN has been created automatically.")
        return True


def open_inbox(root):
    navigate = getattr(root, "_open_whatsapp_page", None)
    if navigate:
        return navigate()
    existing = getattr(root, "_whatsapp_standalone", None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        existing._whatsapp_page.set_visible(True)
        return existing
    try:
        from whatsapp_controller import WhatsAppController
        from whatsapp_page import WhatsAppPage
        controller = getattr(root, "_whatsapp_controller", None)
        if controller is None or controller.closed:
            controller = root._whatsapp_controller = WhatsAppController(root)
        window = tk.Toplevel(root)
        window.title("WhatsApp")
        window.geometry("1140x860")
        window.minsize(960, 740)
        root._whatsapp_standalone = window
        page = WhatsAppPage(root, window, controller)
        window._whatsapp_page = page
        window.protocol("WM_DELETE_WINDOW", lambda: (controller.set_visible(False), window.withdraw()))
        window.bind("<Destroy>", lambda event: controller.set_visible(False) if event.widget is window else None, add="+")
        page.set_visible(True)
    except (OSError, sqlite3.Error) as exc:
        messagebox.showerror("WhatsApp GDN Inbox", f"Could not open local inbox storage: {exc}", parent=root)
        return None
    return page
