"""Embedded WhatsApp browser and review tabs; neither owns capture lifetime."""

import tkinter as tk
from tkinter import ttk

from korber_tool import KorberApp
from whatsapp_gdn import GDNInboxStore
from whatsapp_inbox import WhatsAppGDNInbox
from whatsapp_grn import GRNInboxStore, GRN_WAREHOUSES
from whatsapp_grn_inbox import WhatsAppGRNInbox


WHATSAPP_LANES = (("WhatsApp Lane 1", "whatsapp_lane_1"),
                  ("WhatsApp Lane 2", "whatsapp_lane_2"))


class WhatsAppPage:
    def __init__(self, root, container, controller):
        self.root, self.controller = root, controller
        self.lanes = {}
        self.lane_tabs = {}
        self.lane_canvases = {}
        self.grn_settings = None
        self.browser_host = None
        self.visible = False
        self.frame = ttk.Frame(container, padding=12)
        self.frame.pack(fill="both", expand=True)
        self.frame.bind("<Destroy>", self._destroyed, add="+")
        self.status = tk.StringVar()
        self.group = tk.StringVar()
        self.gap = tk.StringVar()
        self.import_visible = tk.BooleanVar(value=False)
        self.grn_settings = GRNInboxStore(controller.store.path)
        self.grn_warehouse = tk.StringVar()
        configured = self.grn_settings.setting("group", {})
        self.grn_group_id = configured.get("id", "")
        self.grn_warehouse.set(self.grn_settings.default_warehouse(configured.get("id", "")))
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x")
        ttk.Label(bar, text="WhatsApp", font=("Segoe UI", 15, "bold")).pack(side="left", padx=(0, 14))
        ttk.Button(bar, text="Open / Reconnect", command=self._open).pack(side="left")
        self.select_button = ttk.Button(bar, text="Use Open Group", command=self._select)
        self.select_button.pack(side="left", padx=6)
        ttk.Button(bar, text="Pause", command=controller.pause).pack(side="left")
        ttk.Button(bar, text="Resume", command=controller.resume).pack(side="left", padx=6)
        ttk.Button(bar, text="Reload", command=controller.reload).pack(side="left")
        ttk.Label(self.frame, textvariable=self.status, wraplength=1080).pack(anchor="w", pady=(8, 3))
        ttk.Label(self.frame, textvariable=self.group, wraplength=1080).pack(anchor="w")
        grn_setup = ttk.Frame(self.frame)
        grn_setup.pack(fill="x", pady=6)
        ttk.Label(grn_setup, text="Default GRN warehouse for selected group").pack(side="left")
        ttk.Combobox(grn_setup, textvariable=self.grn_warehouse, values=GRN_WAREHOUSES,
                     state="readonly", width=12).pack(side="left", padx=8)
        ttk.Button(grn_setup, text="Save GRN Warehouse", command=self._save_grn_warehouse).pack(side="left")
        self.grn_setup_status = tk.StringVar()
        ttk.Label(grn_setup, textvariable=self.grn_setup_status).pack(side="left", padx=8)
        gapbar = ttk.Frame(self.frame)
        gapbar.pack(fill="x", pady=(3, 6))
        ttk.Label(gapbar, textvariable=self.gap, foreground="#b45309", wraplength=850).pack(side="left")
        self.ack_button = ttk.Button(gapbar, text="Gap checked", command=controller.acknowledge_gap)
        self.notebook = ttk.Notebook(self.frame)
        self.notebook.pack(fill="both", expand=True)
        self.browser_tab = ttk.Frame(self.notebook)
        self.inbox_tab = ttk.Frame(self.notebook)
        self.grn_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.browser_tab, text="  Browser  ")
        self.notebook.add(self.inbox_tab, text="  GDN Inbox  ")
        self.notebook.add(self.grn_tab, text="  GRN Inbox  ")
        for label, profile in WHATSAPP_LANES:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text=f"  {label}  ")
            self.lane_tabs[label] = tab
            canvas = tk.Canvas(tab, highlightthickness=0, background="#faf8f2")
            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            host = ttk.Frame(canvas)
            window_id = canvas.create_window((0, 0), window=host, anchor="nw")
            host.bind("<Configure>", lambda event, c=canvas: c.configure(scrollregion=c.bbox("all")))
            canvas.bind("<Configure>", lambda event, c=canvas, w=window_id: c.itemconfigure(w, width=event.width))
            canvas.bind("<MouseWheel>", lambda event, c=canvas: c.yview_scroll(-int(event.delta / 120), "units"))
            self.lane_canvases[label] = canvas
            self.lanes[label] = KorberApp(root, container=host, standalone=False, profile_name=profile)
        ttk.Label(self.browser_tab, text="Sign in using the QR code, open your GDN group, then choose Use Open Group. "
                  "Pause before changing the monitored group.", wraplength=1060).pack(anchor="w", padx=8, pady=(8, 4))
        ttk.Checkbutton(self.browser_tab, text="Also import messages currently visible when selecting the group",
                        variable=self.import_visible).pack(anchor="w", padx=8, pady=(0, 6))
        self.browser_host = tk.Frame(self.browser_tab, bg="#ffffff")
        self.browser_host.pack(fill="both", expand=True)
        ttk.Label(self.browser_host, text="Choose Open / Reconnect to load WhatsApp Web inside NEXUS.",
                  wraplength=700).place(relx=.5, rely=.5, anchor="center")
        controller.set_host(self.browser_host)
        self.inbox = WhatsAppGDNInbox(root, self.lanes, GDNInboxStore(controller.store.path),
                                      container=self.inbox_tab, controller=controller)
        self.grn_inbox = WhatsAppGRNInbox(root, self.grn_tab, controller, self.lanes)
        self.notebook.bind("<<NotebookTabChanged>>", lambda event: self._visibility())
        controller.listeners.append(self._changed)
        self._changed(controller)

    def _changed(self, controller):
        self.status.set(f"{controller.state}: {controller.detail}")
        group = controller.store.setting("group")
        if group and group["id"] != self.grn_group_id:
            self.grn_group_id = group["id"]
            self.grn_warehouse.set(self.grn_settings.default_warehouse(group["id"]))
        self.group.set("Selected group: " + group["name"] if group else "No group selected")
        enabled = controller.store.setting("enabled", False)
        self.select_button.configure(state="disabled" if group and enabled else "normal")
        self.notebook.tab(self.inbox_tab, text=f"  GDN Inbox ({controller.new_count} new)  ")
        self.notebook.tab(self.grn_tab, text=f"  GRN Inbox ({getattr(controller, 'grn_new_count', 0)} new)  ")
        self.gap.set("\n".join(filter(None, [
            "Possible capture gap. Compare recent group messages and import any missing requests." if controller.gap else "",
            controller.store.setting("done_reply_notice", "")])))
        if controller.gap:
            self.ack_button.pack(side="right")
        else:
            self.ack_button.pack_forget()

    def _open(self):
        self.notebook.select(self.browser_tab)
        self.controller.start()
        self._visibility()

    def _save_grn_warehouse(self):
        group = self.grn_settings.setting("group", {})
        warehouse = self.grn_warehouse.get()
        if not group or warehouse not in GRN_WAREHOUSES:
            self.grn_setup_status.set("Select a group and warehouse first.")
            return
        self.grn_settings.set_default_warehouse(group["id"], warehouse)
        self.grn_setup_status.set("Saved for this group.")

    def _select(self):
        self.controller.select_group(self.import_visible.get())

    def show_inbox(self):
        self.notebook.select(self.inbox_tab)
        self._visibility()

    def set_visible(self, visible):
        self.visible = bool(visible)
        self._visibility()

    def _visibility(self):
        self.controller.set_visible(self.visible and self.notebook.select() == str(self.browser_tab))

    def _destroyed(self, event):
        if event.widget is self.frame:
            if self.grn_settings is not None:
                self.grn_settings.close()
            if self._changed in self.controller.listeners:
                self.controller.listeners.remove(self._changed)
            self.controller.set_visible(False)
            # HWND is destroyed with its Tk host. A later view receives the
            # restarted helper through the application-owned watchdog.
            if self.controller.host is self.browser_host:
                self.controller.host = None
