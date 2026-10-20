"""Parser/storage and real Tk lane checks. No browser or network test doubles."""

from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest

from whatsapp_gdn import GDNInboxStore, parse_gdn_message, validate_fields


# Transcribed from the user's reference message.
REFERENCE_MESSAGE = """Please advise the GDN
WH ID : EGDC
Client Code : HIES
Gate pass# - 734683
Door location - C19
Seal numbers - EGF075133/004186
Note: KOREANA"""


class ParserTests(unittest.TestCase):
    def test_reference_message_maps_note_and_preserves_identifiers(self):
        parsed = parse_gdn_message(REFERENCE_MESSAGE)
        self.assertTrue(parsed.candidate)
        self.assertEqual(parsed.fields, {
            "warehouse": "EGDC", "client": "HIES", "gatepass": "734683",
            "door_location": "C19", "seal": "EGF075133/004186", "delivery_location": "KOREANA",
        })
        self.assertEqual(parsed.warnings, [])

    def test_formatting_label_case_and_leading_zeroes(self):
        text = REFERENCE_MESSAGE.replace("WH ID : EGDC", "*wh id:* EGDC").replace("734683", "000734683")
        parsed = parse_gdn_message(text.replace("\n", "\r\n"))
        self.assertEqual(parsed.fields["warehouse"], "EGDC")
        self.assertEqual(parsed.fields["gatepass"], "000734683")

    def test_missing_note_never_uses_door_or_defaults(self):
        parsed = parse_gdn_message(REFERENCE_MESSAGE.replace("Note: KOREANA", ""))
        self.assertEqual(parsed.fields["delivery_location"], "")
        self.assertEqual(parsed.fields["door_location"], "C19")
        self.assertIn("Missing Delivery Location (Note)", validate_fields(parsed.fields, {"EGDC"}))

    def test_conflicting_labels_require_visible_warning(self):
        parsed = parse_gdn_message(REFERENCE_MESSAGE + "\nNote: C19")
        self.assertEqual(parsed.fields["delivery_location"], "KOREANA")
        self.assertEqual(len(parsed.warnings), 1)

    def test_multiline_note(self):
        parsed = parse_gdn_message(REFERENCE_MESSAGE + "\nDelivery entrance C19")
        self.assertEqual(parsed.fields["delivery_location"], "KOREANA\nDelivery entrance C19")

    def test_non_request_is_not_candidate(self):
        self.assertFalse(parse_gdn_message("Thank you").candidate)
        self.assertFalse(parse_gdn_message("Note: KOREANA").candidate)

    def test_unknown_warehouse_is_rejected(self):
        fields = parse_gdn_message(REFERENCE_MESSAGE).fields
        self.assertIn("Unknown Warehouse ID: EGDC", validate_fields(fields, {"ESKD"}))

    def test_placeholder_and_control_characters_require_review(self):
        fields = parse_gdn_message(REFERENCE_MESSAGE).fields
        fields["delivery_location"] = "-"
        fields["gatepass"] += "\t"
        errors = validate_fields(fields, {"EGDC"})
        self.assertIn("Missing Delivery Location (Note)", errors)
        self.assertIn("Remove control characters from Gate Pass No.", errors)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "inbox.sqlite3"
        self.store = GDNInboxStore(self.path)
        self.addCleanup(lambda: self.store.close())

    def test_duplicate_import_survives_restart_and_source_change(self):
        first, _ = self.store.add(REFERENCE_MESSAGE, "Pasted text")
        self.store.close()
        self.store = GDNInboxStore(self.path)
        second, result = self.store.add(REFERENCE_MESSAGE, "Clipboard")
        self.assertEqual(first, second)
        self.assertIn("Duplicate", result)
        self.assertEqual(len(self.store.records()), 1)

    def test_correction_is_preserved_and_related_to_original(self):
        first, _ = self.store.add(REFERENCE_MESSAGE)
        second, _ = self.store.add(REFERENCE_MESSAGE.replace("KOREANA", "Koreana"))
        self.assertNotEqual(first, second)
        corrected = self.store.get(second)
        self.assertEqual([r["id"] for r in self.store.related(corrected["fields"], second)], [first])

    def test_review_and_action_persist_without_altering_original(self):
        record_id, _ = self.store.add(REFERENCE_MESSAGE)
        fields = self.store.get(record_id)["fields"]
        fields["delivery_location"] = "KOREANA\nC19"
        self.store.save_review(record_id, fields, "Queued: Lane B")
        saved = self.store.get(record_id)
        self.assertEqual(saved["raw_text"], REFERENCE_MESSAGE)
        self.assertEqual(saved["fields"], fields)
        self.assertEqual(saved["action"], "Queued: Lane B")

    def test_unrelated_message_is_not_stored(self):
        self.assertIsNone(self.store.add("Thank you")[0])
        self.assertEqual(self.store.records(), [])


class InboxLaneTests(unittest.TestCase):
    def setUp(self):
        from korber_tool import KorberApp
        from whatsapp_inbox import WhatsAppGDNInbox
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self._destroy_root)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lanes = {}
        for key, name in (("lane_a", "Lane A"), ("lane_b", "Lane B")):
            self.lanes[name] = KorberApp(self.root, container=ttk.Frame(self.root), standalone=False, profile_name=key)
        store = GDNInboxStore(Path(directory.name) / "inbox.sqlite3")
        from whatsapp_controller import WhatsAppController
        self.controller = WhatsAppController(self.root, store.path, autostart=False)
        self.addCleanup(self.controller.shutdown)
        self.inbox = WhatsAppGDNInbox(self.root, self.lanes, store, controller=self.controller)
        self.addCleanup(lambda: self.inbox.window.destroy() if not self.inbox.closed else None)
        self.root.update_idletasks()

    def _destroy_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def test_fill_lane_b_without_creating_or_queuing(self):
        self.inbox.import_message(REFERENCE_MESSAGE)
        self.inbox.lane_choice.set("Lane B")
        self.assertTrue(self.inbox.apply_request(False))
        lane = self.lanes["Lane B"]
        self.assertEqual(lane.gatepass_entry.get(), "734683")
        self.assertEqual(lane.delivery_entry.get(), "KOREANA")
        self.assertEqual(lane.seal_entry.get(), "EGF075133/004186")
        self.assertEqual(lane.queue, [])
        self.assertIsNone(lane.driver)
        self.assertEqual(self.lanes["Lane A"].gatepass_entry.get(), "")

    def test_queue_blocks_duplicate_across_lanes_and_corrections(self):
        self.inbox.import_message(REFERENCE_MESSAGE)
        self.assertTrue(self.inbox.apply_request(True))
        self.assertFalse(self.inbox.apply_request(True))
        self.inbox.import_message(REFERENCE_MESSAGE.replace("KOREANA", "Koreana"))
        self.inbox.lane_choice.set("Lane B")
        self.assertFalse(self.inbox.apply_request(True))
        self.assertEqual(len(self.lanes["Lane A"].queue), 1)
        self.assertEqual(self.lanes["Lane B"].queue, [])
        self.assertFalse(self.lanes["Lane A"].queue_running)

    def test_incomplete_request_does_not_modify_lane(self):
        self.inbox.import_message(REFERENCE_MESSAGE.replace("Note: KOREANA", ""))
        self.assertFalse(self.inbox.apply_request(False))
        self.assertEqual(self.lanes["Lane A"].warehouse_entry.get(), "")

    def test_multiline_note_is_retained_but_transferred_on_one_line(self):
        record_id = self.inbox.import_message(REFERENCE_MESSAGE + "\nDoor C19")
        self.assertTrue(self.inbox.apply_request(False))
        self.assertEqual(self.lanes["Lane A"].delivery_entry.get(), "KOREANA Door C19")
        self.assertEqual(self.inbox.store.get(record_id)["fields"]["delivery_location"], "KOREANA\nDoor C19")

    def test_background_import_preserves_unsaved_edit(self):
        self.inbox.import_message(REFERENCE_MESSAGE)
        editor = self.inbox.editors["client"]
        editor.delete(0, "end")
        editor.insert(0, "HIES reviewed")
        self.inbox.import_message(REFERENCE_MESSAGE.replace("734683", "734684"), select=False)
        self.root.update()
        self.assertEqual(editor.get(), "HIES reviewed")

    def test_repeated_partial_import_preserves_reviewed_fields(self):
        partial = REFERENCE_MESSAGE.replace("Note: KOREANA", "")
        self.inbox.import_message(partial)
        self.inbox.editors["delivery_location"].insert("1.0", "KOREANA")
        self.inbox.save_review()
        self.inbox.import_message(partial)
        self.assertEqual(self.inbox.editors["delivery_location"].get("1.0", "end-1c"), "KOREANA")

    def test_busy_lane_does_not_receive_inbox_values(self):
        self.inbox.import_message(REFERENCE_MESSAGE)
        self.lanes["Lane A"].gdn_btn.configure(state="disabled")
        self.assertFalse(self.inbox.apply_request(False))
        self.assertEqual(self.lanes["Lane A"].gatepass_entry.get(), "")

    def test_destroy_closes_view_store_but_keeps_app_controller(self):
        self.inbox.window.destroy()
        self.assertTrue(self.inbox.closed)
        self.assertFalse(self.controller.closed)
        self.assertEqual(self.controller.store.counts(), (0, 0))
if __name__ == "__main__":
    unittest.main()
