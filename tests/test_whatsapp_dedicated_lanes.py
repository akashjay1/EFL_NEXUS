"""Real Tk/SQLite lane isolation checks; browser launch doubles stay in tests."""

from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from main_app import MainApp
from whatsapp_controller import WhatsAppController
from whatsapp_gdn import form_fields, parse_gdn_message
from whatsapp_inbox import open_inbox
from whatsapp_page import WHATSAPP_LANES
from test_whatsapp_gdn import REFERENCE_MESSAGE
from test_whatsapp_grn import image_double, snapshot_double


class DedicatedWhatsAppLaneTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.controller = WhatsAppController(self.root, Path(folder.name) / 'inbox.sqlite3', autostart=False)
        self.addCleanup(self.controller.shutdown)
        self.root._whatsapp_controller = self.controller
        # Bare main-shell test harness: real pages/lanes without production
        # startup, credentials, network warmup, or external browser processes.
        self.app = MainApp.__new__(MainApp)
        self.app.root = self.root
        self.app.pages = {name: tk.Frame(self.root) for name in ('tool1', 'whatsapp')}
        self.app.tool1_lanes = {'a': None, 'b': None}
        self.app.tool1_ready = False
        self.app.tool1_error = None
        self.app.whatsapp_controller = self.controller
        self.app.whatsapp_page = None
        self.app.whatsapp_error = None
        self.app.active_page = 'whatsapp'

    def destroy_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def build_both(self, whatsapp_first=False):
        if whatsapp_first:
            self.app._ensure_whatsapp()
        self.app._ensure_tool1()
        self.app._ensure_whatsapp()
        self.assertIsNone(self.app.tool1_error)
        self.assertIsNone(self.app.whatsapp_error)
        return self.app.whatsapp_page

    def ready_photo(self, page):
        page.grn_inbox.store.discover(snapshot_double())
        source = page.grn_inbox.store.pending_entries()[0]
        record = page.grn_inbox.store.save_image(source['id'], image_double())
        with page.grn_inbox.store.db:
            page.grn_inbox.store.db.execute("UPDATE grn_documents SET state='Ready for review',gatepass='000123' WHERE id=?", (record,))
        page.grn_inbox.refresh()
        page.grn_inbox.tree.selection_set(str(record))
        page.grn_inbox._selected()
        page.grn_inbox.warehouse.set('EGDC')
        page.grn_inbox.confirmed.set(True)

    def test_whatsapp_opening_creates_only_its_two_lanes(self):
        lanes = self.app._whatsapp_lanes()
        self.assertEqual(tuple(lanes), ('WhatsApp Lane 1', 'WhatsApp Lane 2'))
        self.assertFalse(self.app.tool1_ready)
        self.assertEqual(self.app.tool1_lanes, {'a': None, 'b': None})
        self.assertIsNone(self.controller.process)
        page = self.app.whatsapp_page
        self.assertEqual(tuple(page.inbox.lane_choice['values']), tuple(lanes))
        self.assertEqual(tuple(page.grn_inbox.lane['values']), tuple(lanes))
        self.assertEqual(page.inbox.lane_choice.get(), 'WhatsApp Lane 1')
        self.assertEqual(page.grn_inbox.lane.get(), 'WhatsApp Lane 1')

    def test_four_lanes_have_independent_state_and_browser_profiles(self):
        page = self.build_both()
        all_lanes = [*self.app.tool1_lanes.values(), *page.lanes.values()]
        self.assertEqual({lane.profile_name for lane in all_lanes},
                         {'lane_a', 'lane_b', 'whatsapp_lane_1', 'whatsapp_lane_2'})
        self.assertEqual(len({id(lane.queue) for lane in all_lanes}), 4)
        self.assertTrue(all(lane.driver is None for lane in all_lanes))
        self.assertEqual([self.root._whatsapp_gdn_lanes[label] for label, _ in WHATSAPP_LANES], list(page.lanes.values()))
        self.assertEqual(len(page.notebook.tabs()), 5)

    def test_manual_lanes_created_later_cannot_replace_inbox_destinations(self):
        page = self.build_both(whatsapp_first=True)
        self.assertIs(page.inbox.lanes, page.lanes)
        self.assertIs(page.grn_inbox.lanes, page.lanes)
        self.assertEqual(tuple(page.inbox.lane_choice['values']), ('WhatsApp Lane 1', 'WhatsApp Lane 2'))
        self.assertNotIn(self.app.tool1_lanes['a'], page.lanes.values())
        self.assertNotIn(self.app.tool1_lanes['b'], page.lanes.values())

    def test_whatsapp_dispatch_leaves_busy_manual_lanes_untouched(self):
        page = self.build_both()
        manual = self.app.tool1_lanes['a']
        manual.prefill_gdn(warehouse='EGDC', client='HIES', gatepass='999001', delivery_location='Test delivery', seal='TEST')
        manual.add_to_queue('GDN')
        manual.prefill_gdn(warehouse='EGDC', client='HIES', gatepass='999001', delivery_location='Test delivery', seal='TEST')
        manual.gdn_btn.configure(state='disabled')
        original_queue = list(manual.queue)
        page.inbox.import_message(REFERENCE_MESSAGE)
        page.inbox.lane_choice.set('WhatsApp Lane 2')
        target = page.lanes['WhatsApp Lane 2']
        with patch.object(target, 'run_flow') as launch:  # Browser-launch test double.
            self.assertTrue(page.inbox.apply_request(False, start_run=True))
            self.assertEqual(launch.call_args.args, ('GDN',))
            self.assertTrue(callable(launch.call_args.kwargs['on_complete']))
        self.assertEqual(target.gatepass_entry.get(), '734683')
        self.assertEqual(manual.gatepass_entry.get(), '999001')
        self.assertEqual(manual.queue, original_queue)
        self.assertEqual(self.app.tool1_lanes['b'].gatepass_entry.get(), '')

    def test_grn_dispatch_uses_only_dedicated_lane(self):
        page = self.build_both()
        self.ready_photo(page)
        page.grn_inbox.lane.set('WhatsApp Lane 2')
        target = page.lanes['WhatsApp Lane 2']
        with patch.object(target, 'run_flow') as launch:  # Browser-launch test double.
            self.assertTrue(page.grn_inbox.fill_form(start_run=True))
            self.assertEqual(launch.call_args.args, ('GRN',))
            self.assertTrue(callable(launch.call_args.kwargs['on_complete']))
        self.assertEqual(target.grn_gatepass_entry.get(), '000123')
        self.assertTrue(all(lane.grn_gatepass_entry.get() == '' for lane in self.app.tool1_lanes.values()))

    def test_duplicate_guards_still_see_manual_lane_queues(self):
        page = self.build_both()
        manual = self.app.tool1_lanes['a']
        manual.prefill_gdn(**form_fields(parse_gdn_message(REFERENCE_MESSAGE).fields))
        manual.add_to_queue('GDN')
        page.inbox.import_message(REFERENCE_MESSAGE)
        target = page.lanes['WhatsApp Lane 1']
        with patch.object(target, 'run_flow') as launch:  # Browser-launch test double.
            self.assertFalse(page.inbox.apply_request(False, start_run=True))
            launch.assert_not_called()
        manual.prefill_grn(warehouse='EGDC', gatepass='000123')
        manual.add_to_queue('GRN')
        self.ready_photo(page)
        with patch.object(target, 'run_flow') as launch:  # Browser-launch test double.
            self.assertFalse(page.grn_inbox.fill_form(start_run=True))
            launch.assert_not_called()

    def test_reopening_preserves_dedicated_lane_instances_and_queues(self):
        page = self.build_both()
        target = page.lanes['WhatsApp Lane 1']
        target.prefill_gdn(**form_fields(parse_gdn_message(REFERENCE_MESSAGE).fields))
        target.add_to_queue('GDN')
        self.app._ensure_whatsapp()
        self.assertIs(self.app.whatsapp_page, page)
        self.assertIs(self.app._whatsapp_lanes()['WhatsApp Lane 1'], target)
        self.assertEqual(len(target.queue), 1)

    def test_lane_queue_and_progress_can_be_scrolled_into_view(self):
        self.app.pages['whatsapp'].pack(fill='both', expand=True)
        self.app._ensure_whatsapp()
        page = self.app.whatsapp_page
        label = 'WhatsApp Lane 1'
        page.notebook.select(page.lane_tabs[label])
        self.root.geometry('1280x800')
        self.root.deiconify()
        self.root.update()
        canvas = page.lane_canvases[label]
        self.assertLess(canvas.yview()[1], 1)
        canvas.yview_moveto(1)
        self.root.update()
        progress = page.lanes[label].progress
        self.assertTrue(progress.winfo_ismapped())
        self.assertGreaterEqual(progress.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(progress.winfo_rooty()+progress.winfo_height(), canvas.winfo_rooty()+canvas.winfo_height())

    def test_standalone_inbox_also_has_its_own_two_lanes(self):
        self.app._ensure_tool1()
        page = open_inbox(self.root)
        self.assertIsNotNone(page)
        self.assertEqual(tuple(page.lanes), ('WhatsApp Lane 1', 'WhatsApp Lane 2'))
        self.assertNotIn(self.app.tool1_lanes['a'], page.lanes.values())
        reopened_window = open_inbox(self.root)
        self.assertIs(reopened_window._whatsapp_page, page)

    def test_partial_lane_creation_failure_retains_manual_lanes_and_controller(self):
        self.app._ensure_tool1()
        from whatsapp_page import KorberApp

        def fail_second_lane(*args, **kwargs):
            """Constructor failure test double; first lane uses the real UI."""
            if kwargs['profile_name'] == 'whatsapp_lane_2':
                raise RuntimeError('Test dedicated lane construction failure')
            return KorberApp(*args, **kwargs)

        with patch('whatsapp_page.KorberApp', side_effect=fail_second_lane):
            self.app._ensure_whatsapp()
        self.assertIsNone(self.app.whatsapp_page)
        self.assertIn('Test dedicated lane construction failure', self.app.whatsapp_error)
        self.assertEqual(set(self.root._whatsapp_gdn_lanes), {'Lane A', 'Lane B'})
        self.assertFalse(self.controller.closed)


if __name__ == '__main__':
    unittest.main()
