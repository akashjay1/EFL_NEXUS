"""
My Software - unified launcher for the Korber Automation tool and the
Load Reconciliation tool, behind one sidebar-navigated window.

RUN:
    python main_app.py

Requires korber_tool.py and reconciliation_tool.py (and, for Tool 1,
korber_login_bot.py + selenium) to sit alongside this file.
"""

import sys
import traceback
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime


# ---------------------------------------------------------------------------
# Palette / layout constants for the shell chrome (sidebar, dashboard, etc).
# The two tools keep their own internal theming; this only styles the parts
# that belong to the shell itself.
# ---------------------------------------------------------------------------
SIDEBAR_BG = "#152438"
SIDEBAR_BG_HOVER = "#20334c"
SIDEBAR_BG_ACTIVE = "#1c3f60"
SIDEBAR_FG = "#cbd5e1"
SIDEBAR_FG_ACTIVE = "#ffffff"
SIDEBAR_BORDER = "#0d1826"
CONTENT_BG = "#f4f6f8"
BRAND_ACCENT = "#1c3f60"

SIDEBAR_WIDTH_EXPANDED = 210
SIDEBAR_WIDTH_COLLAPSED = 56

NAV_ITEMS = [
    ("dashboard", "🏠", "Dashboard"),
    ("tool1", "🔧", "Tool 1: Korber Automation"),
    ("tool2", "⚡", "Tool 2: Load Reconciliation"),
    ("history", "📊", "History"),
    ("settings", "⚙", "Settings"),
]


class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title("My Software")
        self.root.geometry("1400x900")
        self.root.minsize(900, 600)
        self.root.configure(bg=CONTENT_BG)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Lazily-created tool instances (built the first time each page is
        # opened, so a missing dependency for one tool never blocks the
        # other tool or the rest of the shell from working).
        # Tool 1 runs as two fully independent lanes -- each is its own
        # KorberApp instance with its own browser/login/queue -- so a
        # priority GDN/GRN can run in Lane B at the same time as Lane A,
        # rather than waiting behind it in one shared queue.
        self.tool1_lanes = {"a": None, "b": None}
        self.tool1_ready = False
        self.tool2_app = None
        self.tool1_error = None
        self.tool2_error = None

        self.sidebar_collapsed = False
        self.active_page = None
        self.nav_buttons = {}  # key -> {"frame":..., "icon":..., "label":...}

        self._build_layout()
        self._build_sidebar()
        self._build_pages()

        self.show_page("dashboard")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------
    # Layout scaffolding
    # ------------------------------------------------------------------
    def _build_layout(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.sidebar = tk.Frame(self.root, bg=SIDEBAR_BG, width=SIDEBAR_WIDTH_EXPANDED)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)

        self.content_outer = tk.Frame(self.root, bg=CONTENT_BG)
        self.content_outer.grid(row=0, column=1, sticky="nsew")
        self.content_outer.columnconfigure(0, weight=1)
        self.content_outer.rowconfigure(0, weight=1)

        # All pages are stacked in the same cell; show_page() raises one.
        self.pages = {}

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    def _build_sidebar(self):
        for w in self.sidebar.winfo_children():
            w.destroy()

        # --- Brand row ---
        brand_row = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        brand_row.pack(fill="x", pady=(14, 18), padx=10)

        if not self.sidebar_collapsed:
            tk.Label(
                brand_row, text="My Software", bg=SIDEBAR_BG, fg="#ffffff",
                font=("Segoe UI", 13, "bold"), anchor="w"
            ).pack(side="left")
        else:
            tk.Label(
                brand_row, text="MS", bg=SIDEBAR_BG, fg="#ffffff",
                font=("Segoe UI", 13, "bold")
            ).pack()

        # --- Nav items ---
        self.nav_buttons = {}
        for key, icon, label in NAV_ITEMS:
            self.nav_buttons[key] = self._make_nav_button(key, icon, label)

        # --- Spacer pushes the collapse toggle to the bottom ---
        spacer = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        spacer.pack(fill="both", expand=True)

        toggle_row = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        toggle_row.pack(fill="x", pady=(0, 14), padx=10)
        toggle_text = "☰" if self.sidebar_collapsed else "◀  Hide"
        self.toggle_btn = tk.Label(
            toggle_row, text=toggle_text, bg=SIDEBAR_BG, fg=SIDEBAR_FG,
            font=("Segoe UI", 10), cursor="hand2", anchor="w", padx=6, pady=6
        )
        self.toggle_btn.pack(fill="x")
        self.toggle_btn.bind("<Button-1>", lambda e: self.toggle_sidebar())
        self.toggle_btn.bind("<Enter>", lambda e: self.toggle_btn.config(bg=SIDEBAR_BG_HOVER))
        self.toggle_btn.bind("<Leave>", lambda e: self.toggle_btn.config(bg=SIDEBAR_BG))

        self._refresh_nav_highlight()

    def _make_nav_button(self, key, icon, label):
        row = tk.Frame(self.sidebar, bg=SIDEBAR_BG, cursor="hand2")
        row.pack(fill="x", padx=8, pady=2)

        text = icon if self.sidebar_collapsed else f"{icon}   {label}"
        anchor = "center" if self.sidebar_collapsed else "w"
        lbl = tk.Label(
            row, text=text, bg=SIDEBAR_BG, fg=SIDEBAR_FG,
            font=("Segoe UI", 10), anchor=anchor, padx=10, pady=9
        )
        lbl.pack(fill="x")

        def on_click(e, k=key):
            self.show_page(k)

        def on_enter(e):
            if self.active_page != key:
                lbl.config(bg=SIDEBAR_BG_HOVER)
                row.config(bg=SIDEBAR_BG_HOVER)

        def on_leave(e):
            if self.active_page != key:
                lbl.config(bg=SIDEBAR_BG)
                row.config(bg=SIDEBAR_BG)

        for widget in (row, lbl):
            widget.bind("<Button-1>", on_click)
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

        return {"row": row, "label": lbl}

    def _refresh_nav_highlight(self):
        for key, widgets in self.nav_buttons.items():
            active = (key == self.active_page)
            bg = SIDEBAR_BG_ACTIVE if active else SIDEBAR_BG
            fg = SIDEBAR_FG_ACTIVE if active else SIDEBAR_FG
            widgets["row"].config(bg=bg)
            widgets["label"].config(bg=bg, fg=fg)

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        new_w = SIDEBAR_WIDTH_COLLAPSED if self.sidebar_collapsed else SIDEBAR_WIDTH_EXPANDED
        self.sidebar.configure(width=new_w)
        self._build_sidebar()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def _build_pages(self):
        for key, _, _ in NAV_ITEMS:
            frame = tk.Frame(self.content_outer, bg=CONTENT_BG)
            frame.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = frame

        self._build_dashboard_page(self.pages["dashboard"])
        self._build_history_page(self.pages["history"])
        self._build_settings_page(self.pages["settings"])
        # tool1 / tool2 pages are populated lazily in show_page()

    def show_page(self, key):
        self.active_page = key
        self._refresh_nav_highlight()

        if key == "tool1":
            self._ensure_tool1()
        elif key == "tool2":
            self._ensure_tool2()
        elif key == "history":
            self._refresh_history()

        self.pages[key].tkraise()

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def _build_dashboard_page(self, parent):
        wrap = tk.Frame(parent, bg=CONTENT_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=40)

        tk.Label(
            wrap, text="Welcome to My Software", bg=CONTENT_BG, fg="#1f2937",
            font=("Segoe UI", 20, "bold")
        ).pack(anchor="w")
        tk.Label(
            wrap, text="Pick a tool from the sidebar, or jump in below.",
            bg=CONTENT_BG, fg="#6b7280", font=("Segoe UI", 11)
        ).pack(anchor="w", pady=(4, 24))

        cards_row = tk.Frame(wrap, bg=CONTENT_BG)
        cards_row.pack(anchor="w")

        self._make_dashboard_card(
            cards_row, "🔧", "Tool 1: Korber Automation",
            "Create GDN / GRN entries in Korber, with a run queue and "
            "auto-retry.", "tool1"
        ).pack(side="left", padx=(0, 20))

        self._make_dashboard_card(
            cards_row, "⚡", "Tool 2: Load Reconciliation",
            "Reconcile Loading History against Load Plan and export a "
            "formatted variance report.", "tool2"
        ).pack(side="left")

    def _make_dashboard_card(self, parent, icon, title, desc, page_key):
        card = tk.Frame(parent, bg="#ffffff", highlightbackground="#e5e7eb",
                         highlightthickness=1, width=320, height=170)
        card.pack_propagate(False)

        tk.Label(card, text=icon, bg="#ffffff", font=("Segoe UI", 22)).pack(
            anchor="w", padx=18, pady=(16, 0)
        )
        tk.Label(
            card, text=title, bg="#ffffff", fg="#1f2937",
            font=("Segoe UI", 12, "bold"), wraplength=280, justify="left"
        ).pack(anchor="w", padx=18, pady=(6, 4))
        tk.Label(
            card, text=desc, bg="#ffffff", fg="#6b7280",
            font=("Segoe UI", 9), wraplength=280, justify="left"
        ).pack(anchor="w", padx=18)

        open_btn = tk.Label(
            card, text="Open  →", bg="#ffffff", fg=BRAND_ACCENT,
            font=("Segoe UI", 9, "bold"), cursor="hand2"
        )
        open_btn.pack(anchor="w", padx=18, pady=(10, 0))

        def go(e=None, k=page_key):
            self.show_page(k)

        for w in (card, open_btn):
            w.bind("<Button-1>", go)
        card.configure(cursor="hand2")

        return card

    # ------------------------------------------------------------------
    # Tool 1 / Tool 2 lazy loading with graceful error pages
    # ------------------------------------------------------------------
    def _ensure_tool1(self):
        page = self.pages["tool1"]
        if self.tool1_ready or self.tool1_error is not None:
            return
        try:
            import korber_tool
        except Exception:
            self.tool1_error = traceback.format_exc()
            self._show_tool_error(page, "Tool 1: Korber Automation", self.tool1_error)
            return

        try:
            notice = tk.Label(
                page,
                text="Lane A and Lane B run fully independently -- each opens "
                "its own browser/login. Use Lane B for jobs that need to jump "
                "ahead instead of waiting behind Lane A's queue.",
                bg="#eef2f7", fg="#374151", font=("Segoe UI", 9),
                anchor="w", padx=12, pady=6
            )
            notice.pack(fill="x")

            notebook = ttk.Notebook(page)
            notebook.pack(fill="both", expand=True)

            lane_a_frame = tk.Frame(notebook, bg="#f4f6f8")
            lane_b_frame = tk.Frame(notebook, bg="#f4f6f8")
            notebook.add(lane_a_frame, text="Lane A")
            notebook.add(lane_b_frame, text="Lane B  (Priority)")

            self.tool1_lanes["a"] = korber_tool.KorberApp(
                self.root, container=lane_a_frame, standalone=False
            )
            self.tool1_lanes["b"] = korber_tool.KorberApp(
                self.root, container=lane_b_frame, standalone=False
            )
            self.tool1_ready = True
        except Exception:
            self.tool1_error = traceback.format_exc()
            self.tool1_lanes = {"a": None, "b": None}
            self._show_tool_error(page, "Tool 1: Korber Automation", self.tool1_error)

    def _ensure_tool2(self):
        page = self.pages["tool2"]
        if self.tool2_app is not None or self.tool2_error is not None:
            return
        try:
            import reconciliation_tool
        except Exception:
            self.tool2_error = traceback.format_exc()
            self._show_tool_error(page, "Tool 2: Load Reconciliation", self.tool2_error)
            return

        try:
            self.tool2_app = reconciliation_tool.ReconciliationApp(
                self.root, container=page, standalone=False
            )
            # Route the tool's "Exit" button back to the Dashboard instead
            # of letting it destroy the shared shell window.
            self.tool2_app.on_embedded_exit = lambda: self.show_page("dashboard")
        except Exception:
            self.tool2_error = traceback.format_exc()
            self.tool2_app = None
            self._show_tool_error(page, "Tool 2: Load Reconciliation", self.tool2_error)

    def _show_tool_error(self, page, tool_name, error_text):
        for w in page.winfo_children():
            w.destroy()
        wrap = tk.Frame(page, bg=CONTENT_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=40)
        tk.Label(
            wrap, text=f"⚠️  {tool_name} couldn't start", bg=CONTENT_BG,
            fg="#b3392c", font=("Segoe UI", 14, "bold")
        ).pack(anchor="w")
        tk.Label(
            wrap, text="This is usually a missing dependency (e.g. selenium, "
            "pandas, openpyxl) or a missing helper module. Details:",
            bg=CONTENT_BG, fg="#6b7280", font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(6, 10))

        text_box = tk.Text(wrap, height=14, font=("Consolas", 9), wrap="word")
        text_box.insert("1.0", error_text)
        text_box.configure(state="disabled")
        text_box.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # History page (pulls from whichever tools have been opened this
    # session -- Tool 1's run queue and Tool 2's activity log).
    # ------------------------------------------------------------------
    def _build_history_page(self, parent):
        wrap = tk.Frame(parent, bg=CONTENT_BG)
        wrap.pack(fill="both", expand=True, padx=30, pady=24)

        top = tk.Frame(wrap, bg=CONTENT_BG)
        top.pack(fill="x")
        tk.Label(
            top, text="History", bg=CONTENT_BG, fg="#1f2937",
            font=("Segoe UI", 16, "bold")
        ).pack(side="left")
        tk.Button(top, text="⟳ Refresh", command=self._refresh_history).pack(side="right")

        cols = tk.Frame(wrap, bg=CONTENT_BG)
        cols.pack(fill="both", expand=True, pady=(16, 0))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)
        cols.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(cols, text="Tool 1: Korber run queues (Lane A + Lane B)", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.history_tool1_text = tk.Text(left, font=("Consolas", 9), wrap="word", height=20)
        self.history_tool1_text.pack(fill="both", expand=True)

        right = ttk.LabelFrame(cols, text="Tool 2: Reconciliation activity log", padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        self.history_tool2_text = tk.Text(right, font=("Consolas", 9), wrap="word", height=20)
        self.history_tool2_text.pack(fill="both", expand=True)

    def _refresh_history(self):
        t1 = getattr(self, "history_tool1_text", None)
        if t1 is not None:
            t1.configure(state="normal")
            t1.delete("1.0", "end")
            if not self.tool1_ready:
                t1.insert("1.0", "Tool 1 hasn't been opened yet this session.")
            else:
                for lane_key, lane_label in (("a", "Lane A"), ("b", "Lane B (Priority)")):
                    lane_app = self.tool1_lanes.get(lane_key)
                    t1.insert("end", f"--- {lane_label} ---\n")
                    queue = getattr(lane_app, "queue", None) if lane_app else None
                    if not queue:
                        t1.insert("end", "  Queue is empty.\n\n")
                        continue
                    for item in queue:
                        t1.insert(
                            "end",
                            f"  [{item.get('status', '?')}] {item.get('doc_type', '?')} "
                            f"- Gate Pass: {item.get('fields', {}).get('gatepass', '')}\n"
                        )
                    t1.insert("end", "\n")
            t1.configure(state="disabled")

        t2 = getattr(self, "history_tool2_text", None)
        if t2 is not None:
            t2.configure(state="normal")
            t2.delete("1.0", "end")
            if self.tool2_app is None:
                t2.insert("1.0", "Tool 2 hasn't been opened yet this session.")
            elif not getattr(self.tool2_app, "log_messages", None):
                t2.insert("1.0", "No activity logged yet.")
            else:
                for entry in self.tool2_app.log_messages:
                    t2.insert("end", str(entry) + "\n")
            t2.configure(state="disabled")

    # ------------------------------------------------------------------
    # Settings page (this is the sidebar "⚙ Settings" destination that
    # replaces Tool 2's old top-right Settings button; Tool 2's existing
    # settings dialog is opened from here instead of being rebuilt).
    # ------------------------------------------------------------------
    def _build_settings_page(self, parent):
        wrap = tk.Frame(parent, bg=CONTENT_BG)
        wrap.pack(fill="both", expand=True, padx=40, pady=40)

        tk.Label(
            wrap, text="Settings", bg=CONTENT_BG, fg="#1f2937",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 20))

        # --- Tool 2 settings ---
        t2_box = ttk.LabelFrame(wrap, text="Tool 2: Load Reconciliation", padding=16)
        t2_box.pack(fill="x", pady=(0, 16))
        tk.Label(
            t2_box, text="Theme, remembered folders, auto-open, and logging "
            "options for the reconciliation tool.",
            font=("Segoe UI", 9), foreground="#6b7280"
        ).pack(anchor="w", pady=(0, 10))
        ttk.Button(
            t2_box, text="⚙️ Open Reconciliation Settings",
            command=self._open_tool2_settings
        ).pack(anchor="w")

        # --- Tool 1 settings / session controls ---
        t1_box = ttk.LabelFrame(wrap, text="Tool 1: Korber Automation", padding=16)
        t1_box.pack(fill="x", pady=(0, 16))
        tk.Label(
            t1_box, text="Session controls for each of Tool 1's two parallel "
            "browser lanes. \"Restart App\" restarts the whole application "
            "(both lanes), since they share one process.",
            font=("Segoe UI", 9), foreground="#6b7280", wraplength=700, justify="left"
        ).pack(anchor="w", pady=(0, 10))

        for lane_key, lane_label in (("a", "Lane A"), ("b", "Lane B (Priority)")):
            row = tk.Frame(t1_box)
            row.pack(anchor="w", fill="x", pady=2)
            tk.Label(row, text=lane_label, font=("Segoe UI", 9, "bold"), width=16, anchor="w").pack(side="left")
            ttk.Button(
                row, text="Terminate Session",
                command=lambda k=lane_key: self._tool1_terminate(k)
            ).pack(side="left", padx=(0, 8))
            ttk.Button(
                row, text="About",
                command=lambda k=lane_key: self._tool1_about(k)
            ).pack(side="left")

        ttk.Button(t1_box, text="Restart App (both lanes)", command=self._tool1_restart).pack(anchor="w", pady=(10, 0))

        # --- About the shell itself ---
        about_box = ttk.LabelFrame(wrap, text="About My Software", padding=16)
        about_box.pack(fill="x")
        tk.Label(
            about_box,
            text="My Software bundles the Korber Automation tool and the "
            "Load Reconciliation tool behind one sidebar. Use the sidebar "
            "to switch tools without losing either tool's in-progress work.",
            font=("Segoe UI", 9), foreground="#6b7280", wraplength=700, justify="left"
        ).pack(anchor="w")

    def _open_tool2_settings(self):
        self._ensure_tool2()
        if self.tool2_app is not None:
            self.tool2_app.open_settings_dialog()
        else:
            messagebox.showerror(
                "Tool 2 unavailable",
                "Tool 2 couldn't be started, so its settings aren't available.\n"
                "Open the Tool 2 page from the sidebar to see the error details."
            )

    def _tool1_terminate(self, lane_key):
        self._ensure_tool1()
        lane_app = self.tool1_lanes.get(lane_key)
        if lane_app is not None:
            lane_app.terminate_session()
        else:
            messagebox.showerror("Tool 1 unavailable", "Tool 1 couldn't be started.")

    def _tool1_restart(self):
        # Restarts the whole process (os.execv under the hood), so both
        # lanes go down and the shell reopens fresh -- there's no way to
        # restart just one lane's process since they share one Python
        # process and one Tk root.
        self._ensure_tool1()
        lane_app = self.tool1_lanes.get("a") or self.tool1_lanes.get("b")
        if lane_app is not None:
            lane_app.terminate_and_restart()
        else:
            messagebox.showerror("Tool 1 unavailable", "Tool 1 couldn't be started.")

    def _tool1_about(self, lane_key):
        self._ensure_tool1()
        lane_app = self.tool1_lanes.get(lane_key)
        if lane_app is not None:
            lane_app.show_about()
        else:
            messagebox.showerror("Tool 1 unavailable", "Tool 1 couldn't be started.")

    # ------------------------------------------------------------------
    def on_close(self):
        if self.tool2_app is not None:
            try:
                self.tool2_app.save_settings()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()
