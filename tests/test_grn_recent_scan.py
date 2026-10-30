"""Real timestamp and SQLite checks for the rolling one-hour GRN scan policy."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
import unittest

from whatsapp_grn import GRNInboxStore, grn_message_epoch, grn_photo_is_recent


class RecentGRNScanTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = GRNInboxStore(Path(folder.name) / 'inbox.sqlite3')
        self.addCleanup(self.store.close)

    def snapshot(self, **times):
        """Timestamp-only source fixtures; no browser, image or OCR is substituted."""
        return {'group_id': 'test-group', 'name': 'Test group', 'messages': [],
                'photos': [{'message_id': message, 'index': 0, 'message_time': stamp}
                           for message, stamp in times.items()]}

    def test_only_recent_received_times_are_imported(self):
        now = datetime.now(timezone.utc)
        counts = self.store.discover(self.snapshot(
            recent=(now-timedelta(minutes=30)).isoformat(),
            old=(now-timedelta(hours=2)).isoformat(),
            future=(now+timedelta(minutes=5)).isoformat(),
            missing='', unsupported='yesterday at noon'), import_visible=True, recent_only=True)
        self.assertEqual([row['message_id'] for row in self.store.pending_entries()], ['recent'])
        self.assertEqual(counts, {'eligible': 1, 'outside_window': 2, 'unknown_time': 2})

    def test_exact_cutoff_future_and_missing_times(self):
        now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(grn_photo_is_recent((now-timedelta(hours=1)).isoformat(), now.timestamp()))
        self.assertFalse(grn_photo_is_recent((now-timedelta(hours=1, seconds=1)).isoformat(), now.timestamp()))
        self.assertTrue(grn_photo_is_recent(now.isoformat(), now.timestamp()))
        self.assertFalse(grn_photo_is_recent((now+timedelta(seconds=1)).isoformat(), now.timestamp()))
        self.assertFalse(grn_photo_is_recent('', now.timestamp()))

    def test_verified_display_format_and_midnight_crossing(self):
        now = datetime(2026, 10, 26, 0, 15)
        self.assertTrue(grn_photo_is_recent('23:30, 25/10/2026', now.timestamp()))
        self.assertTrue(grn_photo_is_recent('11:30 PM, 25/10/2026', now.timestamp()))
        self.assertFalse(grn_photo_is_recent('22:30, 25/10/2026', now.timestamp()))
        self.assertIsNone(grn_message_epoch('10:00, 31/02/2026'))
        self.assertIsNone(grn_message_epoch('2026-10-26T00:00:00'))

    def test_old_backlog_does_not_block_recent_photos(self):
        now = datetime.now(timezone.utc)
        self.store.discover(self.snapshot(old=(now-timedelta(hours=2)).isoformat(),
                                          recent=(now-timedelta(minutes=5)).isoformat()))
        pending = self.store.pending_capture('test-group', recent_only=True, visible_ids={'old', 'recent'})
        self.assertEqual([row['message_id'] for row in pending], ['recent'])
        self.assertEqual(len(self.store.pending_entries()), 2)

    def test_expired_retry_cannot_bypass_the_capture_cutoff(self):
        self.store.discover(self.snapshot(recent=datetime.now(timezone.utc).isoformat()), recent_only=True)
        source_id = self.store.pending_entries()[0]['id']
        with self.store.db:
            self.store.db.execute('UPDATE grn_sources SET message_received_at=? WHERE id=?', (time.time()-3601, source_id))
        self.store.retry()
        self.assertEqual(self.store.pending_capture('test-group', owner_id=source_id, recent_only=True), [])

    def test_baseline_scan_and_done_visibility_remain_sticky(self):
        snapshot = self.snapshot(recent=datetime.now(timezone.utc).isoformat())
        self.store.discover(snapshot, baseline=True, recent_only=True)
        self.assertEqual(self.store.pending_capture('test-group', recent_only=True), [])
        self.store.discover(snapshot, import_visible=True, recent_only=True)
        self.assertEqual(len(self.store.pending_capture('test-group', recent_only=True)), 1)
        self.store.clear_list()
        self.store.discover(snapshot, import_visible=True, recent_only=True)
        self.assertEqual(self.store.pending_entries(), [])


if __name__ == '__main__':
    unittest.main()
