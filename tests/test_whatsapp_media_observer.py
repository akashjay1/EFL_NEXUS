"""Observer behavior checks against an explicitly labelled minimal DOM double."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from whatsapp_monitor import READ_CONVERSATION_JS, ACK_PHOTOS_JS
from whatsapp_grn import GRNInboxStore


@unittest.skipUnless(shutil.which('node'), 'Node is required for DOM state checks')
class PhotoObserverTests(unittest.TestCase):
    def scenario(self, name):
        result = subprocess.run(['node', str(Path(__file__).with_name('whatsapp_media_dom_double.js'))],
                                input=json.dumps({'script': READ_CONVERSATION_JS, 'ack_script': ACK_PHOTOS_JS, 'scenario': name}),
                                capture_output=True, text=True, timeout=5, check=True)
        return json.loads(result.stdout)

    def test_album_lists_one_source_for_each_image(self):
        result = self.scenario('album')
        self.assertEqual([0, 1, 2], [photo['index'] for photo in result['photos']])

    def test_captionless_photos_exclude_outgoing_quotes_and_unverified_senders(self):
        result = self.scenario('directions')
        self.assertEqual(['incoming'], [photo['message_id'] for photo in result['photos']])
        self.assertEqual(['uncertain'], [photo['message_id'] for photo in result['unclassifiedPhotos']])

    def test_transient_album_is_detected_once_but_is_not_marked_visible(self):
        result = self.scenario('transient')
        self.assertEqual([0, 1], [photo['index'] for photo in result['first']['photos']])
        self.assertEqual([], result['first']['visible_photos'])
        self.assertEqual(2, len(result['repeated']['photos']))
        self.assertEqual([], result['second']['photos'])

    def test_group_change_cannot_drain_observed_photos_into_another_group(self):
        result = self.scenario('group_changed')
        self.assertIn('error', result['first'])
        self.assertNotIn('photos', result['first'])

    def test_single_viewer_owner_keeps_its_source_while_other_photos_arrive(self):
        with tempfile.TemporaryDirectory() as folder:
            store = GRNInboxStore(Path(folder) / 'inbox.sqlite3')
            try:
                # Explicit snapshot test double for scheduling; no browser or media is substituted.
                store.discover({'group_id': 'test-group', 'name': 'Test group', 'messages': [],
                                'photos': [{'message_id': 'album', 'index': i} for i in range(3)]})
                sources = store.pending_capture('test-group', limit=3, visible_ids={'album'})
                owner = sources[1]['id']
                selected = store.pending_capture('test-group', visible_ids={'album'}, owner_id=owner)
                self.assertEqual([owner], [row['id'] for row in selected])
                self.assertEqual([], store.pending_capture('test-group', visible_ids=set(), owner_id=owner))
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
