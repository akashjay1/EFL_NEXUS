"""Real SQLite/Tk lifecycle checks and explicitly labelled snapshot test doubles.

Snapshots exercise the capture state machine only. They do not establish that
WhatsApp's live DOM is compatible; that requires the separate live acceptance.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import subprocess
import sys
import tkinter as tk
import unittest

from whatsapp_controller import WhatsAppController, helper_command
from whatsapp_gdn import GDNInboxStore
from whatsapp_monitor import CaptureEngine


REFERENCE = """WH ID: EGDC
Client Code: HIES
Gate pass# - 734683
Door location - C19
Seal numbers - EGF075133/004186
Note: KOREANA"""


def snapshot_double(*requests):
    """Minimal browser snapshot test double, with no real group identifiers."""
    return {"group_id": "test-group", "name": "Test group", "identity_method": "exact_name",
            "messages": [{"id": message_id, "text": text} for message_id, text in requests]}


class MonitorStorageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "inbox.sqlite3"
        self.store = GDNInboxStore(self.path)
        self.addCleanup(self.store.close)

    def test_concurrent_identical_import_is_atomic(self):
        barrier = threading.Barrier(2)

        def insert():
            store = GDNInboxStore(self.path)
            try:
                barrier.wait(timeout=5)
                return store.add(REFERENCE)[0]
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(insert) for _ in range(2)]
            ids = [future.result(timeout=10) for future in futures]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.store.counts(), (1, 1))

    def test_existing_requests_and_reviews_survive_monitor_tables(self):
        record_id, _ = self.store.add(REFERENCE)
        original = self.store.get(record_id)
        self.store.save_review(record_id, original["fields"], "Reviewed")
        other = GDNInboxStore(self.path)
        try:
            self.assertEqual(other.get(record_id)["raw_text"], REFERENCE)
            self.assertEqual(other.get(record_id)["action"], "Reviewed")
            self.assertEqual(other.db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        finally:
            other.close()

    def test_commands_are_consumed_only_by_their_helper(self):
        self.store.command("old-run", "shutdown")
        self.store.command("current-run", "select", import_visible=True)
        self.assertEqual(self.store.take_commands("current-run"), [("select", {"import_visible": True})])
        self.assertEqual(self.store.take_commands("current-run"), [])
        self.assertEqual(self.store.take_commands("old-run"), [("shutdown", {})])

    def test_pause_survives_connection_restart(self):
        engine = CaptureEngine(self.store, "test-run")
        engine.select(snapshot_double(("one", REFERENCE)))
        engine.pause()
        other = GDNInboxStore(self.path)
        try:
            self.assertFalse(other.setting("enabled"))
            self.assertEqual(other.setting("group")["id"], "test-group")
        finally:
            other.close()

    def test_capture_after_baseline_and_reconnect_is_durable(self):
        engine = CaptureEngine(self.store, "first-run")
        first = snapshot_double(("one", REFERENCE))
        engine.select(first)
        self.assertEqual(self.store.counts(), (0, 0))
        new_text = REFERENCE.replace("734683", "734684")
        subsequent = snapshot_double(("one", REFERENCE), ("two", new_text))
        engine.accept(subsequent)
        self.assertEqual(self.store.counts(), (1, 1))
        restarted = CaptureEngine(self.store, "second-run")
        restarted.accept(subsequent)
        self.assertEqual(self.store.counts(), (1, 1))
        self.assertFalse(self.store.setting("capture_gap", False))

    def test_missing_checkpoint_flags_gap_and_imports_visible_requests(self):
        engine = CaptureEngine(self.store, "first-run")
        engine.select(snapshot_double(("one", REFERENCE)))
        restarted = CaptureEngine(self.store, "second-run")
        restarted.accept(snapshot_double(("two", REFERENCE.replace("734683", "734684"))))
        self.assertTrue(self.store.setting("capture_gap"))
        self.assertEqual(self.store.counts(), (1, 1))

    def test_storage_failure_does_not_acknowledge_message(self):
        engine = CaptureEngine(self.store, "test-run")
        engine.select(snapshot_double(("one", REFERENCE)))
        text = REFERENCE.replace("734683", "734684")
        next_snapshot = snapshot_double(("one", REFERENCE), ("two", text))
        self.store.db.execute("PRAGMA query_only=ON")
        with self.assertRaises(sqlite3.OperationalError):
            engine.accept(next_snapshot)
        self.store.db.execute("PRAGMA query_only=OFF")
        engine.accept(next_snapshot)
        self.assertEqual(self.store.counts(), (1, 1))
        self.assertEqual(self.store.setting("checkpoint")["message_id"], "two")

    def test_wrong_group_never_captures(self):
        engine = CaptureEngine(self.store, "test-run")
        engine.select(snapshot_double(("one", REFERENCE)))
        wrong = snapshot_double(("two", REFERENCE))
        wrong["group_id"] = "another-test-group"
        with self.assertRaises(ValueError):
            engine.accept(wrong)
        self.assertEqual(self.store.counts(), (0, 0))

    def test_group_change_requires_explicit_pause(self):
        engine = CaptureEngine(self.store, "test-run")
        data = snapshot_double(("one", REFERENCE))
        engine.select(data)
        with self.assertRaises(ValueError):
            engine.select(data)
        engine.pause()
        engine.select(data)
        self.assertTrue(self.store.setting("enabled"))

    def test_checked_unclassified_text_does_not_reopen_same_gap_forever(self):
        engine = CaptureEngine(self.store, "test-run")
        initial = snapshot_double(("one", REFERENCE))
        engine.select(initial)
        current = snapshot_double(("one", REFERENCE))
        current["unclassified"] = [{"id": "uncertain", "text": REFERENCE.replace("734683", "734684")}]
        engine.accept(current)
        self.assertTrue(self.store.setting("capture_gap"))
        self.store.set_settings(capture_gap=False)  # User acknowledges the observed gap.
        engine.accept(current)
        self.assertFalse(self.store.setting("capture_gap"))
        current["unclassified"].append({"id": "another", "text": REFERENCE.replace("734683", "734685")})
        engine.accept(current)
        self.assertTrue(self.store.setting("capture_gap"))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.controller = WhatsAppController(self.root, Path(folder.name) / "inbox.sqlite3", autostart=False)
        self.addCleanup(self.controller.shutdown)

    def test_visibility_and_pause_do_not_destroy_controller(self):
        self.controller.set_visible(False)
        self.controller.pause()
        self.assertFalse(self.controller.closed)
        self.assertFalse(self.controller.store.setting("enabled"))

    def test_three_retry_delays_then_actionable_failure(self):
        self.controller.wanted = True
        for expected, delay in enumerate((2, 5, 15), 1):
            before = time.monotonic()
            self.controller._failed("Test helper failure.")
            self.assertEqual(self.controller.retry_index, expected)
            self.assertIsNotNone(self.controller.restart_at)
            self.assertAlmostEqual(self.controller.restart_at - before, delay, delta=.2)
        self.controller._failed("Test helper failure.")
        self.assertEqual(self.controller.state, "Failed")
        self.assertIsNone(self.controller.restart_at)
        self.assertIn("Reconnect", self.controller.detail)

    def test_shutdown_does_not_erase_monitoring_preference(self):
        self.controller.store.set_settings(enabled=True, group={"id": "test-group", "name": "Test group"})
        path = self.controller.store.path
        self.controller.shutdown()
        store = GDNInboxStore(path)
        try:
            self.assertTrue(store.setting("enabled"))
        finally:
            store.close()

    def test_source_helper_command_targets_existing_module(self):
        command = helper_command(self.controller.store.path, "test-run", 123)
        self.assertTrue(Path(command[1]).is_file())
        self.assertIn("--whatsapp-browser", command)

    def test_stale_heartbeat_terminates_only_the_owned_helper_and_retries(self):
        # Explicit process test double: a sleeping Python child, not a browser.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        self.root.after_cancel(self.controller.after_id)
        self.controller.after_id = None
        self.controller.process = child
        self.controller.wanted = True
        self.controller.run_id = "test-stale-run"
        self.controller.store.report("test-stale-run", "Monitoring")
        with self.controller.store.db:
            self.controller.store.db.execute("UPDATE monitor_runtime SET heartbeat=heartbeat-20")
        self.controller._tick()
        self.assertIsNotNone(child.poll())
        self.assertEqual(self.controller.state, "Reconnecting")
        self.assertEqual(self.controller.retry_index, 1)

    def test_main_app_navigation_hides_view_without_stopping_controller(self):
        from main_app import MainApp
        from whatsapp_page import WhatsAppPage
        # Minimal application test double with real Tk frames, controller, and
        # page. No portal, credentials, or production app startup is involved.
        app = MainApp.__new__(MainApp)
        app.root = self.root
        app.pages = {key: tk.Frame(self.root) for key in ("dashboard", "whatsapp")}
        for frame in app.pages.values():
            frame.grid(row=0, column=0, sticky="nsew")
        app.nav_buttons = {}
        app.tool5_hwnd = None
        app.tool1_ready = True
        app.tool1_error = None
        for number in range(2, 7):
            setattr(app, f"tool{number}_app", None)
            setattr(app, f"tool{number}_error", None)
        app.tool5_ready = False
        app.whatsapp_error = None
        app.whatsapp_page = WhatsAppPage(self.root, app.pages["whatsapp"], self.controller)
        self.controller.wanted = True
        app.show_page("whatsapp")
        self.assertTrue(app.whatsapp_page.visible)
        app.whatsapp_page.show_inbox()
        self.assertFalse(self.controller.visible)
        app.show_page("dashboard")
        self.assertFalse(app.whatsapp_page.visible)
        self.assertTrue(self.controller.wanted)
        self.assertFalse(self.controller.closed)
        self.root.update_idletasks()


if __name__ == "__main__":
    unittest.main()
