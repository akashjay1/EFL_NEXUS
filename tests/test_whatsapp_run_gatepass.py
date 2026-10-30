"""Real Tk/SQLite lane checks; launch/worker test doubles never open a portal."""

from pathlib import Path
from contextlib import closing
import tempfile
import threading
import sqlite3
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from korber_tool import KorberApp
from whatsapp_controller import WhatsAppController
from whatsapp_gdn import GDNInboxStore
from whatsapp_inbox import WhatsAppGDNInbox
from whatsapp_grn_inbox import WhatsAppGRNInbox
from test_whatsapp_gdn import REFERENCE_MESSAGE
from test_whatsapp_grn import image_double, snapshot_double


class RunGatepassTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        path = Path(folder.name) / 'inbox.sqlite3'
        self.controller = WhatsAppController(self.root, path, autostart=False)
        self.addCleanup(self.controller.shutdown)
        self.lanes = {name: KorberApp(self.root, container=ttk.Frame(self.root),
            standalone=False, profile_name=profile) for name, profile in [('Lane A', 'lane_a'), ('Lane B', 'lane_b')]}
        self.gdn = WhatsAppGDNInbox(self.root, self.lanes, GDNInboxStore(path), controller=self.controller)
        self.grn = WhatsAppGRNInbox(self.root, ttk.Frame(self.root), self.controller, self.lanes)
        self.gdn.lane_choice.set('Lane B')
        self.grn.lane.set('Lane B')
        self.lane = self.lanes['Lane B']
        self.root.update_idletasks()

    def destroy_root(self):
        for lane in self.lanes.values():
            lane._stop_progress()
        self.root.update_idletasks()
        self.root.destroy()

    def run_button(self, widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button) and child.cget('text') == 'Run Gatepass':
                return child
            found = self.run_button(child)
            if found is not None:
                return found
        return None

    def ready_grn(self):
        self.grn.store.discover(snapshot_double())
        source = self.grn.store.pending_entries()[0]
        record = self.grn.store.save_image(source['id'], image_double())
        with self.grn.store.db:
            self.grn.store.db.execute("UPDATE grn_documents SET state='Ready for review',gatepass='000123' WHERE id=?", (record,))
        self.grn.refresh()
        self.grn.tree.selection_set(str(record))
        self.grn._selected()
        self.grn.warehouse.set('EGDC')
        self.grn.confirmed.set(True)
        return record

    def test_gdn_button_fills_selected_lane_and_blocks_only_while_running(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE.replace('734683', '000123'))

        callbacks = []
        def launch_double(doc_type, on_complete):
            """Launch test double; verify values at the browser-start boundary."""
            self.assertEqual(doc_type, 'GDN')
            self.assertEqual(self.lane.gatepass_entry.get(), '000123')
            self.assertEqual(self.lane.delivery_entry.get(), 'KOREANA')
            self.assertEqual(self.lane.seal_entry.get(), 'EGF075133/004186')
            callbacks.append(on_complete)

        with patch.object(self.lane, 'run_flow', side_effect=launch_double) as launch:
            self.run_button(self.gdn.window).invoke()
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            self.assertEqual(launch.call_count, 1)
            self.assertEqual(self.gdn.store.get(record)['run_state'], 'Running')
            callbacks[0](True, 'Test GDN completed')
            self.assertEqual(self.gdn.store.get(record)['run_state'], 'Completed')
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
            self.assertEqual(launch.call_count, 2)
        self.assertEqual(self.gdn.store.get(record)['run_state'], 'Running')
        self.assertEqual(self.lanes['Lane A'].gatepass_entry.get(), '')
        self.assertEqual(self.lane.queue, [])

    def test_grn_button_calls_real_flow_with_filled_fields_and_worker_boundary_double(self):
        record = self.ready_grn()
        entered = threading.Event()

        def worker_double(*args):
            """Worker test double; stops before Selenium or portal operations."""
            entered.set()

        with patch.object(self.lane, '_run_flow_worker', side_effect=worker_double) as worker:
            self.run_button(self.grn.frame).invoke()
            self.assertTrue(entered.wait(2))
            worker.assert_called_once_with('GRN', 'EGDC', '', '000123', '', '')
        self.assertEqual(self.lane.grn_gatepass_entry.get(), '000123')
        self.assertEqual(self.lane.grn_warehouse_entry.get(), 'EGDC')
        self.assertEqual(self.grn.store.document(record)['action'], 'Filled: Lane B')
        self.assertEqual(self.grn.store.document(record)['run_state'], 'Running')
        self.assertEqual(self.lanes['Lane A'].grn_gatepass_entry.get(), '')
        self.assertIsNone(self.lane.driver)

    def test_invalid_gdn_and_unconfirmed_grn_do_not_launch(self):
        self.gdn.import_message(REFERENCE_MESSAGE.replace('Note: KOREANA', ''))
        self.ready_grn()
        self.grn.confirmed.set(False)
        with patch.object(self.lane, 'run_flow') as launch:  # Launch test double.
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            self.assertFalse(self.grn.fill_form(start_run=True))
            launch.assert_not_called()
        self.assertEqual(self.lane.gatepass_entry.get(), '')
        self.assertEqual(self.lane.grn_gatepass_entry.get(), '')

    def test_busy_lane_does_not_receive_values_or_launch(self):
        self.gdn.import_message(REFERENCE_MESSAGE)
        self.ready_grn()
        self.lane.gdn_btn.configure(state='disabled')
        self.lane.grn_btn.configure(state='disabled')
        with patch.object(self.lane, 'run_flow') as launch:  # Launch test double.
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            self.assertFalse(self.grn.fill_form(start_run=True))
            launch.assert_not_called()
        self.assertEqual(self.lane.gatepass_entry.get(), '')
        self.assertEqual(self.lane.grn_gatepass_entry.get(), '')

    def test_gdn_launch_error_returns_new_and_allows_retry(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        with patch.object(self.lane, 'run_flow', side_effect=RuntimeError('Test launch failure')) as launch:
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            self.gdn.save_review()
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            self.assertEqual(launch.call_count, 2)
        self.assertEqual(self.gdn.store.get(record)['run_state'], 'New')

    def test_grn_launch_error_returns_new_and_allows_retry(self):
        record = self.ready_grn()
        with patch.object(self.lane, 'run_flow', side_effect=RuntimeError('Test launch failure')) as launch:
            self.assertFalse(self.grn.fill_form(start_run=True))
            self.assertFalse(self.grn.fill_form(start_run=True))
            self.assertEqual(launch.call_count, 2)
        self.assertEqual(self.grn.store.document(record)['action'], 'Filled: Lane B')
        self.assertEqual(self.grn.store.document(record)['run_state'], 'New')

    def test_cleared_stale_selections_cannot_launch(self):
        self.gdn.import_message(REFERENCE_MESSAGE)
        self.ready_grn()
        self.gdn.store.clear_list()
        self.grn.store.clear_list()
        with patch.object(self.lane, 'run_flow') as launch:  # Launch test double.
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            self.assertFalse(self.grn.fill_form(start_run=True))
            launch.assert_not_called()

    def deferred_worker(self, workers):
        """Thread test double: run the real worker later on Tk's owning thread."""
        class WorkerDouble:
            def __init__(self, target, args=(), daemon=False):
                self.target, self.args = target, args
            def start(self):
                workers.append(self)
            def finish(self):
                self.target(*self.args)
        return patch('korber_tool.threading.Thread', WorkerDouble)

    def test_real_gdn_flow_transitions_and_can_complete_repeatedly(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        self.assertEqual(self.gdn.store.get(record)['run_state'], 'New')
        workers = []
        # Step-list test double keeps every portal action outside this regression.
        with self.deferred_worker(workers), patch.object(self.lane, '_build_steps', return_value=[
                ('test finish', 'Test flow finishing', lambda: None, 0)]):
            for attempt in range(3):
                self.assertTrue(self.gdn.apply_request(False, start_run=True))
                self.assertEqual(self.gdn.store.get(record)['run_state'], 'Running')
                self.assertTrue(self.lane._flow_active)
                self.assertFalse(self.gdn.apply_request(False, start_run=True))
                self.assertFalse(self.lane.run_flow('GDN'))
                workers[-1].finish()
                self.assertFalse(self.lane._flow_active)
                self.assertEqual(self.gdn.store.get(record)['run_state'], 'Completed')
                self.gdn.refresh()
                self.assertEqual(self.gdn.tree.item(str(record), 'values')[2], 'Completed')
                self.assertIn('Completed', self.gdn.status.get())
        history = self.gdn.store.db.execute('SELECT state FROM gatepass_runs ORDER BY rowid').fetchall()
        self.assertEqual([r[0] for r in history], ['Completed'] * 3)

    def test_real_grn_flow_completes_and_can_run_after_prior_fill(self):
        record = self.ready_grn()
        self.assertTrue(self.grn.fill_form())
        workers = []
        # Test step double completes without opening a browser or creating a GRN.
        with self.deferred_worker(workers), patch.object(self.lane, '_build_grn_steps', return_value=[
                ('test finish', 'Test GRN finishing', lambda: None, 0)]):
            for attempt in range(2):
                self.assertTrue(self.grn.fill_form(start_run=True))
                self.assertEqual(self.grn.store.document(record)['run_state'], 'Running')
                self.assertFalse(self.grn.fill_form(start_run=True))
                workers[-1].finish()
                self.assertEqual(self.grn.store.document(record)['run_state'], 'Completed')
                self.grn.refresh()
                self.assertEqual(self.grn.tree.item(str(record), 'values')[2], 'Completed')
                self.assertIn('Completed', self.grn.status.get())

    def test_actual_background_worker_saves_completion_while_tk_mainloop_runs(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        states, failures = [], []
        deadline = time.monotonic() + 5
        def launch():
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
            poll()
        def poll():
            states.append(self.gdn.store.get(record)['run_state'])
            if states[-1] == 'Completed' and str(self.lane.gdn_btn.cget('state')) != 'disabled':
                self.root.quit()
            elif time.monotonic() >= deadline:
                failures.append('Worker did not complete before the test deadline')
                self.root.quit()
            else:
                self.root.after(10, poll)
        # Only the portal step is a test double; run_flow, its thread, and Tk are real.
        with patch.object(self.lane, '_build_steps', return_value=[
                ('test completion', 'Completing test flow', lambda: None, 0)]):
            self.root.after(0, launch)
            self.root.mainloop()
        self.assertEqual(failures, [])
        self.assertIn('Running', states)
        self.assertEqual(states[-1], 'Completed')

    def test_retry_exhaustion_is_failure_and_never_completed(self):
        from selenium.common.exceptions import TimeoutException
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        workers = []
        def failing_step_double():
            """Portal step test double with a reproducible exhausted timeout."""
            raise TimeoutException('Test timeout')
        with self.deferred_worker(workers), patch.object(self.lane, '_build_steps', return_value=[
                ('test timeout', 'Waiting in test', failing_step_double, 0)]), \
                patch.object(self.lane, '_capture_diagnostics', return_value=(None, None)), \
                patch.object(self.lane, '_report_error', side_effect=lambda *_: self.lane._cancel_after_failure()):
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
            workers[-1].finish()
            self.assertEqual(self.gdn.store.get(record)['run_state'], 'New')
            self.assertFalse(self.lane._flow_active)
            self.assertTrue(self.gdn.apply_request(False, start_run=True))

    def test_step_preparation_failure_unlocks_after_error_is_acknowledged(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        workers = []
        with self.deferred_worker(workers), patch.object(self.lane, '_build_steps', side_effect=ValueError('Test preparation failure')), \
                patch.object(self.lane, '_report_error', side_effect=lambda *_: self.lane._cancel_after_failure()):
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
            workers[-1].finish()
        self.assertEqual(self.gdn.store.get(record)['run_state'], 'New')
        self.assertFalse(self.lane._flow_active)

    def test_repeat_releases_previous_browser_before_opening_same_lane_profile(self):
        events, workers = [], []
        class BrowserDouble:
            """Driver test double; no Chrome or portal session is launched."""
            def quit(self):
                events.append('closed')
        previous, replacement = BrowserDouble(), BrowserDouble()
        self.lane.driver = previous
        self.gdn.import_message(REFERENCE_MESSAGE)
        def opening_step_double(*_):
            """Step-list double checks that the previous profile owner is gone."""
            def open_double():
                self.assertIsNone(self.lane.driver)
                events.append('opened')
                self.lane.driver = replacement
            return [('test browser', 'Test browser', open_double, 0)]
        with self.deferred_worker(workers), patch.object(self.lane, '_build_steps', side_effect=opening_step_double):
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
            workers[-1].finish()
        self.assertEqual(events, ['closed', 'opened'])
        self.assertIs(self.lane.driver, replacement)

    def test_terminate_stops_worker_then_allows_repeat(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        workers, executed = [], []
        with self.deferred_worker(workers), patch.object(self.lane, '_build_steps', return_value=[
                ('test finish', 'Test flow', lambda: executed.append(True), 0)]), \
                patch('korber_tool.messagebox.askyesno', return_value=True):
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
            self.lane.terminate_session()
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            workers[-1].finish()
            self.assertEqual(executed, [])
            self.assertEqual(self.gdn.store.get(record)['run_state'], 'New')
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
            workers[-1].finish()
            self.assertEqual(self.gdn.store.get(record)['run_state'], 'Completed')

    def test_finished_queue_history_allows_intentional_rerun(self):
        self.gdn.import_message(REFERENCE_MESSAGE)
        self.gdn.apply_request(True)
        item = self.lane.queue[0]
        with patch.object(self.lane, 'run_flow') as launch:  # Launch test double.
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            launch.assert_not_called()
            item['status'] = 'Done'
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
            self.assertEqual(launch.call_count, 1)

    def test_clear_during_run_cannot_be_undone_by_completion(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        callbacks = []
        with patch.object(self.lane, 'run_flow', side_effect=lambda _, on_complete: callbacks.append(on_complete)):
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
        self.gdn.clear_list()
        callbacks[0](True, 'Test completion after clear')
        self.gdn.refresh()
        self.assertEqual(self.gdn.tree.get_children(), ())
        self.assertEqual(self.gdn.store.get(record)['hidden_reason'], 'cleared')
        self.assertEqual(self.gdn.store.get(record)['run_state'], 'Completed')

    def test_done_during_grn_run_stays_hidden_after_completion_and_cannot_rerun(self):
        record = self.ready_grn()
        callbacks = []
        source = self.grn.store.db.execute('SELECT group_id,message_id FROM grn_sources WHERE document_id=?', (record,)).fetchone()
        with patch.object(self.lane, 'run_flow', side_effect=lambda _, on_complete: callbacks.append(on_complete)):
            self.assertTrue(self.grn.fill_form(start_run=True))
        # Snapshot test double with a verified original-message association.
        self.grn.store.observe_messages({'group_id': source['group_id'], 'messages': [],
            'replies': [{'id': 'test-done-reply', 'text': 'DONE', 'reply_to': source['message_id']}]})
        callbacks[0](True, 'Test completion after DONE')
        self.grn.refresh()
        self.assertEqual(self.grn.tree.get_children(), ())
        self.assertEqual(self.grn.store.document(record)['hidden_reason'], 'done')
        self.grn.selected_id = record
        self.grn.confirmed.set(True)
        with patch.object(self.lane, 'run_flow') as launch:
            self.assertFalse(self.grn.fill_form(start_run=True))
            launch.assert_not_called()

    def test_completion_is_saved_from_worker_after_inbox_closes(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        path, callbacks, errors = self.gdn.store.path, [], []
        with patch.object(self.lane, 'run_flow', side_effect=lambda _, on_complete: callbacks.append(on_complete)):
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
        self.gdn.window.destroy()
        def complete_double():
            """Worker-completion test double exercises the real independent connection."""
            try:
                callbacks[0](True, 'Test completion after closing inbox')
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=complete_double)
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        store = GDNInboxStore(path)
        try:
            self.assertEqual(store.get(record)['run_state'], 'Completed')
        finally:
            store.close()

    def test_restart_recovery_and_late_callback_cannot_change_newer_run(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        store = self.gdn.store
        first = store.begin_gatepass_run(record, 'Lane B')
        store.recover_gatepass_runs(set(), 'GDN')
        self.assertEqual(store.get(record)['run_state'], 'New')
        second = store.begin_gatepass_run(record, 'Lane B')
        store.finish_gatepass_run(first, True, 'Late test callback')
        self.assertEqual(store.get(record)['run_state'], 'Running')
        self.assertEqual(store.get(record)['run_id'], second)
        store.finish_gatepass_run(second, True)
        reopened = GDNInboxStore(store.path)
        try:
            self.assertEqual(reopened.get(record)['run_state'], 'Completed')
        finally:
            reopened.close()

    def test_legacy_launch_flags_do_not_prevent_reruns(self):
        record = self.gdn.import_message(REFERENCE_MESSAGE)
        for old_action in ('Run requested: Lane B', 'Run uncertain: Lane B', 'Queued: Lane B'):
            self.gdn.store.save_review(record, self.gdn.store.get(record)['fields'], old_action)
            callbacks = []
            with patch.object(self.lane, 'run_flow', side_effect=lambda _, on_complete: callbacks.append(on_complete)):
                self.assertTrue(self.gdn.apply_request(False, start_run=True))
            callbacks[0](True, 'Test completion')

    def test_additive_migration_backs_up_existing_reviews_and_is_idempotent(self):
        path = self.gdn.store.path.with_name('legacy.sqlite3')
        original = self.gdn.store.get(self.gdn.import_message(REFERENCE_MESSAGE))
        with closing(sqlite3.connect(path)) as legacy, legacy:
            legacy.execute('''CREATE TABLE requests (
                id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, source TEXT NOT NULL,
                message_id TEXT NOT NULL, received_at TEXT NOT NULL, raw_text TEXT NOT NULL,
                fields TEXT NOT NULL, warnings TEXT NOT NULL, action TEXT NOT NULL DEFAULT 'New')''')
            import json
            legacy.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?)', (original['id'], original['fingerprint'],
                original['source'], original['message_id'], original['received_at'], original['raw_text'],
                json.dumps(original['fields']), json.dumps(original['warnings']), 'Run requested: Lane B'))
        for attempt in range(2):
            migrated = GDNInboxStore(path)
            try:
                item = migrated.get(original['id'])
                self.assertEqual(item['fields'], original['fields'])
                self.assertEqual(item['action'], 'Run requested: Lane B')
                self.assertEqual(item['run_state'], 'New')
            finally:
                migrated.close()
        backups = list(path.parent.glob('legacy.before-gatepass-runs-*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup:
            self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(backup.execute('SELECT action FROM requests').fetchone()[0], 'Run requested: Lane B')

    def test_running_gdn_blocks_corrected_duplicate_in_other_lane(self):
        self.gdn.import_message(REFERENCE_MESSAGE)
        with patch.object(self.lane, 'run_flow'):  # Launch test double.
            self.assertTrue(self.gdn.apply_request(False, start_run=True))
        self.gdn.import_message(REFERENCE_MESSAGE.replace('KOREANA', 'Koreana'))
        self.gdn.lane_choice.set('Lane A')
        with patch.object(self.lanes['Lane A'], 'run_flow') as launch:  # Launch test double.
            self.assertFalse(self.gdn.apply_request(False, start_run=True))
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
