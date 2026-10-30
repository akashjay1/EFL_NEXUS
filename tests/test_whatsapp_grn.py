"""Real SQLite/image checks. Snapshot and lane doubles are labelled and test-only."""

import base64
from datetime import datetime
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

from whatsapp_grn import GRNInboxStore, GRNExtractionWorker, fill_grn_request, validate_grn_fields
from grn_ocr import header_anchors


def snapshot_double(message="test-message", count=1):
    """Minimal test double for an incoming photo snapshot, not real WhatsApp DOM."""
    return {"group_id": "name:Test group", "name": "Test group",
            "photos": [{"message_id": message, "index": i,
                        "message_time": datetime.now().strftime('%H:%M, %d/%m/%Y')} for i in range(count)]}


def image_double(color="white"):
    """Small generated image test double for persistence, not OCR validation."""
    data = io.BytesIO()
    Image.new("RGB", (400, 600), color).save(data, "PNG")
    return base64.b64encode(data.getvalue()).decode()


class LaneDouble:
    """Minimal lane test double: records form filling; it cannot create a GRN."""
    def __init__(self, busy=False):
        self.queue_running = busy
        self.queue = []
        self.grn_btn = self
        self.filled = []

    def cget(self, _):
        return "normal"

    def prefill_grn(self, **fields):
        self.filled.append(fields)

    def set_status(self, _):
        pass


class GRNStorageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = GRNInboxStore(Path(folder.name) / "inbox.sqlite3")
        self.addCleanup(self.store.close)
        self.store.set_default_warehouse("name:Test group", "EGDC")

    def document(self, message="test-message", color="white", gatepass="00734355"):
        self.store.discover(snapshot_double(message))
        source = self.store.pending_capture("name:Test group")[0]
        record = self.store.save_image(source["id"], image_double(color))
        with self.store.db:
            self.store.db.execute("UPDATE grn_documents SET state='Ready for review',gatepass=? WHERE id=?", (gatepass, record))
        return record

    def test_baseline_skips_history_until_explicit_import(self):
        self.store.discover(snapshot_double(), baseline=True)
        self.assertFalse(self.store.pending_capture("name:Test group"))
        self.store.discover(snapshot_double(), import_visible=True)
        self.assertEqual(len(self.store.pending_capture("name:Test group")), 1)

    def test_message_and_content_deduplication_survive_reopen(self):
        first = self.document()
        self.store.discover(snapshot_double())
        self.assertFalse(self.store.pending_capture("name:Test group"))
        second = self.document("second-message")
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.documents()), 1)
        with_image = self.store.document(first)
        self.assertTrue(Path(with_image["image_path"]).is_file())
        other = GRNInboxStore(self.store.path)
        try:
            self.assertEqual(other.document(first)["gatepass"], "00734355")
            self.assertEqual(other.default_warehouse("name:Test group"), "EGDC")
        finally:
            other.close()

    def test_invalid_bytes_are_not_acknowledged(self):
        self.store.discover(snapshot_double())
        source = self.store.pending_capture("name:Test group")[0]
        with self.assertRaises(ValueError):
            self.store.save_image(source["id"], "not base64")
        self.assertEqual(len(self.store.documents()), 0)
        self.assertEqual(self.store.pending_capture("name:Test group")[0]["id"], source["id"])

    def test_failed_capture_is_visible_and_retryable(self):
        self.store.discover(snapshot_double())
        source = self.store.pending_capture("name:Test group")[0]
        self.store.capture_failed(source["id"], "Photo not loaded")
        self.assertFalse(self.store.pending_capture("name:Test group"))
        self.assertEqual(self.store.capture_errors()[0]["capture_error"], "Photo not loaded")
        self.store.retry()
        self.assertEqual(len(self.store.pending_capture("name:Test group")), 1)

    def test_detection_is_listed_before_image_or_extraction(self):
        self.store.discover(snapshot_double())
        pending = self.store.pending_entries()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["message_id"], "test-message")
        self.assertFalse(self.store.documents())
        self.store.save_image(pending[0]["id"], image_double())
        self.assertFalse(self.store.pending_entries())
        self.assertEqual(len(self.store.documents()), 1)

    def test_unknown_sender_is_visible_but_cannot_be_captured_until_verified(self):
        snapshot = snapshot_double()
        snapshot['unclassifiedPhotos'] = snapshot.pop('photos')
        self.store.discover(snapshot)
        self.assertEqual(self.store.pending_entries()[0]['incoming_verified'], 0)
        self.assertFalse(self.store.pending_capture('name:Test group'))
        self.store.discover(snapshot_double())
        self.assertEqual(len(self.store.pending_capture('name:Test group')), 1)

    def test_capture_schedules_visible_photos_without_blocking_on_old_or_inflight(self):
        for message in ('old', 'first', 'second', 'third'):
            self.store.discover(snapshot_double(message))
        visible = {'first', 'second', 'third'}
        pending = self.store.pending_capture('name:Test group', limit=4, visible_ids=visible)
        self.assertEqual([r['message_id'] for r in pending], ['first', 'second', 'third'])
        self.store.capture_failed(pending[0]['id'], 'Download failed')
        remaining = self.store.pending_capture('name:Test group', limit=4,
            exclude_ids=[pending[1]['id']], visible_ids=visible)
        self.assertEqual([r['message_id'] for r in remaining], ['third'])
        self.assertFalse(self.store.pending_capture('name:Test group', visible_ids=set()))

    def test_loading_original_does_not_increase_failure_backoff(self):
        self.store.discover(snapshot_double())
        source = self.store.pending_entries()[0]
        before = time.time()
        self.store.capture_waiting(source['id'], 'Loading original')
        current = self.store.pending_entries()[0]
        self.assertEqual(current['capture_attempts'], 0)
        self.assertLess(current['next_try'] - before, 1)

    def test_review_and_retry_preserve_identifiers_and_status(self):
        record = self.document()
        self.store.save_grn_review(record, "EGDC", "000123")
        self.store.retry(record)
        reread = self.store.document(record)
        self.assertEqual(reread["gatepass"], "000123")
        self.assertEqual(reread["action"], "Reviewed")
        self.assertEqual(reread["state"], "Pending")

    def test_recapture_replaces_unreviewed_image_in_same_record(self):
        record = self.document()
        original = self.store.document(record)["image_hash"]
        self.store.refresh_photo(record)
        self.assertEqual(self.store.document(record)["state"], "Awaiting original photo")
        pending = self.store.pending_capture("name:Test group")[0]
        self.assertEqual(pending["document_id"], record)
        result = self.store.save_image(pending["id"], image_double("gray"))
        self.assertEqual(result, record)
        self.assertNotEqual(self.store.document(record)["image_hash"], original)
        self.assertEqual(self.store.document(record)["state"], "Pending")
        self.assertEqual(self.store.document(record)["gatepass"], "")

    def test_recapture_cannot_replace_saved_review(self):
        record = self.document()
        self.store.save_grn_review(record, "EGDC", "001234")
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            self.store.refresh_photo(record)
        self.assertEqual(self.store.document(record)["gatepass"], "001234")

    def test_recapture_deduplicates_existing_image_and_blocks_superseded_form(self):
        first = self.document()
        second = self.document("second", "gray")
        self.store.refresh_photo(first)
        source = self.store.pending_capture("name:Test group")[0]
        self.assertEqual(self.store.save_image(source["id"], image_double("gray")), second)
        with self.assertRaisesRegex(ValueError, "already transferred"):
            fill_grn_request(self.store, first, "EGDC", "123456", "Lane A", {"Lane A": LaneDouble()})

    def test_fill_only_selected_lane_and_block_repeat(self):
        record = self.document()
        lanes = {"Lane A": LaneDouble(), "Lane B": LaneDouble()}
        fill_grn_request(self.store, record, "EGDC", "00734355", "Lane B", lanes)
        self.assertEqual(lanes["Lane A"].filled, [])
        self.assertEqual(lanes["Lane B"].filled, [{"warehouse": "EGDC", "gatepass": "00734355"}])
        self.assertEqual(self.store.document(record)["action"], "Filled: Lane B")
        with self.assertRaisesRegex(ValueError, "already transferred"):
            fill_grn_request(self.store, record, "EGDC", "00734355", "Lane A", lanes)

    def test_missing_values_and_busy_lane_cannot_fill(self):
        record = self.document()
        lane = LaneDouble(busy=True)
        for warehouse, gatepass in (("", "123"), ("EGDC", ""), ("EGDC", "123")):
            with self.assertRaises(ValueError):
                fill_grn_request(self.store, record, warehouse, gatepass, "Lane A", {"Lane A": lane})
        self.assertFalse(lane.filled)
        self.assertEqual(self.store.document(record)["action"], "New")

    def test_duplicate_gatepass_photo_and_queue_block_transfer(self):
        first = self.document()
        second = self.document("second", "gray")
        lanes = {"Lane A": LaneDouble()}
        fill_grn_request(self.store, first, "EGDC", "00734355", "Lane A", lanes)
        with self.assertRaisesRegex(ValueError, "another photo"):
            fill_grn_request(self.store, second, "EGDC", "00734355", "Lane A", lanes)
        lanes["Lane A"].queue.append({"doc_type": "GRN", "warehouse_id": "EGDC", "gate_pass_number": "888"})
        with self.assertRaisesRegex(ValueError, "already in a GRN queue"):
            fill_grn_request(self.store, second, "EGDC", "888", "Lane A", lanes)

    def test_existing_gdn_records_are_unchanged(self):
        text = "WH ID: EGDC\nGate Pass: 123\nClient Code: TEST"
        record, _ = self.store.add(text)
        original = self.store.get(record)
        self.document()
        self.assertEqual(original, self.store.get(record))

    def test_worker_recovers_interrupted_extraction_and_keeps_review(self):
        record = self.document()
        self.store.save_grn_review(record, "EGDC", "000123")
        with self.store.db:
            self.store.db.execute("UPDATE grn_documents SET state='Extracting' WHERE id=?", (record,))
        stopping = threading.Event()
        # Minimal extraction test double: this verifies worker recovery and the
        # review write race, not OCR quality or browser compatibility.
        with patch("grn_ocr.extract_gatepass", return_value={"gatepass": "999888", "warnings": []}):
            worker = GRNExtractionWorker(self.store.path, stopping)
            worker.thread.start()
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and self.store.document(record)["state"] != "Ready for review":
                    time.sleep(.05)
                self.assertEqual(self.store.document(record)["state"], "Ready for review")
                self.assertEqual(self.store.document(record)["gatepass"], "000123")
                self.assertEqual(self.store.document(record)["action"], "Reviewed")
            finally:
                stopping.set()
                worker.thread.join(timeout=5)
            self.assertFalse(worker.thread.is_alive())


class GRNInboxRefreshTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from types import SimpleNamespace
        from whatsapp_grn_inbox import WhatsAppGRNInbox
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = GRNInboxStore(Path(directory.name) / 'inbox.sqlite3')
        self.addCleanup(self.store.close)
        self.store.set_settings(group={'id': 'name:Test group', 'name': 'Test group'})
        self.store.set_default_warehouse('name:Test group', 'EGDC')
        # Minimal controller test double: no browser is launched by these UI checks.
        controller = SimpleNamespace(store=self.store, run_id='test-run', start=lambda: None)
        self.inbox = WhatsAppGRNInbox(self.root, self.root, controller, {})
        self.addCleanup(self.inbox.frame.destroy)
        self.root.update_idletasks()

    def test_pending_detection_reaches_ui_without_waiting_for_photo_or_ocr(self):
        start = time.monotonic()
        self.store.discover(snapshot_double())
        while not self.inbox.tree.get_children() and time.monotonic() - start < 1.5:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(len(self.inbox.tree.get_children()), 1)
        key = self.inbox.tree.get_children()[0]
        self.assertTrue(key.startswith('source:'))
        self.assertEqual(self.inbox.tree.item(key, 'values')[1], 'Waiting for original photo')
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertFalse(self.store.documents())

    def test_pending_selection_transitions_to_captured_document_in_place(self):
        self.store.discover(snapshot_double())
        self.inbox.refresh()
        source = self.store.pending_entries()[0]
        self.inbox.tree.selection_set(f"source:{source['id']}")
        self.inbox._selected()
        self.assertIsNone(self.inbox.selected_id)
        self.assertFalse(self.inbox.save_review())
        record = self.store.save_image(source['id'], image_double())
        self.inbox.refresh()
        self.assertEqual(self.inbox.selected_id, record)
        self.assertEqual(self.inbox.tree.selection(), (str(record),))
        self.assertFalse(any(key.startswith('source:') for key in self.inbox.tree.get_children()))

    def test_arrivals_preserve_unsaved_values_and_selection(self):
        self.store.discover(snapshot_double())
        record = self.store.save_image(self.store.pending_entries()[0]['id'], image_double())
        self.inbox.refresh()
        self.inbox.tree.selection_set(str(record))
        self.inbox._selected()
        self.inbox.gatepass.set('000123')
        self.store.discover(snapshot_double('second-message'))
        self.inbox.refresh()
        self.assertEqual(self.inbox.gatepass.get(), '000123')
        self.assertTrue(self.inbox.dirty)
        self.assertEqual(self.inbox.tree.selection(), (str(record),))


class GRNValidationTests(unittest.TestCase):
    def test_numbers_are_not_coerced_or_restricted_to_six_digits(self):
        self.assertEqual(validate_grn_fields("EGDC", "00012345"), [])
        for value in ("73O355", "ï¼‘ï¼’ï¼“", "123\n", "", "*123*"):
            self.assertTrue(validate_grn_fields("EGDC", value))

    def test_header_requires_adjacent_label_words(self):
        # Explicit OCR word test doubles verify spatial association, not OCR accuracy.
        word = lambda text, x, y: {"text": text, "left": x, "top": y, "width": 60, "height": 20}
        self.assertEqual(len(header_anchors([word("GATE", 300, 100), word("PASS:", 370, 100)], (1000, 1500))), 1)
        self.assertEqual(header_anchors([word("GATE", 300, 100), word("PASS", 800, 600)], (1000, 1500)), [])
        self.assertEqual(header_anchors([word("DATE", 300, 100), word("734355", 370, 100)], (1000, 1500)), [])


class GRNRealFormTests(unittest.TestCase):
    def test_review_fills_real_grn_tab_without_starting_browser(self):
        import tkinter as tk
        from korber_tool import KorberApp
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        container = tk.Frame(root)
        lane = KorberApp(root, container=container, standalone=False, profile_name="lane_b")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = GRNInboxStore(Path(directory.name) / "inbox.sqlite3")
        self.addCleanup(store.close)
        store.discover(snapshot_double())
        record = store.save_image(store.pending_capture("name:Test group")[0]["id"], image_double())
        with store.db:
            store.db.execute("UPDATE grn_documents SET state='Ready for review' WHERE id=?", (record,))
        fill_grn_request(store, record, "EGDC", "000123", "Lane B", {"Lane B": lane})
        self.assertEqual(lane.grn_gatepass_entry.get(), "000123")
        self.assertEqual(lane.grn_warehouse_entry.get(), "EGDC")
        self.assertEqual(lane.notebook.index(lane.notebook.select()), 1)
        self.assertIsNone(lane.driver)
        self.assertFalse(lane.queue_running)


if __name__ == "__main__":
    unittest.main()
