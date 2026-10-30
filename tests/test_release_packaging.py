"""Real temporary files and ZIP round trips; no application binary is substituted."""

from pathlib import Path
import tempfile
import unittest
import zipfile

from build_release import full_release_zip, sanitize_distribution
from create_patch import _should_ignore_file, build_patch_zip


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.new = self.root / 'new'
        self.previous = self.root / 'previous'
        self.new.mkdir()
        self.previous.mkdir()

    def write(self, relative, content='Packaging test input, not production data.'):
        path = self.new / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def test_state_is_excluded_but_ocr_assets_and_modules_are_allowed(self):
        for name in ('config.json', '_internal/.env', '.env.local', 'grn_images/photo.png',
                     'whatsapp_gdn/inbox.sqlite3', 'inbox.sqlite3-wal', 'chrome_automation_profile_whatsapp_lane_1/session',
                     'diagnostics/header.png'):
            with self.subTest(name=name):
                self.assertTrue(_should_ignore_file(name))
        for name in ('_internal/assets/grn_ocr/tesseract.exe', '_internal/assets/grn_ocr/tessdata/eng.traineddata',
                     '_internal/zxingcpp.pyd', '_internal/cv2/cv2.pyd', 'grn_cloud_ocr.py', 'whatsapp_media.py'):
            with self.subTest(name=name):
                self.assertFalse(_should_ignore_file(name))

    def test_full_zip_preserves_metadata_and_excludes_runtime_state(self):
        expected = {'version.txt', 'build.txt', '_internal/assets/grn_ocr/NOTICE.txt'}
        for name in expected | {'config.json', '.env', 'grn_images/private.txt', 'inbox.sqlite3'}:
            self.write(name)
        archive = self.root / 'release.zip'
        full_release_zip(self.new, archive)
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(set(bundle.namelist()), expected)
            self.assertIsNone(bundle.testzip())
        sanitize_distribution(self.new)
        self.assertEqual({path.relative_to(self.new).as_posix() for path in self.new.rglob('*') if path.is_file()}, expected)

    def test_patch_includes_new_ocr_files_without_user_state(self):
        # These are plain-text release fixtures; they do not claim to be executables.
        self.write('version.txt', '0.0.0-test')
        self.write('grn_cloud_ocr.py', '"""Packaging test source fixture."""\n')
        self.write('_internal/assets/grn_ocr/NOTICE.txt')
        self.write('grn_images/private.txt')
        self.write('inbox.sqlite3')
        archive = self.root / 'patch.zip'
        build_patch_zip(self.new, self.previous, archive, '0.0.0-test', 1, True)
        with zipfile.ZipFile(archive) as bundle:
            self.assertTrue({'version.txt', 'build.txt', 'grn_cloud_ocr.py', '_internal/assets/grn_ocr/NOTICE.txt'} <= set(bundle.namelist()))
            self.assertNotIn('grn_images/private.txt', bundle.namelist())
            self.assertNotIn('inbox.sqlite3', bundle.namelist())
            self.assertEqual(bundle.read('build.txt').decode(), '1')

    def test_zip_cannot_include_its_own_output(self):
        self.write('version.txt')
        with self.assertRaisesRegex(RuntimeError, 'outside the distribution'):
            full_release_zip(self.new, self.new / 'release.zip')


if __name__ == '__main__':
    unittest.main()
