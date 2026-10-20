"""Browser state tests use an explicitly labelled DOM double, not a live session."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from whatsapp_grn import photo_read_script


@unittest.skipUnless(shutil.which('node'), 'Node is required for JavaScript state checks')
class OriginalPhotoScriptTests(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run(['node', str(Path(__file__).with_name('whatsapp_photo_dom_double.js'))],
            input=json.dumps({'script': photo_read_script('name:Test group', 'test-message', 0), 'scenario': scenario}),
            capture_output=True, text=True, timeout=5, check=True)
        return json.loads(result.stdout)

    def test_reads_full_viewer_and_closes_only_its_own_viewer(self):
        result = self.run_scenario('ready')
        self.assertTrue(result['first']['waiting'])
        self.assertEqual(result['result']['quality'], 'full_viewer')
        self.assertEqual((result['opened'], result['closed'], result['fetches']), (1, 1, 1))

    def test_blurred_full_size_image_is_not_stored(self):
        result = self.run_scenario('blurred')
        self.assertTrue(result['result']['waiting'])
        self.assertNotIn('data', result['result'])
        self.assertEqual(result['fetches'], 0)

    def test_thumbnail_cannot_substitute_for_missing_viewer_image(self):
        result = self.run_scenario('thumbnail_only')
        self.assertTrue(result['result']['waiting'])
        self.assertNotIn('data', result['result'])
        self.assertEqual(result['fetches'], 0)

    def test_incomplete_image_waits_without_fetching(self):
        result = self.run_scenario('incomplete')
        self.assertTrue(result['result']['waiting'])
        self.assertEqual(result['fetches'], 0)

    def test_user_opened_viewer_is_left_untouched(self):
        result = self.run_scenario('user_viewer')
        self.assertTrue(result['result']['waiting'])
        self.assertEqual((result['opened'], result['closed'], result['fetches']), (0, 0, 0))

    def test_wrong_group_is_rejected_before_opening_photo(self):
        result = self.run_scenario('wrong_group')
        self.assertIn('selected group', result['result']['error'])
        self.assertEqual((result['opened'], result['closed'], result['fetches']), (0, 0, 0))

    def test_fetch_failure_releases_the_owned_viewer_for_next_photo(self):
        result = self.run_scenario('fetch_error')
        self.assertIn('could not be retrieved', result['result']['error'])
        self.assertEqual((result['opened'], result['closed'], result['fetches']), (1, 1, 1))
