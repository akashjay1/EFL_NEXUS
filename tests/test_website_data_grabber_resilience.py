import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import tkinter as tk
from website_data_grabber import (
    WebsiteDataGrabberApp,
    _browser_log_file,
    _write_results,
    job_ids_from_rows,
)


class WebsiteDataGrabberResilienceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk not available: {exc}")
        self.addCleanup(self.root.destroy)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.test_cfg_path = str(Path(self.tmp_dir.name) / "test_config.json")
        self.cfg_patcher = patch("outlook_email_gui.CONFIG_JSON_PATH", self.test_cfg_path)
        self.cfg_patcher.start()
        self.addCleanup(self.cfg_patcher.stop)
        self.pwd_save_patcher = patch("website_data_grabber._save_password")
        self.pwd_save_patcher.start()
        self.addCleanup(self.pwd_save_patcher.stop)

    def test_job_ids_from_rows_with_various_job_header_names(self):
        rows = [["JB-001", "Pending"], ["JB-002", "Pending"]]

        # Job Number
        self.assertEqual(
            job_ids_from_rows(["Job Number", "Reconciliation Status"], rows, required_status="Pending"),
            ["JB-001", "JB-002"],
        )
        # Job No
        self.assertEqual(
            job_ids_from_rows(["Job No", "Reconciliation Status"], rows, required_status="Pending"),
            ["JB-001", "JB-002"],
        )
        # Case and whitespace normalization
        rows_dirty = [["  JB-001  ", "Pending"], ["jb-001", "Pending"], ["JB-003", "Pending"]]
        self.assertEqual(
            job_ids_from_rows(["Job ID", "Reconciliation Status"], rows_dirty, required_status="Pending"),
            ["JB-001", "JB-003"],
        )

    def test_write_results_atomically_persists_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test_results.json"
            _write_results(target, ["ID-1", "ID-2", "ID-3"])
            self.assertTrue(target.exists())
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data, {"job_ids": ["ID-1", "ID-2", "ID-3"]})

    def test_write_results_with_records_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test_results.json"
            records = [{"job_id": "ID-1", "status": "Pending"}, {"job_id": "ID-2", "status": "In Progress"}]
            _write_results(target, ["ID-1", "ID-2"], records=records)
            self.assertTrue(target.exists())
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(data, {"job_ids": ["ID-1", "ID-2"], "records": records})

    def test_poll_internal_browser_results_reads_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test_results.json"
            records = [{"job_id": "ID-10", "status": "Pending"}, {"job_id": "ID-20", "status": "In Progress"}]
            _write_results(target, ["ID-10", "ID-20"], records=records)

            app = WebsiteDataGrabberApp(self.root, config_store=None)
            app.result_path = target
            app._poll_internal_browser_results()

            self.assertEqual(app.job_ids, ["ID-10", "ID-20"])
            self.assertEqual(app.records, records)
            self.assertIn("1 Pending", app.status.get())
            self.assertIn("1 In Progress", app.status.get())

    def test_command_file_lifecycle_and_bridge_consumption(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_cmd = Path(tmpdir) / "test_cmd.json"
            from website_data_grabber import _command_file

            with patch("website_data_grabber._command_file", return_value=test_cmd):
                app = WebsiteDataGrabberApp(self.root, config_store=None)
                app._send_browser_command("start_job", job_id="OUT_0000007024")

                self.assertTrue(test_cmd.exists())

                # Simulate ResultsBridge reading the command
                from website_data_grabber import run_internal_browser
                # Test the logic matching bridge.get_pending_command
                content = json.loads(test_cmd.read_text(encoding="utf-8"))
                self.assertEqual(content["action"], "start_job")
                self.assertEqual(content["job_id"], "OUT_0000007024")
                test_cmd.unlink()
                self.assertFalse(test_cmd.exists())

    @patch("website_data_grabber.messagebox.showerror")
    def test_start_preflight_blocks_when_pywebview_missing(self, mock_err):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.login_url.set("https://active.efl3plofc.com/login")
        app.username.set("operator@efl.global")
        app.password.set("ValidPass123")

        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "webview":
                raise ImportError("No module named 'webview'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            app.start()

        mock_err.assert_called_once()
        self.assertIn("pywebview", app.status.get())
        self.assertIsNone(app.browser_process)

    @patch("website_data_grabber.messagebox.showerror")
    def test_find_and_embed_detects_subprocess_crash_and_alerts_user(self, mock_err):
        app = WebsiteDataGrabberApp(self.root, config_store=None)

        # Simulate a dead process with exit code 1
        dead_proc = Mock()
        dead_proc.poll.return_value = 1
        dead_proc.pid = 99999
        app.browser_process = dead_proc

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as log_file:
            log_file.write("Traceback:\nModuleNotFoundError: No module named 'webview'\n")
            log_path = Path(log_file.name)
        app.browser_log_path = log_path

        app._find_and_embed_internal_browser()

        # browser_process must be cleared so user can retry cleanly
        self.assertIsNone(app.browser_process)
        mock_err.assert_called_once()
        self.assertIn("code 1", app.status.get())
        dialog_text = mock_err.call_args[0][1]
        self.assertIn("ModuleNotFoundError", dialog_text)

        try:
            log_path.unlink()
        except Exception:
            pass

    def test_close_browser_cleans_up_process_and_handles(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        mock_proc = Mock()
        mock_proc.poll.return_value = None  # running
        app.browser_process = mock_proc
        app.browser_hwnd = 12345
        mock_handle = Mock()
        mock_handle.closed = False
        app._browser_log_handle = mock_handle

        app.close_browser()

        mock_proc.terminate.assert_called_once()
        mock_handle.close.assert_called_once()
        self.assertIsNone(app.browser_process)
        self.assertIsNone(app.browser_hwnd)


if __name__ == "__main__":
    unittest.main()
