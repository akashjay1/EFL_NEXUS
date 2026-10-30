"""Real SQLite/Tk checks; browser snapshots below are explicit test doubles."""

from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from whatsapp_gdn import GDNInboxStore, received_label
from whatsapp_grn import GRNInboxStore, fill_grn_request
from whatsapp_controller import WhatsAppController
from whatsapp_monitor import CaptureEngine
from whatsapp_inbox import WhatsAppGDNInbox
from whatsapp_grn_inbox import WhatsAppGRNInbox
from test_whatsapp_grn import image_double
from test_whatsapp_monitoring import REFERENCE


def browser_double(messages=(), photos=(), replies=()):
    """Minimal browser snapshot test double; no production identifiers."""
    return {"group_id": "test-group", "name": "Test group", "identity_method": "exact_name", "messages": list(messages),
            "photos": list(photos), "replies": list(replies)}


class InboxFeatureStorageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "inbox.sqlite3"
        self.store = GRNInboxStore(self.path)
        self.addCleanup(self.store.close)

    def request(self, message="original", text=REFERENCE):
        return self.store.add(text, "Test group", message, group_id="test-group",
                              message_time="09:14, 21/10/2026")[0]

    def photo(self, message="photo"):
        self.store.discover(browser_double(photos=[{"message_id": message, "index": 0,
                                                   "message_time": "09:15, 21/10/2026"}]))
        source = self.store.pending_entries()[0]
        return source["id"], self.store.save_image(source["id"], image_double())

    def done(self, target, text="DONE", group="test-group"):
        snapshot = browser_double(replies=[{"id": "reply-" + target, "text": text, "reply_to": target}])
        snapshot["group_id"] = group
        self.store.observe_messages(snapshot)

    def test_message_time_and_capture_time_are_distinct(self):
        record = self.store.get(self.request())
        self.assertEqual(received_label(record), "09:14, 21/10/2026")
        self.assertIn("+00:00", record["received_at"])
        self.assertTrue(received_label({"received_at": record["received_at"]}).startswith("Captured "))
        self.assertEqual(received_label({}), "Time unavailable")
        source, doc = self.photo()
        self.assertEqual(received_label(self.store.document(doc)), "09:15, 21/10/2026")

    def test_clear_each_inbox_independently_and_keep_history(self):
        request = self.request()
        source, doc = self.photo()
        GDNInboxStore.clear_list(self.store)
        self.assertEqual(self.store.records(), [])
        self.assertEqual(len(self.store.documents()), 1)
        self.assertIsNone(self.request())
        self.assertEqual(self.store.counts(), (0, 0))
        self.assertEqual(self.store.get(request)["hidden_reason"], "cleared")
        self.store.clear_list()
        self.assertEqual(self.store.documents(), [])
        self.assertTrue(Path(self.store.document(doc)["image_path"]).exists())
        self.assertEqual(self.store.grn_new_count(), 0)
        self.assertIsNotNone(self.request("new", REFERENCE.replace("734683", "000123")))
        other = GRNInboxStore(self.path)
        try:
            self.assertEqual(other.document(doc)["hidden_reason"], "cleared")
            self.assertEqual(len(other.records()), 1)
        finally:
            other.close()

    def test_clear_pending_photo_blocks_late_callback_and_rescan(self):
        snapshot = browser_double(photos=[{"message_id": "pending", "index": 0}])
        self.store.discover(snapshot)
        source = self.store.pending_entries()[0]
        self.store.clear_list()
        with self.assertRaisesRegex(ValueError, "cleared"):
            self.store.save_image(source["id"], image_double())
        self.store.discover(snapshot, import_visible=True)
        self.store.retry()
        self.assertEqual(self.store.pending_entries(), [])
        self.assertEqual(self.store.pending_capture("test-group"), [])
        self.assertEqual(self.store.documents(), [])

    def test_done_before_import_and_late_reply_are_sticky(self):
        self.done("future", " done ")
        self.assertIsNone(self.request("future"))
        request = self.request("later", REFERENCE.replace("734683", "000123"))
        self.done("later")
        self.assertEqual(self.store.records(), [])
        self.assertEqual(self.store.get(request)["hidden_reason"], "done")
        self.assertEqual(self.store.known_done_replies()["test-group"]["reply-later"], "later")
        self.assertIsNone(self.request("resent", REFERENCE.replace("734683", "000123")))

    def test_done_uses_identity_not_text_and_rejects_other_phrases(self):
        request = self.request()
        for text in ("NOT DONE", "DONE ✅", "GDN done"):
            self.done("original", text)
        self.done("different-original")
        self.done("original", group="another-test-group")
        self.assertEqual(self.store.get(request)["hidden_reason"], "")
        self.done("original")
        self.assertEqual(self.store.get(request)["hidden_reason"], "done")

    def test_done_on_duplicate_source_hides_deduplicated_photo(self):
        source, doc = self.photo()
        self.photo("second-photo-message")
        self.assertEqual(len(self.store.documents()), 1)
        self.done("second-photo-message")
        self.assertEqual(self.store.documents(), [])
        self.assertEqual(self.store.document(doc)["hidden_reason"], "done")
        with self.assertRaisesRegex(ValueError, "cleared or marked DONE"):
            fill_grn_request(self.store, doc, "EGDC", "000123", "Lane A", {})

    def test_done_hides_all_captured_edits_of_same_original_message(self):
        first = self.request("edited-original")
        second = self.request("edited-original", REFERENCE.replace("KOREANA", "Updated location"))
        self.assertNotEqual(first, second)
        self.done("edited-original")
        self.assertEqual(self.store.get(first)["hidden_reason"], "done")
        self.assertEqual(self.store.get(second)["hidden_reason"], "done")
        self.assertEqual(self.store.records(), [])

    def test_done_before_photo_discovery_skips_download(self):
        self.done("not-yet-captured")
        self.store.discover(browser_double(photos=[{"message_id": "not-yet-captured", "index": 0}]), import_visible=True)
        self.assertEqual(self.store.pending_entries(), [])
        self.assertEqual(self.store.pending_capture("test-group"), [])

    def test_completed_ocr_cannot_restore_cleared_document(self):
        source, doc = self.photo()
        from whatsapp_grn import GRNExtractionWorker
        from grn_ocr import extract_gatepass
        started, release, stopping = threading.Event(), threading.Event(), threading.Event()

        def delayed_real_ocr(*args):
            """Synchronization test double wrapping the real OCR implementation."""
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test failed to release OCR")
            return extract_gatepass(*args)

        worker = GRNExtractionWorker(self.path, stopping)
        with patch("grn_ocr.extract_gatepass", side_effect=delayed_real_ocr):
            worker.thread.start()
            try:
                self.assertTrue(started.wait(5))
                self.store.clear_list()
                release.set()
                deadline = time.monotonic() + 12
                while self.store.setting("grn_ocr_status") != "Local OCR worker ready" and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertEqual(self.store.setting("grn_ocr_status"), "Local OCR worker ready")
            finally:
                release.set()
                stopping.set()
                worker.thread.join(5)
        self.store.retry(doc)
        self.assertEqual(self.store.document(doc)["state"], "Extracting")
        with self.assertRaises(ValueError):
            self.store.save_grn_review(doc, "EGDC", "000123")

    def test_hidden_gdn_keeps_queue_duplicate_protection(self):
        request = self.request()
        fields = self.store.get(request)["fields"]
        self.store.save_review(request, fields, "Queued: Lane A")
        GDNInboxStore.clear_list(self.store)
        self.assertEqual(self.store.related(fields)[0]["action"], "Queued: Lane A")
        with self.assertRaises(ValueError):
            self.store.save_review(request, fields)

    def test_legacy_time_is_backfilled_only_from_observed_original(self):
        request = self.store.add(REFERENCE, "Test group", "legacy")[0]
        captured = self.store.get(request)["received_at"]
        snapshot = browser_double(messages=[{"id": "legacy", "text": REFERENCE, "message_time": "10:31, 21/10/2026"}])
        self.store.observe_messages(snapshot)
        self.assertEqual(self.store.get(request)["message_time"], "10:31, 21/10/2026")
        self.assertEqual(self.store.get(request)["received_at"], captured)
        self.done("legacy")
        self.assertEqual(self.store.get(request)["hidden_reason"], "done")

    def test_unresolved_reply_leaves_request_visible_with_notice(self):
        self.request()
        self.store.observe_messages({**browser_double(), "unresolved_done": ["unknown-reply"]})
        self.assertEqual(len(self.store.records()), 1)
        self.assertIn("could not be linked", self.store.setting("done_reply_notice"))

    def test_capture_waits_for_reply_identity_before_importing(self):
        engine = CaptureEngine(self.store, "test-run")
        engine.select(browser_double())
        snapshot = browser_double(messages=[{"id": "original", "text": REFERENCE}],
            replies=[{"id": "reply", "text": "DONE", "reply_to": None}])
        engine.accept({**snapshot, "reply_scan_pending": True, "unresolved_done": ["reply"]})
        self.assertEqual(self.store.counts(), (0, 0))
        self.assertIsNone(self.store.setting("checkpoint"))
        snapshot["replies"][0]["reply_to"] = "original"
        engine.accept(snapshot)
        self.assertEqual(self.store.counts(), (0, 0))
        self.assertEqual(self.store.records(include_hidden=True)[0]["hidden_reason"], "done")

    def test_additive_migration_preserves_legacy_record_and_is_repeatable(self):
        request = self.request()
        legacy = self.path.with_name("legacy.sqlite3")
        with sqlite3.connect(legacy) as old:
            self.store.db.backup(old)
            old.execute("DROP TABLE whatsapp_messages")
            old.execute("DROP TABLE gdn_message_requests")
            for table, names in (("requests", ("message_time", "hidden_reason")),
                                 ("grn_documents", ("message_time", "hidden_reason")),
                                 ("grn_sources", ("message_time", "captured_at", "hidden_reason"))):
                for name in names:
                    old.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
        old.close()
        for _ in range(2):
            migrated = GRNInboxStore(legacy)
            try:
                self.assertEqual(migrated.get(request)["raw_text"], REFERENCE)
                self.assertEqual(migrated.get(request)["message_time"], "")
                self.assertEqual(migrated.get(request)["hidden_reason"], "")
            finally:
                migrated.close()


class InboxFeatureUITests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "inbox.sqlite3"
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.controller = WhatsAppController(self.root, self.path, autostart=False)
        self.addCleanup(self.controller.shutdown)
        self.gdn = WhatsAppGDNInbox(self.root, {}, GDNInboxStore(self.path), controller=self.controller)
        self.grn = WhatsAppGRNInbox(self.root, ttk.Frame(self.root), self.controller, {})

    def test_received_columns_clear_buttons_and_scan_button(self):
        self.assertIn("received", self.gdn.tree["columns"])
        self.assertIn("received", self.grn.tree["columns"])
        def buttons(widget):
            return [w.cget("text") for w in widget.winfo_children() if isinstance(w, ttk.Button)] + [
                text for w in widget.winfo_children() for text in buttons(w)]
        labels = buttons(self.root)
        self.assertEqual(labels.count("Clear List"), 2)
        self.assertIn("Scan GRN", labels)
        self.assertIn("Retry Extraction", labels)

    def test_clearing_resets_editors_and_preserves_pause(self):
        self.gdn.import_message(REFERENCE)
        self.controller.store.set_settings(enabled=False)
        self.gdn.clear_list()
        self.assertIsNone(self.gdn.selected_id)
        self.assertEqual(self.gdn.editors["gatepass"].get(), "")
        self.assertEqual(self.gdn.tree.get_children(), ())
        self.grn.gatepass.set("000123")
        self.grn.confirmed.set(True)
        self.grn.clear_list()
        self.assertEqual(self.grn.gatepass.get(), "")
        self.assertFalse(self.grn.confirmed.get())
        self.assertFalse(self.controller.store.setting("enabled"))

    def test_scan_enqueues_visible_photo_import_without_resuming(self):
        self.controller.store.set_settings(group={"id": "test-group", "name": "Test group"}, enabled=False)
        self.grn.store.set_default_warehouse("test-group", "EGDC")
        self.controller.run_id = "test-run"
        # Process-launch test double: this unit check does not open WhatsApp.
        with patch.object(self.controller, "start") as start:
            self.grn.import_visible()
            start.assert_called_once()
        self.assertEqual(self.controller.store.take_commands("test-run"), [("import_photos", {})])
        self.assertFalse(self.controller.store.setting("enabled"))

    def test_late_done_clears_selected_review_panels(self):
        self.gdn.import_message(REFERENCE)
        self.gdn.store.observe_messages(browser_double(messages=[{"id": "original", "text": REFERENCE}],
            replies=[{"id": "reply", "text": "DONE", "reply_to": "original"}]))
        self.gdn.refresh()
        self.assertIsNone(self.gdn.selected_id)
        self.assertFalse(self.gdn.apply_request(False))
        self.grn.store.discover(browser_double(photos=[{"message_id": "photo", "index": 0}]))
        self.grn.refresh()
        source = self.grn.store.pending_entries()[0]
        self.grn.tree.selection_set(f"source:{source['id']}")
        self.grn._selected()
        self.grn.store.observe_messages(browser_double(replies=[{"id": "photo-reply", "text": "DONE", "reply_to": "photo"}]))
        self.grn.refresh()
        self.assertIsNone(self.grn.selected_source_id)
        self.assertEqual(self.grn.gatepass.get(), "")


if __name__ == "__main__":
    unittest.main()
