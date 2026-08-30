"""
Simple UI for the Körber bot.

Pick GDN or GRN first — the bot then opens a fresh browser, logs in, and
navigates straight to that page, all in one click.

RUN:
    python korber_app.py
"""

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

import korber_login_bot as bot  # reuses open_new_browser() and login() from the file we already built

# How many extra attempts a single step gets before it's treated as a real
# failure, and how long to pause between attempts. Bump STEP_RETRIES up (or
# STEP_RETRY_DELAY) if the system is reliably slow enough that 2 retries
# isn't cutting it.
STEP_RETRIES = 2
STEP_RETRY_DELAY = 2  # seconds
RETRYABLE_EXCEPTIONS = (TimeoutException, StaleElementReferenceException)


def play_completion_beep():
    """Plays a ~1 second beep once GRN finishes printing, so the person
    doesn't have to keep watching the status label to know it's done.

    winsound is Windows-only (this is a Selenium/desktop automation tool,
    so Windows is the expected environment) — if it's not available for
    any reason, we fall back to the terminal bell rather than raising, so
    a beep failure never breaks/blocks the actual completed flow."""
    try:
        import winsound
        winsound.Beep(1000, 1000)  # 1000 Hz for 1000 ms
    except Exception:
        try:
            print("\a", end="", flush=True)
        except Exception:
            pass


class KorberApp:
    def __init__(self, root):
        self.root = root
        self.driver = None

        # State kept around so a failed run can be resumed with "Retry from
        # here" instead of starting the whole browser session over.
        self._current_steps = None      # the ordered step list for the run in progress
        self._current_ctx = None        # dict of values steps hand to later steps (gdn_number, etc.)
        self._current_doc_type = None
        self._failed_step_index = None  # index into _current_steps of the step that last failed

        root.title("Körber Automation")
        root.geometry("440x600")
        root.minsize(440, 600)
        root.configure(bg="#f4f6f8")

        # --- Theming ---
        # 'clam' is the most reliably customizable stock ttk theme across
        # platforms (unlike the native Windows theme, its colors/borders
        # actually respond to style overrides), so it's the base for a
        # cleaner look without adding a third-party dependency.
        ACCENT = "#1c3f60"       # Körber-ish dark navy/blue
        ACCENT_HOVER = "#274d73"
        SUCCESS = "#1f8a4c"
        DANGER = "#b3392c"
        BG = "#f4f6f8"
        CARD_BG = "#ffffff"
        MUTED = "#6b7280"

        style = ttk.Style(root)
        style.theme_use("clam")

        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("Header.TFrame", background=ACCENT)

        style.configure("TLabel", background=BG, foreground="#1f2937", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=CARD_BG, foreground="#1f2937", font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=ACCENT, foreground="#ffffff", font=("Segoe UI", 15, "bold"))
        style.configure("HeaderSub.TLabel", background=ACCENT, foreground="#cbd5e1", font=("Segoe UI", 9))
        style.configure("SectionTitle.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI", 11, "bold"))
        style.configure("Status.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9), wraplength=380)

        style.configure("TEntry", padding=6, fieldbackground="#ffffff")
        style.configure("TCombobox", padding=6)

        style.configure(
            "Primary.TButton", background=ACCENT, foreground="#ffffff",
            font=("Segoe UI", 10, "bold"), padding=10, borderwidth=0
        )
        style.map("Primary.TButton",
                  background=[("active", ACCENT_HOVER), ("disabled", "#9aa5b1")],
                  foreground=[("disabled", "#e5e7eb")])

        style.configure(
            "Secondary.TButton", background="#e5e7eb", foreground="#1f2937",
            font=("Segoe UI", 10), padding=9, borderwidth=0
        )
        style.map("Secondary.TButton", background=[("active", "#d1d5db")])

        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab", background="#e5e7eb", foreground="#374151",
            font=("Segoe UI", 10, "bold"), padding=(18, 8)
        )
        style.map("TNotebook.Tab",
                  background=[("selected", CARD_BG)],
                  foreground=[("selected", ACCENT)])

        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#e5e7eb", borderwidth=0)

        self.status_var = tk.StringVar(value="Fill in the details, then choose GDN or GRN")

        # --- Header banner ---
        header = ttk.Frame(root, style="Header.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Körber Automation", style="Header.TLabel").pack(
            anchor="w", padx=20, pady=(16, 0)
        )
        ttk.Label(header, text="GDN / GRN creation bot", style="HeaderSub.TLabel").pack(
            anchor="w", padx=20, pady=(0, 14)
        )

        body = ttk.Frame(root, style="TFrame")
        body.pack(fill="both", expand=True, padx=18, pady=16)

        # --- Tabs: GDN / GRN ---
        notebook = ttk.Notebook(body)
        notebook.pack(fill="both", expand=True)

        gdn_tab = ttk.Frame(notebook, style="Card.TFrame", padding=18)
        grn_tab = ttk.Frame(notebook, style="Card.TFrame", padding=18)
        notebook.add(gdn_tab, text="  GDN  ")
        notebook.add(grn_tab, text="  GRN  ")

        # --- GDN tab ---
        gdn_tab.columnconfigure(1, weight=1)

        ttk.Label(gdn_tab, text="Warehouse ID", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.warehouse_entry = ttk.Entry(gdn_tab)
        self.warehouse_entry.grid(row=0, column=1, sticky="ew", pady=(0, 12), padx=(10, 0))

        ttk.Label(gdn_tab, text="Client Code", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 12))
        self.client_entry = ttk.Entry(gdn_tab)
        self.client_entry.grid(row=1, column=1, sticky="ew", pady=(0, 12), padx=(10, 0))

        ttk.Label(gdn_tab, text="Gate Pass No.", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 12))
        self.gatepass_entry = ttk.Entry(gdn_tab)
        self.gatepass_entry.grid(row=2, column=1, sticky="ew", pady=(0, 12), padx=(10, 0))

        ttk.Label(gdn_tab, text="Delivery Location", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 12))
        self.delivery_entry = ttk.Entry(gdn_tab)
        self.delivery_entry.grid(row=3, column=1, sticky="ew", pady=(0, 12), padx=(10, 0))

        ttk.Label(gdn_tab, text="Seal No.", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 20))
        self.seal_entry = ttk.Entry(gdn_tab)
        self.seal_entry.grid(row=4, column=1, sticky="ew", pady=(0, 20), padx=(10, 0))

        self.gdn_btn = ttk.Button(
            gdn_tab, text="Create GDN", style="Primary.TButton",
            command=lambda: self.run_flow("GDN")
        )
        self.gdn_btn.grid(row=5, column=0, columnspan=2, sticky="ew")

        # --- GRN tab (separate fields, not shared with GDN) ---
        grn_tab.columnconfigure(1, weight=1)

        ttk.Label(grn_tab, text="Warehouse ID", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.grn_warehouse_entry = ttk.Combobox(
            grn_tab, state="readonly", values=["EGDC", "ESKD", "NUGE"]
        )
        self.grn_warehouse_entry.grid(row=0, column=1, sticky="ew", pady=(0, 12), padx=(10, 0))

        ttk.Label(grn_tab, text="Gate Pass No.", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 20))
        self.grn_gatepass_entry = ttk.Entry(grn_tab)
        self.grn_gatepass_entry.grid(row=1, column=1, sticky="ew", pady=(0, 20), padx=(10, 0))

        self.grn_btn = ttk.Button(
            grn_tab, text="Create GRN", style="Primary.TButton",
            command=lambda: self.run_flow("GRN")
        )
        self.grn_btn.grid(row=2, column=0, columnspan=2, sticky="ew")

        # --- Clear button (applies to both tabs) ---
        self.clear_btn = ttk.Button(
            body, text="Clear All Fields", style="Secondary.TButton",
            command=self.clear_fields
        )
        self.clear_btn.pack(fill="x", pady=(14, 0))

        # --- Status card (always visible, below the tabs) ---
        status_card = ttk.Frame(body, style="TFrame")
        status_card.pack(fill="x", pady=(16, 0))

        ttk.Label(status_card, textvariable=self.status_var, style="Status.TLabel").pack(
            anchor="w", fill="x"
        )
        self.progress = ttk.Progressbar(status_card, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(8, 0))

    def _start_progress(self):
        self.progress.start(12)

    def _stop_progress(self):
        self.progress.stop()

    def clear_fields(self):
        self.warehouse_entry.delete(0, tk.END)
        self.client_entry.delete(0, tk.END)
        self.gatepass_entry.delete(0, tk.END)
        self.delivery_entry.delete(0, tk.END)
        self.seal_entry.delete(0, tk.END)
        self.grn_warehouse_entry.set("")
        self.grn_gatepass_entry.delete(0, tk.END)
        self.set_status("Fields cleared")

    def set_status(self, text):
        self.status_var.set(text)
        self.root.update_idletasks()

    def run_flow(self, doc_type: str):
        if doc_type == "GDN":
            warehouse_id = self.warehouse_entry.get().strip()
            client_code = self.client_entry.get().strip()
            gate_pass_number = self.gatepass_entry.get().strip()
            delivery_location = self.delivery_entry.get().strip()
            seal_number = self.seal_entry.get().strip()

            if not all([warehouse_id, client_code, gate_pass_number, delivery_location, seal_number]):
                messagebox.showwarning("Missing info", "Please fill in all five GDN fields first.")
                return
        else:  # GRN uses its own separate fields
            warehouse_id = self.grn_warehouse_entry.get().strip()
            gate_pass_number = self.grn_gatepass_entry.get().strip()
            client_code = delivery_location = seal_number = ""  # not used for GRN

            if not all([warehouse_id, gate_pass_number]):
                messagebox.showwarning("Missing info", "Please fill in the GRN Warehouse ID and Gate Pass Number first.")
                return

        # Fresh run: no steps/context/failure to resume from yet.
        self._current_steps = None
        self._current_ctx = None
        self._failed_step_index = None

        self.gdn_btn.config(state=tk.DISABLED)
        self.grn_btn.config(state=tk.DISABLED)
        self._start_progress()
        self.set_status(f"Opening browser for {doc_type}...")
        threading.Thread(
            target=self._run_flow_worker,
            args=(doc_type, warehouse_id, client_code, gate_pass_number, delivery_location, seal_number),
            daemon=True,
        ).start()

    def _build_grn_steps(self, warehouse_id, gate_pass_number):
        """GRN only needs to reach the page and fill two fields for now —
        no query/insert/print pipeline has been defined for it yet (unlike
        GDN's multi-step flow), so this stays short until that's specified."""

        def opening_browser():
            self.driver = bot.open_new_browser(headless=False)

        def logging_in():
            bot.login(self.driver)

        def opening_grn_page():
            navigate_to_grn(self.driver)

        def filling_form():
            fill_grn_form(self.driver, warehouse_id, gate_pass_number)

        def submitting_query():
            click_query_button(self.driver)

        def setting_page_size():
            set_page_size(self.driver, "100")

        def clicking_select_all():
            click_select_all_checkbox(self.driver)

        def clicking_create_grn():
            click_create_grn_at_gatepass(self.driver)

        def clicking_grn_details():
            click_grn_details_button(self.driver, timeout=30)

        def clicking_print_grn_sku():
            click_print_grn_sku(self.driver)

        def waiting_for_grn_report():
            wait_for_grn_report(self.driver)

        def beeping_after_report_ready():
            # Beeps once the report/details have actually finished
            # rendering on screen.
            play_completion_beep()

        return [
            ("opening browser", "Opening browser...", opening_browser),
            ("logging in", "Logging in...", logging_in),
            ("opening GRN page", "Opening GRN page...", opening_grn_page),
            ("filling form", "Filling form...", filling_form),
            ("submitting query", "Submitting query...", submitting_query),
            ("setting page size to 100", "Setting page size...", setting_page_size),
            ("clicking select all", "Selecting all rows...", clicking_select_all),
            ("clicking Create GRN @ GatePass", "Creating GRN @ GatePass...", clicking_create_grn),
            # This page can be genuinely slow to load after Create GRN @
            # GatePass, so this step gets many more automatic retries (and a
            # longer per-attempt wait, see timeout=30 above) than the rest
            # of the flow before it's treated as a real failure.
            ("clicking GRN Details", "Opening GRN Details (can take a while)...", clicking_grn_details, 8),
            ("clicking Print GRN - SKU", "Printing GRN - SKU...", clicking_print_grn_sku),
            ("waiting for the GRN report to render", "Generating GRN report...", waiting_for_grn_report),
            ("beeping after GRN report renders", "GRN report ready...", beeping_after_report_ready),
        ]

    def _build_steps(self, doc_type, warehouse_id, client_code, gate_pass_number, delivery_location, seal_number, ctx):
        """Builds the ordered list of (name, status_text, func) steps for one
        full run. ctx is a plain dict the step funcs read/write into (e.g.
        the query_li/add_gdn_link/gdn_number handed from one step to the
        next), so the SAME list + ctx can be re-run starting partway through
        for the 'Retry from here' flow, instead of starting the whole
        browser session over."""

        def opening_browser():
            self.driver = bot.open_new_browser(headless=False)

        def logging_in():
            bot.login(self.driver)

        def opening_doc_page():
            if doc_type == "GDN":
                navigate_to_gdn(self.driver)
            else:
                navigate_to_grn(self.driver)

        def filling_form():
            fill_gdn_form(self.driver, warehouse_id, client_code, gate_pass_number)

        def submitting_query():
            ctx["query_li"] = click_query_button(self.driver)

        def waiting_results():
            wait_for_query_results(self.driver, old_query_li=ctx.get("query_li"))

        def clicking_add_gdn():
            ctx["add_gdn_link"] = click_add_gdn(self.driver)

        def waiting_add_gdn_page():
            wait_for_add_gdn_page(self.driver, old_add_gdn_link=ctx.get("add_gdn_link"))

        def pausing_after_add_gdn():
            time.sleep(2)

        def capturing_gdn_number():
            ctx["gdn_number"] = capture_gdn_number(self.driver)

        def refilling_warehouse():
            fill_warehouse_id(self.driver, warehouse_id)

        def pausing_after_warehouse():
            time.sleep(2)

        def refilling_client():
            fill_client_code(self.driver, client_code)

        def refilling_gatepass():
            fill_gate_pass_number(self.driver, gate_pass_number)

        def filling_delivery():
            fill_delivery_location(self.driver, delivery_location)

        def filling_seal():
            fill_seal_number(self.driver, seal_number)

        def clicking_insert():
            ctx["insert_link"] = click_insert_button(self.driver)

        def waiting_insert_result():
            wait_for_insert_result(self.driver, old_insert_link=ctx.get("insert_link"))

        def clicking_add_gdn_detail_step():
            click_add_gdn_detail(self.driver)

        def clicking_add_all_step():
            click_add_all_to_gdn(self.driver)

        def checking_ok_dialog():
            click_ok_if_present(self.driver)

        def clicking_send():
            click_send_button(self.driver)

        def clicking_back_twice():
            def click_with_retries(click_fn, label, retries=3):
                last_exc = None
                for attempt in range(retries):
                    try:
                        click_fn(self.driver)
                        return
                    except RETRYABLE_EXCEPTIONS as e:
                        last_exc = e
                        self.set_status(f"{label} click didn't register yet, retrying...")
                        time.sleep(1.5)
                raise last_exc

            for i in range(2):
                self.set_status(f"Clicking Back ({i + 1}/2)...")
                click_with_retries(click_back_button, "Back")
                time.sleep(0.5)

        def clicking_gdn_row():
            click_gdn_number_link(self.driver, ctx["gdn_number"])

        def clicking_print():
            click_print_gdn_sku(self.driver)

        def waiting_for_gdn_report():
            wait_for_gdn_report(self.driver)

        def beeping_after_gdn_report_ready():
            # Beeps once the GDN PDF has actually finished rendering on
            # screen, not just that the print click was sent.
            play_completion_beep()

        return [
            ("opening browser", "Opening browser...", opening_browser),
            ("logging in", "Logging in...", logging_in),
            (f"opening {doc_type} page", f"Opening {doc_type} page...", opening_doc_page),
            ("filling form", "Filling form...", filling_form),
            ("submitting query", "Submitting query...", submitting_query),
            ("waiting for results page to load", "Loading results...", waiting_results),
            ("clicking Add GDN", "Adding GDN...", clicking_add_gdn),
            ("waiting for the Add GDN detail page to load", "Loading detail page...", waiting_add_gdn_page),
            ("pausing after the Add GDN detail page loads", "Waiting for page to settle...", pausing_after_add_gdn),
            ("capturing the auto-generated GDN number", "Reading GDN number...", capturing_gdn_number),
            ("re-filling Warehouse ID on the detail page", "Filling Warehouse ID again...", refilling_warehouse),
            ("pausing after Warehouse ID is changed", "Waiting after Warehouse ID change...", pausing_after_warehouse),
            ("re-filling Client Code on the detail page", "Filling Client Code again...", refilling_client),
            ("re-filling Gate Pass Number on the detail page", "Filling Gate Pass Number again...", refilling_gatepass),
            ("filling Delivery Location on the detail page", "Filling Delivery Location...", filling_delivery),
            ("filling Seal No. on the detail page", "Filling Seal No...", filling_seal),
            ("clicking Insert", "Inserting...", clicking_insert),
            ("waiting for the page after Insert to load", "Loading next page...", waiting_insert_result),
            ("clicking ADD GDN DETAIL", "Adding GDN detail...", clicking_add_gdn_detail_step),
            ("clicking Add All to GDN", "Adding all to GDN...", clicking_add_all_step),
            ("checking for an OK confirmation dialog", "Checking for confirmation dialog...", checking_ok_dialog),
            ("clicking Send", "Sending...", clicking_send),
            ("clicking Back twice", "Navigating back...", clicking_back_twice),
            ("clicking the GDN number row", "Opening GDN row...", clicking_gdn_row),
            ("clicking PRINT GDN - SKU", "Printing GDN - SKU...", clicking_print),
            ("waiting for the GDN report to render", "Generating GDN PDF...", waiting_for_gdn_report),
            ("beeping after GDN report renders", "GDN PDF ready...", beeping_after_gdn_report_ready),
        ]

    def _run_step_with_retry(self, func, retries=STEP_RETRIES, delay=STEP_RETRY_DELAY):
        """Runs one step, automatically retrying a few times if it fails
        with a timeout-flavored exception (the kind system slowness causes)
        before letting the failure bubble up to the retry-from-here dialog.

        Before every attempt, waits out the app's processing spinner if
        it's showing (self.driver is None only for the very first step,
        "opening browser", which hasn't created a driver yet)."""
        last_exc = None
        for attempt in range(retries + 1):
            if self.driver is not None:
                wait_for_loading_to_disappear(self.driver)
            try:
                func()
                return
            except RETRYABLE_EXCEPTIONS as e:
                last_exc = e
                if attempt < retries:
                    self.set_status(f"Slow response, retrying... (attempt {attempt + 2}/{retries + 1})")
                    time.sleep(delay)
        raise last_exc

    def _run_flow_worker(self, doc_type, warehouse_id, client_code, gate_pass_number, delivery_location, seal_number):
        ctx = {}
        if doc_type == "GDN":
            steps = self._build_steps(doc_type, warehouse_id, client_code, gate_pass_number, delivery_location, seal_number, ctx)
        else:
            steps = self._build_grn_steps(warehouse_id, gate_pass_number)
        self._current_steps = steps
        self._current_ctx = ctx
        self._current_doc_type = doc_type
        self._execute_steps(steps, ctx, 0, doc_type)

    def _execute_steps(self, steps, ctx, start_index, doc_type):
        """Runs steps[start_index:], in order. Used both for a fresh run
        (start_index=0) and for 'Retry from here' (start_index = the step
        that failed last time), reusing the same driver session and ctx
        so we don't have to log in and navigate all over again."""
        for i in range(start_index, len(steps)):
            step = steps[i]
            name, status_text, func = step[0], step[1], step[2]
            step_retries = step[3] if len(step) > 3 else STEP_RETRIES
            self.set_status(status_text)
            try:
                self._run_step_with_retry(func, retries=step_retries)
            except Exception as e:
                self._failed_step_index = i
                self._stop_progress()
                self.set_status(f"Failed ({doc_type}) during: {name}")
                self._report_error(name, e)
                return  # leave buttons disabled + driver open until user decides in the dialog

        if doc_type == "GDN":
            gdn_number = ctx.get("gdn_number", "")
            self.set_status(f"{doc_type} {gdn_number} completed and printed")
        else:
            self.set_status(f"{doc_type} created and printed")
        self._failed_step_index = None
        self._stop_progress()
        self.gdn_btn.config(state=tk.NORMAL)
        self.grn_btn.config(state=tk.NORMAL)

    def _cancel_after_failure(self):
        self._current_steps = None
        self._current_ctx = None
        self._failed_step_index = None
        self._stop_progress()
        self.gdn_btn.config(state=tk.NORMAL)
        self.grn_btn.config(state=tk.NORMAL)
        self.set_status("Cancelled after failure — fill in details and try again")

    def _report_error(self, step, e):
        """Shows exactly which step failed, the exception type/message, and
        saves a screenshot + page source next to the script so we can see
        what the page actually looked like at the moment of failure. Then
        offers 'Retry from here' (resume from this exact step) or 'Cancel'."""
        err_type = type(e).__name__
        err_msg = str(e).strip().splitlines()[0] if str(e).strip() else "(no message provided)"

        screenshot_path = None
        html_path = None
        if self.driver is not None:
            try:
                screenshot_path = "korber_failure_screenshot.png"
                self.driver.save_screenshot(screenshot_path)
            except Exception:
                pass
            try:
                html_path = "korber_failure_page.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
            except Exception:
                pass

        details = f"Failed during step: {step}\n\nException type: {err_type}\nMessage: {err_msg}"
        details += f"\n\n(Already retried {STEP_RETRIES} extra time(s) automatically before giving up.)"
        if screenshot_path:
            details += f"\n\nScreenshot saved: {screenshot_path}"
        if html_path:
            details += f"\nPage HTML saved: {html_path}"

        # Tkinter widgets must be created on the main thread; this method
        # runs on the worker thread, so schedule the messagebox via root.after().
        self.root.after(0, lambda: self._show_failure_and_reset(details))

    def _show_failure_and_reset(self, details):
        messagebox.showerror("Failed", details)
        self._cancel_after_failure()


# ---------------------------------------------------------------------------
# GDN is fully wired up. GRN still needs its search code (see TODO below).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Loading spinner — waited out before every click/interaction step below,
# so the bot moves as fast as the system allows instead of using fixed
# sleeps (fast system = no wasted wait, slow system = waits as long as
# actually needed).
# ---------------------------------------------------------------------------

def wait_for_loading_to_disappear(driver, timeout=30):
    """Waits for the app's processing/loading spinner
    (data-hj-test-id="processing-dialog-container") to disappear, if it's
    showing at all.

    Two-phase: first a very short check for whether the spinner is even
    present right now (most of the time it won't be, since this gets
    called before nearly every step) — if it's not there, return
    immediately rather than waiting out a full timeout for nothing. If it
    IS present, wait up to `timeout` seconds for it to go away."""
    quick_wait = WebDriverWait(driver, 0.5)
    try:
        spinner = quick_wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div[data-hj-test-id='processing-dialog-container']")
            )
        )
    except TimeoutException:
        return  # not showing right now — nothing to wait for

    long_wait = WebDriverWait(driver, timeout)
    try:
        long_wait.until(EC.invisibility_of_element(spinner))
    except TimeoutException:
        # Element might have been removed from the DOM entirely rather than
        # just hidden, in which case invisibility_of_element can time out
        # even though it's genuinely gone. Confirm with a fresh lookup —
        # only re-raise if it's actually still there and visible.
        try:
            still_there = driver.find_element(
                By.CSS_SELECTOR, "div[data-hj-test-id='processing-dialog-container']"
            )
            if still_there.is_displayed():
                raise
        except Exception:
            pass  # gone from the DOM — treat as disappeared


def open_menu_and_search(driver, search_code: str, result_text: str):
    """Shared steps: open the side menu, type a code into the search box,
    then click the menu item matching result_text."""
    wait = WebDriverWait(driver, 20)

    # Confirmed: hamburger menu toggle button
    menu_toggle = wait.until(
        EC.element_to_be_clickable((By.ID, "menuButtonToggle"))
    )
    menu_toggle.click()

    # The menu slides open with a CSS animation, so the search box exists in
    # the DOM immediately but isn't visible/interactable yet. Wait for
    # visibility (not just presence), with a short buffer for the animation.
    search_box = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "input[data-hj-test-id='menuSearchTextBox']")
        )
    )
    time.sleep(0.5)  # small buffer in case the animation is still finishing

    try:
        search_box.click()
    except Exception:
        driver.execute_script("arguments[0].click();", search_box)

    search_box.clear()
    search_box.send_keys(search_code)

    # Confirmed: menu item structure — <span class="title"> holds the display text
    menu_item = wait.until(
        EC.visibility_of_element_located(
            (By.XPATH, f"//span[@class='title' and text()='{result_text}']/ancestor::a")
        )
    )
    try:
        menu_item.click()
    except Exception:
        driver.execute_script("arguments[0].click();", menu_item)


def navigate_to_gdn(driver):
    # Confirmed: search code 1703 -> "Goods Delivery Note"
    open_menu_and_search(driver, "1703", "Goods Delivery Note")


def navigate_to_grn(driver):
    # Confirmed: search code 1712 -> "Print GRN" menu item
    open_menu_and_search(driver, "1712", "Print GRN")


# ---------------------------------------------------------------------------
# GDN form filling
# ---------------------------------------------------------------------------

def set_kendo_dropdown_value(driver, select_element, code):
    """Sets a Kendo dropdownlist's value via its own JS API instead of
    simulating clicks — far more reliable than clicking through the popup,
    since Kendo renders its option list in a separate floating panel with
    its own open/close animation.

    IMPORTANT: the underlying <option value="..."> attribute is NOT
    consistently just the bare code across this app's dropdowns:
      - Warehouse ID options: value="EGDC" (just the code)
      - Client Code options:  value="HIES - HIRDARAMANI INTERNATIONAL EXPO"
        (code + " - " + full name, not just "HIES")
    So we can't just call widget.value(code) directly for every dropdown —
    it would silently fail to select anything on dropdowns like Client Code
    where the option value isn't an exact match to the short code the user
    types in. Instead we search the <option> list for one whose value is
    EITHER an exact match to the code OR starts with "{code} -", and use
    whichever full value we find.

    select_element: the underlying <select> Selenium WebElement (the one
    with data-role="dropdownlist"), NOT the outer <hj-dropdownlist> tag.
    code: the short code the user provided, e.g. "EGDC" or "HIES" — not
    necessarily the full option value.
    """
    driver.execute_script(
        """
        var $select = jQuery(arguments[0]);
        var widget = $select.data('kendoDropDownList');
        if (!widget) { throw 'Kendo widget not initialized on this element'; }

        var code = arguments[1];
        var match = null;
        $select.find('option').each(function() {
            var v = this.value;
            if (v === code) {
                match = v;
                return false;  // break out of jQuery.each
            }
            // Handle "CODE - Full Name" / "CODE-Full Name" style options
            // (separator spacing isn't consistent across every dropdown on
            // this app), while avoiding a false match on a longer code that
            // merely starts with the same letters (e.g. "EG" vs "EGDC").
            if (v.indexOf(code) === 0) {
                var next = v.charAt(code.length);
                if (next === '' || next === ' ' || next === '-') {
                    match = v;
                    return false;
                }
            }
        });
        if (match === null) {
            throw 'No matching option found for code: ' + code;
        }

        widget.value(match);
        widget.trigger('change');
        """,
        select_element,
        code,
    )


def get_field_cell(driver, label_text: str):
    """Finds the <hj-field-cell> wrapping a field by its visible label text.
    Works for any field on this form (Warehouse ID, Client Code, etc.) since
    they all share the same hj-field-cell / hj-field-label structure.

    IMPORTANT #1: this is a knockout/kendo SPA where the previous page's
    elements sometimes linger in the DOM (hidden) instead of being removed
    when a new page loads. That means more than one <hj-field-cell> can
    match the same label at once -- an old, hidden one from the page we
    just left, and the new, visible one on the current page. Using
    presence_of_element_located() alone would happily return whichever one
    comes first in the HTML, which can silently be the stale/hidden one --
    the fields then get "filled in" on a page you can't see, which looks
    like nothing happened. So we explicitly wait for and return the first
    match that is actually visible/displayed.

    IMPORTANT #2: label casing is NOT consistent across pages for the same
    field -- confirmed from a failure page dump that the first page renders
    "Client Code" (title case) while the "Add Goods Delivery Note" detail
    page renders "client code" (all lowercase) for that same field. A
    case-sensitive text() match will silently find nothing and time out on
    pages that use different casing, so we compare case-insensitively via
    XPath's translate().

    IMPORTANT #3: some required fields render their label with a leading
    '*' fused into the SAME span as the text (e.g. "*Delivery To"), not as
    a separate element -- confirmed from a screenshot of the live page. An
    exact match against "delivery to" would never match "*delivery to", so
    we also strip a leading '*' from the label text via translate() before
    comparing.
    """
    wait = WebDriverWait(driver, 20)
    label_lower = label_text.lower()
    xpath = (
        "//hj-field-cell[.//hj-label//span[normalize-space(translate(translate("
        "text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
        "'*', ''))"
        f"='{label_lower}']]"
    )

    def _first_visible_match(d):
        for cell in d.find_elements(By.XPATH, xpath):
            if cell.is_displayed():
                return cell
        return False

    return wait.until(_first_visible_match)


def capture_gdn_number(driver):
    """Reads the auto-generated GDN number (e.g. 'GDN0000010209') from the
    'GDN' field on the detail page -- this value is assigned by the system
    and is different every run, so we can't hardcode it anywhere. We read
    it here and hold onto it so we can later find and click the matching
    row in a results list (the row shows this same number as its link
    text, confirmed by the user)."""
    gdn_cell = get_field_cell(driver, "GDN")
    gdn_input = gdn_cell.find_element(By.CSS_SELECTOR, "input.k-textbox")
    return gdn_input.get_attribute("value").strip()


def fill_gdn_form(driver, warehouse_id: str, client_code: str, gate_pass_number: str):
    # Confirmed: Warehouse ID field located via its label + Kendo dropdown
    warehouse_cell = get_field_cell(driver, "Warehouse ID")
    warehouse_select = warehouse_cell.find_element(By.CSS_SELECTOR, "select[data-role='dropdownlist']")
    set_kendo_dropdown_value(driver, warehouse_select, warehouse_id)

    # ASSUMED label text "Client Code" — confirm this matches what's on screen;
    # same dropdown structure as Warehouse ID assumed.
    client_cell = get_field_cell(driver, "Client Code")
    client_select = client_cell.find_element(By.CSS_SELECTOR, "select[data-role='dropdownlist']")
    set_kendo_dropdown_value(driver, client_select, client_code)

    # ASSUMED label text "Gate Pass Number" and a plain text input (like the
    # hj-textbox pattern from the login page) — confirm both if this fails.
    gatepass_cell = get_field_cell(driver, "Gate Pass Number")
    gatepass_input = gatepass_cell.find_element(By.CSS_SELECTOR, "input.k-textbox")
    gatepass_input.clear()
    gatepass_input.send_keys(gate_pass_number)


def fill_grn_form(driver, warehouse_id: str, gate_pass_number: str):
    """GRN's initial form only has two fields to fill (unlike GDN's three) —
    reuses the same generic get_field_cell()/set_kendo_dropdown_value()
    helpers already confirmed working for GDN, since the underlying field
    structure (hj-field-cell wrapping a Kendo dropdown or hj-textbox) is
    shared across the whole app.

    Confirmed from a screenshot of the "Search Print GRN" page: the gate
    pass field is labeled "Gate Pass ID" here (not "Gate Pass Number" like
    on GDN), and it's a filter-style box next to a "Like" dropdown -- same
    hj-field-cell/hj-textbox structure though, so no other changes needed.
    """
    warehouse_cell = get_field_cell(driver, "Warehouse ID")
    warehouse_select = warehouse_cell.find_element(By.CSS_SELECTOR, "select[data-role='dropdownlist']")
    set_kendo_dropdown_value(driver, warehouse_select, warehouse_id)

    gatepass_cell = get_field_cell(driver, "Gate Pass ID")
    gatepass_input = gatepass_cell.find_element(By.CSS_SELECTOR, "input.k-textbox")
    gatepass_input.clear()
    gatepass_input.send_keys(gate_pass_number)


def set_grid_page_size(driver, size: str):
    """Sets the grid's 'items per page' dropdown to the given size (e.g.
    '100'). This dropdown has no label or unique id/data-hj-test-id, so
    instead of guessing at its container we identify it by its option
    fingerprint: Kendo's standard page-size dropdown uses exactly
    5/10/15/20/25/50/100 as its options, which should be unique on this
    page regardless of where it sits in the layout."""
    driver.execute_script(
        """
        var target = null;
        var expected = ['5', '10', '15', '20', '25', '50', '100'];
        document.querySelectorAll("select[data-role='dropdownlist']").forEach(function(sel) {
            var values = Array.prototype.map.call(sel.options, function(o) { return o.value; });
            if (values.length === expected.length && values.every(function(v, i) { return v === expected[i]; })) {
                target = sel;
            }
        });
        if (!target) { throw 'Page size dropdown not found (expected options 5/10/15/20/25/50/100)'; }

        var widget = jQuery(target).data('kendoDropDownList');
        if (!widget) { throw 'Kendo widget not initialized on page size dropdown'; }
        widget.value(arguments[0]);
        widget.trigger('change');
        """,
        size,
    )


def set_page_size(driver, size: str):
    """Sets the grid's 'rows per page' dropdown (options: 5/10/15/20/25/50/100).
    No unique ID or label on this one, but the specific combination of
    option values is distinctive enough on this page to find it reliably."""
    wait = WebDriverWait(driver, 20)
    xpath = (
        "//select[@data-role='dropdownlist']"
        "[option[@value='5'] and option[@value='10'] and option[@value='100']]"
    )
    page_size_select = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    set_kendo_dropdown_value(driver, page_size_select, size)


def click_query_button(driver):
    """Clicks the 'Query' button to move to the next page. The <li> itself
    has no click handler — the knockout binding (click: click) lives on the
    inner <a>, so we need to locate and click that specifically.

    Important: the <li> gets a 'disabled' CSS class (via Knockout's
    isDisabled binding) right after the form is filled, until Knockout's
    digest cycle catches up with the Kendo dropdown 'change' events. If we
    click before that clears, the click is silently swallowed or throws a
    low-level WebDriver exception with no readable message. So we wait for
    the 'disabled' class to actually be gone from the <li> first."""
    wait = WebDriverWait(driver, 20)

    query_li = wait.until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "li[data-hj-test-id='query-button']")
        )
    )

    # Wait until Knockout removes the 'disabled' class from the <li>
    wait.until(
        lambda d: "disabled" not in query_li.get_attribute("class").split()
    )

    query_link = query_li.find_element(By.CSS_SELECTOR, "a")

    # JS click first — sidesteps ElementClickInterceptedException from any
    # overlay/animation still settling right as the button becomes enabled.
    try:
        driver.execute_script("arguments[0].click();", query_link)
    except Exception:
        query_link.click()

    return query_li  # handed to wait_for_query_results() for a staleness check


def click_select_all_checkbox(driver):
    """Clicks the grid's 'select all' header checkbox (top-left cell of the
    results grid).

    IMPORTANT: the original inspect snippet showed the <th> with
    class="k-header selected-all", but a failure-page HTML dump confirmed
    the live DOM only has class="k-header" -- "selected-all" is evidently
    added conditionally (e.g. on hover) rather than always present, so a
    selector depending on it times out waiting for a class that may never
    show up. The one thing that's stable in both states is the inner
    <span class="select-all-icon"> icon, so we match on that instead and
    click its <th> ancestor (falling back to clicking the span itself if
    the th click doesn't register)."""
    wait = WebDriverWait(driver, 20)

    icon_span = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "span.select-all-icon"))
    )

    try:
        target_th = icon_span.find_element(By.XPATH, "./ancestor::th[1]")
    except Exception:
        target_th = icon_span

    try:
        driver.execute_script("arguments[0].click();", target_th)
    except Exception:
        try:
            target_th.click()
        except Exception:
            driver.execute_script("arguments[0].click();", icon_span)

    return target_th


def click_create_grn_at_gatepass(driver):
    """Clicks the 'Create GRN @ GatePass' button. Same structure as 'Add
    All to GDN' / 'PRINT GDN - SKU': the wrapping <li> has a Knockout
    `disabled` binding, and `data-hj-test-id` is bound to a dynamic
    observable (not a fixed string we can rely on), so we locate by visible
    text and wait for 'disabled' to clear on that specific <li> before
    clicking the inner <a>.

    Clicks exactly ONCE. An earlier version of this function retried the
    click if the button's <li> didn't go stale within a few seconds — but
    on this page the click doesn't remove that element, it just triggers
    the loading spinner, so that check was firing genuine EXTRA clicks on
    the live system (risking duplicate GRN creation), not just retrying a
    failed one. Now that wait_for_loading_to_disappear() runs automatically
    before every step (including the next one, GRN Details), there's no
    need for this function to also wait/verify — the spinner-wait on the
    following step covers that."""
    wait = WebDriverWait(driver, 20)

    grn_li = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//span[normalize-space(text())='Create GRN @ GatePass']/ancestor::li[1]")
        )
    )
    wait.until(
        lambda d: "disabled" not in (grn_li.get_attribute("class") or "").split()
    )
    grn_link = grn_li.find_element(By.CSS_SELECTOR, "a")

    try:
        driver.execute_script("arguments[0].click();", grn_link)
    except Exception:
        grn_link.click()

    return grn_link


def click_grn_details_button(driver, timeout=5):
    """Clicks the 'GRN Details' button that appears after 'Create GRN @
    GatePass' succeeds.

    Confirmed structure from a live page snippet: the visible text sits in
    <hj-label class="label-cell-content"><span data-bind="text: _text, ...">
    GRN Details</span></hj-label> — the same hj-label/span text wrapper
    pattern used elsewhere in this app (both for field labels and for
    toolbar button captions), so we match on the visible span text and
    climb to the nearest clickable ancestor, same approach as
    click_create_grn_at_gatepass / click_add_all_to_gdn: prefer a wrapping
    <li> (with the usual Knockout 'disabled' class to wait out) and fall
    back to a plain ancestor <a> if there's no <li> wrapper."""
    wait = WebDriverWait(driver, timeout)

    try:
        details_li = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//span[normalize-space(text())='GRN Details']/ancestor::li[1]")
            )
        )
        wait.until(
            lambda d: "disabled" not in (details_li.get_attribute("class") or "").split()
        )
        details_link = details_li.find_element(By.CSS_SELECTOR, "a")
    except TimeoutException:
        details_link = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//span[normalize-space(text())='GRN Details']/ancestor::a")
            )
        )

    try:
        driver.execute_script("arguments[0].click();", details_link)
    except Exception:
        details_link.click()

    return details_link


def click_print_grn_sku(driver):
    """Clicks the 'Print GRN - SKU' button that appears after GRN Details
    opens.

    Confirmed structure from a live page snippet: standard toolbar-button
    <li data-bind="template: ..., css: {'disabled': isDisabled, ...}">
    wrapping an <a data-bind="click: click, ...."><span data-bind="text:
    observableText">Print GRN - SKU</span></a> — same disabled-on-the-<li>
    pattern as click_create_grn_at_gatepass/click_add_all_to_gdn, so we wait
    for 'disabled' to clear on that <li> before clicking the inner <a>.

    Note the exact label text is 'Print GRN - SKU' (title case + hyphen
    spacing), which differs from GDN's all-caps 'PRINT GDN - SKU' — and
    unlike that GDN button, nothing here indicates a second, duplicate
    match to disambiguate, so this assumes a single match for now."""
    wait = WebDriverWait(driver, 20)

    print_li = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//span[normalize-space(text())='Print GRN - SKU']/ancestor::li[1]")
        )
    )

    wait.until(
        lambda d: "disabled" not in (print_li.get_attribute("class") or "").split()
    )

    print_link = print_li.find_element(By.CSS_SELECTOR, "a")

    try:
        driver.execute_script("arguments[0].click();", print_link)
    except Exception:
        print_link.click()

    return print_link


def wait_for_report(driver, title_text, timeout=30):
    """Waits for a printed report (GRN or GDN) to finish rendering, by
    switching into its ReportViewer iframe and checking for the report's
    own title text.

    CONFIRMED (from a failure-page dump where a GRN-report wait had timed
    out even though the report was visibly on screen) that these reports
    render inside an <iframe
    src="https://.../ReportServer/Pages/ReportViewer.aspx?...">
    — a genuinely separate (cross-origin) document from the main app page,
    not directly in the main page's DOM. Searching the main page only (the
    original version of this function) silently times out because of that.
    We locate the iframe by its src containing 'ReportViewer.aspx' (its id,
    e.g. 'a1r_report_viewer_2', is knockout-bound and not guaranteed stable
    run to run — same reasoning as avoiding the ReportViewerControl_ctlNN
    ids inside it), switch into it, and check for title_text there instead.

    Also possible (seen elsewhere in this app) that a previous run's
    report iframe lingers hidden in the DOM rather than being removed, so
    we filter to a currently-visible match rather than just the first one
    present, same as get_field_cell()'s stale-duplicate handling.

    Always switches back to the main document afterward (even on timeout),
    since every other step in this flow expects to be operating on the
    main page, not left inside this iframe."""
    wait = WebDriverWait(driver, timeout)

    def _visible_report_iframe(d):
        frames = [
            f for f in d.find_elements(By.CSS_SELECTOR, "iframe[src*='ReportViewer.aspx']")
            if f.is_displayed()
        ]
        return frames[-1] if frames else False

    report_iframe = wait.until(_visible_report_iframe)
    driver.switch_to.frame(report_iframe)
    try:
        wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, f"//*[contains(normalize-space(text()), '{title_text}')]")
            )
        )
    finally:
        driver.switch_to.default_content()


def wait_for_grn_report(driver, timeout=30):
    """Waits for the GRN report (see wait_for_report() for the iframe
    details) — confirmed title text is 'GOODS RECEIVED NOTE'."""
    wait_for_report(driver, "GOODS RECEIVED NOTE", timeout=timeout)


def wait_for_gdn_report(driver, timeout=30):
    """Waits for the GDN report after 'PRINT GDN - SKU' (see
    wait_for_report() for the iframe details). CONFIRMED title text (from a
    screenshot of the rendered report) is 'DELIVERY NOTE' — not 'GOODS
    DELIVERY NOTE' as originally guessed by analogy with the GRN report."""
    wait_for_report(driver, "DELIVERY NOTE", timeout=timeout)


def wait_for_query_results(driver, old_query_li=None, timeout=20):
    """Waits for the results/detail page (that appears after clicking Query)
    to actually finish loading before we try to click anything on it.

    This is a knockout/kendo single-page app, so the URL doesn't change and
    the old page's elements don't necessarily get removed instantly — we
    can't just wait for a URL change or assume the click was synchronous.
    Instead we grab a fresh reference to the Query <li> right after clicking
    it and wait for that specific element to go stale (removed/replaced in
    the DOM), which is a reliable signal that the page has actually moved on.

    old_query_li: pass in the query_li element used to click Query, if you
    have it. If not provided, we fall back to just waiting for the
    'Add GDN' link to become clickable, which implicitly waits for the new
    page too (just with less certainty about a stale intermediate state)."""
    wait = WebDriverWait(driver, timeout)

    if old_query_li is not None:
        wait.until(EC.staleness_of(old_query_li))

    # Belt-and-suspenders: also wait for the Add GDN link itself to be
    # present, since that's the element we actually need next.
    wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//span[normalize-space(text())='Add GDN']/ancestor::a")
        )
    )


def click_add_gdn(driver):
    """Clicks the 'Add GDN' link on the results page (shown after Query is
    submitted). Its data-hj-test-id lives on the parent <li> and is bound to
    an observable ('testId'), so it isn't a fixed, reliable value to select
    on — the visible label text ('Add GDN') is the stable thing here. The
    knockout click binding itself lives on the <a>, not the <li>, so we
    click the ancestor <a> rather than the <li>."""
    wait = WebDriverWait(driver, 20)

    add_gdn_link = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//span[normalize-space(text())='Add GDN']/ancestor::a")
        )
    )
    try:
        add_gdn_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", add_gdn_link)

    return add_gdn_link  # handed to wait_for_add_gdn_page() for a staleness check


def click_insert_button(driver):
    """Clicks the 'Insert' toolbar button to save the filled-in GDN detail.

    Unlike the Query button, the css binding here (`css: $data.cssClasses`)
    lives directly on the <a> itself, not on a wrapping <li> -- so any
    disabled/inactive state would show up as a class on the <a>. We wait
    for that class list to be free of anything containing 'disabled'
    before clicking, same reasoning as click_query_button: Selenium's
    "clickable" check doesn't know about app-level disabled states, only
    genuine DOM-level disabled attributes, so a plain element_to_be_clickable
    wait alone isn't enough of a guarantee here."""
    wait = WebDriverWait(driver, 20)

    insert_link = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//span[normalize-space(text())='Insert']/ancestor::a")
        )
    )

    wait.until(
        lambda d: not any(
            "disabled" in cls.lower()
            for cls in (insert_link.get_attribute("class") or "").split()
        )
    )

    try:
        driver.execute_script("arguments[0].click();", insert_link)
    except Exception:
        insert_link.click()

    return insert_link  # handed to wait_for_insert_result() for a staleness check


def wait_for_insert_result(driver, old_insert_link=None, timeout=20):
    """Waits for the page that appears after clicking Insert to actually
    finish loading before we try to click 'ADD GDN DETAIL' on it.

    Same reasoning as wait_for_query_results() / wait_for_add_gdn_page():
    this is a knockout/kendo SPA, so we wait for the old Insert <a> to go
    stale (removed/replaced in the DOM), then confirm the 'ADD GDN DETAIL'
    link itself is present as a secondary check."""
    wait = WebDriverWait(driver, timeout)

    if old_insert_link is not None:
        wait.until(EC.staleness_of(old_insert_link))

    wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//span[normalize-space(text())='ADD GDN DETAIL']/ancestor::a")
        )
    )


def click_add_gdn_detail(driver):
    """Clicks the 'ADD GDN DETAIL' link on the page shown after Insert
    succeeds. Its data-hj-test-id ('hj-link') is a generic value shared by
    many links on this app, so we locate it by its visible label text
    instead, then click the ancestor <a data-bind="click: ..."> that
    actually holds the knockout binding (same approach as click_add_gdn)."""
    wait = WebDriverWait(driver, 20)

    add_detail_link = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//span[normalize-space(text())='ADD GDN DETAIL']/ancestor::a[@data-hj-test-id='hj-link']")
        )
    )
    try:
        add_detail_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", add_detail_link)

    return add_detail_link


def click_add_all_to_gdn(driver):
    """Clicks the 'Add All to GDN' button.

    This one combines two things seen separately on other buttons: like
    the Query button, the wrapping <li> has a Knockout `disabled` binding
    that must clear before a click actually does anything; but like
    'Add GDN', its `data-hj-test-id` is bound to a dynamic observable
    (`testId`) rather than a fixed string, so we can't select on that
    attribute reliably -- we locate the <li> via its visible text instead,
    then wait for 'disabled' to clear specifically on that <li> before
    clicking the inner <a>."""
    wait = WebDriverWait(driver, 20)

    add_all_li = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//span[normalize-space(text())='Add All to GDN']/ancestor::li[1]")
        )
    )

    wait.until(
        lambda d: "disabled" not in (add_all_li.get_attribute("class") or "").split()
    )

    add_all_link = add_all_li.find_element(By.CSS_SELECTOR, "a")

    try:
        driver.execute_script("arguments[0].click();", add_all_link)
    except Exception:
        add_all_link.click()

    return add_all_link


def click_print_gdn_sku(driver):
    """Clicks the 'PRINT GDN - SKU' button.

    There are TWO buttons in the same toolbar sharing the exact text
    'PRINT GDN - SKU' -- confirmed from a screenshot that both are
    visible at once, at the 2nd and 3rd positions in the toolbar
    respectively. The desired one is the SECOND occurrence (position 3
    overall). Since both are genuinely visible, filtering by is_displayed()
    alone can't distinguish them -- we rely on DOM order matching the
    left-to-right visual order in the toolbar and pick the second visible
    match."""
    wait = WebDriverWait(driver, 20)

    def _second_visible_print_link(d):
        candidates = d.find_elements(
            By.XPATH, "//span[normalize-space(text())='PRINT GDN - SKU']/ancestor::a[1]"
        )
        visible = [link for link in candidates if link.is_displayed()]
        return visible[1] if len(visible) >= 2 else False

    print_link = wait.until(_second_visible_print_link)

    try:
        driver.execute_script("arguments[0].click();", print_link)
    except Exception:
        print_link.click()

    return print_link


def click_ok_if_present(driver, timeout=8):
    """Clicks a dialog/confirmation 'OK' button IF one appears -- this is a
    plain <button class="k-button"> (not a knockout <a> link like the other
    buttons), gated by `visible: _visible` and `enable: _enabled` bindings,
    so it may or may not show up depending on what the previous action did.

    Since its appearance is conditional, this uses a short wait and treats
    a timeout as "it just didn't appear this time" rather than an error --
    unlike every other click_* helper in this file, which assume the
    target must be there and let a timeout bubble up as a real failure."""
    short_wait = WebDriverWait(driver, timeout)

    try:
        ok_button = short_wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, "//button[contains(@class,'k-button')][.//span[normalize-space(text())='OK']]")
            )
        )
    except TimeoutException:
        return False  # no OK dialog appeared -- nothing to do

    short_wait.until(lambda d: ok_button.is_enabled())

    try:
        ok_button.click()
    except Exception:
        driver.execute_script("arguments[0].click();", ok_button)

    return True


def click_send_button(driver):
    """Clicks the 'Send' button that appears after Add All to GDN. Same
    knockout <a> pattern as Query/other toolbar buttons (href="#",
    click: click), with no unique id/data-hj-test-id -- so it's located by
    its visible "Send" label text instead, same approach used for the
    menu items on the search page."""
    wait = WebDriverWait(driver, 20)
    send_link = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//a[.//span[normalize-space(text())='Send']]")
        )
    )
    try:
        send_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", send_link)
    return send_link


def click_back_button(driver):
    """Clicks the back/previous-page button. Unlike most buttons on this
    app, this one has a stable, unique data-hj-test-id
    ('active-thread-previous-button'), so no text-matching workaround is
    needed here. Its disabled state is a CSS class toggle applied directly
    on the <a> itself (`css: { 'disabled': !isPreviousButtonEnabled() }`),
    same pattern as the Insert button, so we wait for that class to clear
    before clicking."""
    wait = WebDriverWait(driver, 20)

    back_link = wait.until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "a[data-hj-test-id='active-thread-previous-button']")
        )
    )

    wait.until(
        lambda d: "disabled" not in (back_link.get_attribute("class") or "").split()
    )

    try:
        back_link.click()
    except (ElementClickInterceptedException, ElementNotInteractableException):
        # The click was genuinely blocked (something covering it, or it
        # wasn't interactable) -- it never actually fired, so trying again
        # via JS is safe here.
        driver.execute_script("arguments[0].click();", back_link)
    except Exception:
        # Any OTHER exception here (e.g. StaleElementReferenceException)
        # usually means the click DID fire and the resulting page
        # navigation invalidated our reference to the element while
        # Selenium was still processing the command -- not that the click
        # failed. This is the actual cause of the intermittent
        # triple-click bug: falling back to a second real click here, on
        # top of the caller already clicking Back twice, occasionally
        # produced three total clicks. So we deliberately do nothing and
        # assume the click succeeded.
        pass

    return back_link


def click_forward_button(driver):
    """Clicks the forward/next-page button. Mirrors click_back_button:
    same stable data-hj-test-id ('active-thread-next-button'), same
    'disabled' class toggle applied directly on the <a>, and the same
    fix for the navigation-triggered spurious-exception double-click
    issue -- only ElementClickInterceptedException /
    ElementNotInteractableException mean the click genuinely didn't
    register; anything else (e.g. StaleElementReferenceException from the
    page navigating mid-command) is treated as a successful click."""
    wait = WebDriverWait(driver, 20)

    forward_link = wait.until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "a[data-hj-test-id='active-thread-next-button']")
        )
    )

    wait.until(
        lambda d: "disabled" not in (forward_link.get_attribute("class") or "").split()
    )

    try:
        forward_link.click()
    except (ElementClickInterceptedException, ElementNotInteractableException):
        driver.execute_script("arguments[0].click();", forward_link)
    except Exception:
        pass

    return forward_link


def click_gdn_number_link(driver, gdn_number: str):
    """Clicks the row/link for a specific GDN in a results list, matched by
    its auto-generated number (e.g. 'GDN0000010209') captured earlier via
    capture_gdn_number(). Confirmed the number's text sits inside an <a>
    tag directly, so we locate the exact-text span and click its ancestor
    <a> -- same approach as click_add_gdn / click_add_gdn_detail."""
    wait = WebDriverWait(driver, 20)

    gdn_link = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, f"//span[normalize-space(text())='{gdn_number}']/ancestor::a")
        )
    )
    try:
        gdn_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", gdn_link)

    return gdn_link


def wait_for_add_gdn_page(driver, old_add_gdn_link=None, timeout=20):
    """Waits for the detail page (that appears after clicking 'Add GDN') to
    actually finish loading before we try to re-fill Warehouse ID on it.

    Same reasoning as wait_for_query_results(): this is a knockout/kendo SPA,
    so we wait for the old 'Add GDN' link to go stale, then confirm the
    Warehouse ID field is present on the new page."""
    wait = WebDriverWait(driver, timeout)

    if old_add_gdn_link is not None:
        wait.until(EC.staleness_of(old_add_gdn_link))

    def _visible_warehouse_cell(d):
        xpath = (
            "//hj-field-cell[.//hj-label//span["
            "translate(normalize-space(text()), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
            "='warehouse id']]"
        )
        for cell in d.find_elements(By.XPATH, xpath):
            if cell.is_displayed():
                return cell
        return False

    wait.until(_visible_warehouse_cell)


def fill_warehouse_id(driver, warehouse_id: str):
    """Re-fills the Warehouse ID dropdown on the detail page shown after
    'Add GDN'. Same field structure as the first Warehouse ID field, so we
    reuse get_field_cell() / set_kendo_dropdown_value().

    Warehouse ID options on THIS page were confirmed to be code + name pairs
    (e.g. "EGDC - EFL GLOBAL FREEPORT(PVT) Ltd"), same shape as Client Code —
    unlike the bare-code options on the first Warehouse ID field. This is
    already handled by set_kendo_dropdown_value()'s code-or-"code - name"
    matching, so no extra changes are needed here, just confirm the label
    text ("Warehouse ID") still matches what's on screen for this page."""
    warehouse_cell = get_field_cell(driver, "Warehouse ID")
    warehouse_select = warehouse_cell.find_element(By.CSS_SELECTOR, "select[data-role='dropdownlist']")
    set_kendo_dropdown_value(driver, warehouse_select, warehouse_id)


def fill_client_code(driver, client_code: str):
    """Re-fills the Client Code dropdown on the detail page shown after
    'Add GDN'. Confirmed structure: same hj-dropdownlist / <select
    data-role='dropdownlist'> pattern, with <option value="CODE - Full Name">
    (e.g. "EGDC - EFL Global Freeport (Pvt) Ltd", "HIES - HIRDARAMANI
    INTERNATIONAL EXPO") — identical shape to the Client Code field on the
    first page, so set_kendo_dropdown_value()'s existing matching handles it
    with no changes. Uses the same client_code value the user typed in
    originally."""
    client_cell = get_field_cell(driver, "Client Code")
    client_select = client_cell.find_element(By.CSS_SELECTOR, "select[data-role='dropdownlist']")
    set_kendo_dropdown_value(driver, client_select, client_code)


def fill_gate_pass_number(driver, gate_pass_number: str):
    """Re-fills the Gate Pass Number field on the detail page shown after
    'Add GDN'. Confirmed structure: this field is a plain <hj-textbox>
    (knockout textInput binding on an <input class="k-textbox">), NOT a
    Kendo dropdown — same shape as the Gate Pass Number field on the first
    page, so we reuse the same get_field_cell() + clear()/send_keys()
    pattern from fill_gdn_form() rather than set_kendo_dropdown_value()."""
    gatepass_cell = get_field_cell(driver, "Gate Pass Number")
    gatepass_input = gatepass_cell.find_element(By.CSS_SELECTOR, "input.k-textbox")
    gatepass_input.clear()
    gatepass_input.send_keys(gate_pass_number)


def fill_delivery_location(driver, delivery_location: str):
    """Fills the 'Delivery To' field on the detail page shown after
    'Add GDN' (labelled "*Delivery To" on screen — the leading asterisk is
    fused into the same label span as the text itself, which is now
    handled by get_field_cell()'s asterisk-stripping match). Same plain
    <hj-textbox> structure as Gate Pass Number, so we reuse get_field_cell().

    Extra care here vs. Gate Pass Number:
    - The field has `disable: _disabled` bound to field.isReadOnly, an
      observable — it may still be flipping from disabled to enabled a
      moment after the page loads (e.g. once Client Code's selection
      finishes propagating), so we explicitly wait for it to be enabled
      before typing rather than assuming presence == interactable.
    - The field has `event:{blur: trimValueOnChange}` — a handler that
      only runs once the field loses focus. Knockout's textInput binding
      itself updates on every keystroke, but if the app has any logic
      that finalizes/validates the value on blur (or that re-populates a
      default value asynchronously after Client Code changes), typing
      without ever blurring could leave the visible text there but not
      "committed" the way the app expects. So after send_keys we
      explicitly blur (Tab) and then read the value back to confirm it
      actually stuck, retrying once if something else overwrote it.
    """
    from selenium.webdriver.common.keys import Keys

    wait = WebDriverWait(driver, 20)
    delivery_cell = get_field_cell(driver, "Delivery To")

    def _enabled_input(d):
        el = delivery_cell.find_element(By.CSS_SELECTOR, "input.k-textbox")
        return el if el.is_displayed() and el.is_enabled() else False

    delivery_input = wait.until(_enabled_input)

    def _type_and_blur():
        delivery_input.clear()
        delivery_input.send_keys(delivery_location)
        delivery_input.send_keys(Keys.TAB)  # triggers blur -> trimValueOnChange

    _type_and_blur()

    # Confirm the value actually stuck; retry once if something (e.g. an
    # async default-population from Client Code) overwrote it.
    time.sleep(0.5)
    current_value = delivery_input.get_attribute("value")
    if current_value.strip() != delivery_location.strip():
        _type_and_blur()
        time.sleep(0.5)
        current_value = delivery_input.get_attribute("value")
        if current_value.strip() != delivery_location.strip():
            raise Exception(
                f"Delivery To field shows '{current_value}' after typing "
                f"'{delivery_location}' twice — something on the page is "
                f"overwriting it (possibly an auto-populated default)."
            )


def fill_seal_number(driver, seal_number: str):
    """Fills the 'Seal No' field on the detail page shown after 'Add GDN'
    (sits directly under Delivery To). Confirmed same plain <hj-textbox>
    structure as Delivery To and Gate Pass Number — a knockout textInput
    binding on an <input class="k-textbox">, with the same
    event:{blur: trimValueOnChange} handler. So we reuse the same
    wait-for-enabled + type-blur-verify pattern used for Delivery To,
    rather than the simpler clear()/send_keys() used for Gate Pass Number,
    since we don't yet know whether this field is also subject to an
    async overwrite the way Delivery To was."""
    from selenium.webdriver.common.keys import Keys

    wait = WebDriverWait(driver, 20)
    seal_cell = get_field_cell(driver, "Seal No")

    def _enabled_input(d):
        el = seal_cell.find_element(By.CSS_SELECTOR, "input.k-textbox")
        return el if el.is_displayed() and el.is_enabled() else False

    seal_input = wait.until(_enabled_input)

    def _type_and_blur():
        seal_input.clear()
        seal_input.send_keys(seal_number)
        seal_input.send_keys(Keys.TAB)  # triggers blur -> trimValueOnChange

    _type_and_blur()

    time.sleep(0.5)
    current_value = seal_input.get_attribute("value")
    if current_value.strip() != seal_number.strip():
        _type_and_blur()
        time.sleep(0.5)
        current_value = seal_input.get_attribute("value")
        if current_value.strip() != seal_number.strip():
            raise Exception(
                f"Seal No field shows '{current_value}' after typing "
                f"'{seal_number}' twice — something on the page is "
                f"overwriting it."
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = KorberApp(root)
    root.mainloop()
