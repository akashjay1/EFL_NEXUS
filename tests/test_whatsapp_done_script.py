"""Quote resolver checks using an explicitly labelled minimal DOM test double."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from whatsapp_monitor import RESOLVE_DONE_JS


@unittest.skipUnless(shutil.which('node'), 'Node is required for JavaScript state checks')
class DoneReplyScriptTests(unittest.TestCase):
    def scenario(self, scenario):
        result = subprocess.run(['node', str(Path(__file__).with_name('whatsapp_done_dom_double.js'))],
            input=json.dumps({'script': RESOLVE_DONE_JS, 'scenario': scenario}),
            capture_output=True, text=True, timeout=5, check=True)
        return json.loads(result.stdout)

    def test_verified_original_highlight_links_identity_and_restores_view(self):
        result = self.scenario('ready')
        self.assertTrue(result['first']['reply_scan_pending'])
        self.assertEqual(result['second']['replies'][0]['reply_to'], 'test-original')
        self.assertFalse(result['second']['unresolved_done'])
        self.assertTrue(result['restored'])

    def test_missing_ambiguous_unrelated_or_interrupted_highlights_do_not_link(self):
        for scenario in ('missing', 'ambiguous', 'unrelated-animation', 'interrupted'):
            with self.subTest(scenario=scenario):
                result = self.scenario(scenario)
                self.assertIsNone(result['second']['replies'][0]['reply_to'])
                self.assertEqual(result['second']['unresolved_done'], ['test-reply'])
                self.assertFalse(result['second'].get('reply_scan_pending', False))
