import unittest
from unittest.mock import Mock, patch
import tkinter as tk

from website_data_grabber import (
    DEFAULT_LOGIN_URL,
    WebsiteDataGrabberApp,
    extract_jobs_with_status,
    job_ids_from_rows,
    normalize_reconciliation_status,
)


class WebsiteDataGrabberExtractionTests(unittest.TestCase):
    def test_uses_confirmed_portal_login_url(self):
        self.assertEqual(DEFAULT_LOGIN_URL, "https://active.efl3plofc.com/login")

    def test_extracts_and_deduplicates_job_id_column(self):
        result = job_ids_from_rows(
            ["Warehouse", "Job ID", "Status"],
            [["A", " JOB-100 ", "Open"], ["B", "job-100", "Closed"], ["C", "JOB-200", "Open"]],
        )
        self.assertEqual(result, ["JOB-100", "JOB-200"])

    def test_accepts_exact_custom_column_name(self):
        result = job_ids_from_rows(["Load Reference", "State"], [["REF-1", "Open"]], "Load Reference")
        self.assertEqual(result, ["REF-1"])

    def test_returns_no_values_when_table_has_no_job_column(self):
        self.assertEqual(job_ids_from_rows(["Order", "State"], [["A1", "Open"]]), [])

    def test_filters_to_pending_reconciliation_status_only(self):
        result = job_ids_from_rows(
            ["Job ID", "Reconciliation Status"],
            [["OUT-1", "Pending"], ["OUT-2", "on Progress"], ["OUT-3", "pending"]],
            required_status="Pending",
        )
        self.assertEqual(result, ["OUT-1", "OUT-3"])


class WebsiteDataGrabberCredentialsTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk not available: {exc}")
        self.addCleanup(self.root.destroy)
        import tempfile
        from pathlib import Path
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.test_cfg_path = str(Path(self.tmp_dir.name) / "test_config.json")
        self.cfg_patcher = patch("outlook_email_gui.CONFIG_JSON_PATH", self.test_cfg_path)
        self.cfg_patcher.start()
        self.addCleanup(self.cfg_patcher.stop)

    @patch("website_data_grabber._load_saved_password", return_value="SecretPass123")
    @patch("website_data_grabber._save_password")
    def test_save_credentials_succeeds_even_if_config_store_is_none(self, mock_save_pwd, _mock_load_pwd):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.config_store = None
        app.login_url.set("https://active.efl3plofc.com/login")
        app.username.set("test_user@efl.global")
        app.password.set("SecretPass123")

        result = app.save_credentials(show_success=False)

        self.assertTrue(result)
        mock_save_pwd.assert_called_once_with("SecretPass123", "test_user@efl.global")

    @patch("website_data_grabber._load_saved_password", return_value="SecretPass123")
    @patch("website_data_grabber._save_password")
    def test_save_credentials_succeeds_even_if_config_store_save_fails(self, mock_save_pwd, _mock_load_pwd):
        failing_store = Mock()
        failing_store.save.side_effect = IOError("Simulated disk error")
        failing_store.config = {}

        app = WebsiteDataGrabberApp(self.root, config_store=failing_store)
        app.login_url.set("https://active.efl3plofc.com/login")
        app.username.set("test_user@efl.global")
        app.password.set("SecretPass123")

        result = app.save_credentials(show_success=False)

        self.assertTrue(result)
        mock_save_pwd.assert_called_once_with("SecretPass123", "test_user@efl.global")

    @patch("website_data_grabber._load_saved_password", return_value="SecretPass123")
    @patch("website_data_grabber._save_password")
    def test_save_credentials_persists_to_config_store_when_available(self, mock_save_pwd, _mock_load_pwd):
        mock_store = Mock()
        mock_store.save.return_value = True
        mock_store.config = {}

        app = WebsiteDataGrabberApp(self.root, config_store=mock_store)
        app.login_url.set("https://active.efl3plofc.com/login")
        app.username.set("operator@efl.global")
        app.password.set("SecretPass123")

        result = app.save_credentials(show_success=False)

        self.assertTrue(result)
        mock_save_pwd.assert_called_once_with("SecretPass123", "operator@efl.global")
        mock_store.save.assert_called_once()

    @patch("website_data_grabber.messagebox.showerror")
    @patch("website_data_grabber._save_password", side_effect=RuntimeError("Credential store locked"))
    def test_save_credentials_fails_cleanly_when_password_cannot_be_saved(self, mock_save_pwd, mock_err):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.login_url.set("https://active.efl3plofc.com/login")
        app.username.set("operator@efl.global")
        app.password.set("SecretPass123")

        result = app.save_credentials(show_success=False)

        self.assertFalse(result)
        mock_err.assert_called_once()


class WebsiteDataGrabberStatusTests(unittest.TestCase):
    def test_normalize_reconciliation_status_variants(self):
        self.assertEqual(normalize_reconciliation_status("pending"), "Pending")
        self.assertEqual(normalize_reconciliation_status("Pending"), "Pending")
        self.assertEqual(normalize_reconciliation_status("  PENDING  "), "Pending")
        self.assertEqual(normalize_reconciliation_status("on Progress"), "In Progress")
        self.assertEqual(normalize_reconciliation_status("in progress"), "In Progress")
        self.assertEqual(normalize_reconciliation_status("InProgress"), "In Progress")
        self.assertEqual(normalize_reconciliation_status("In Progress"), "In Progress")
        self.assertEqual(normalize_reconciliation_status("completed"), "Completed")
        self.assertEqual(normalize_reconciliation_status(""), "Unknown")
        self.assertEqual(normalize_reconciliation_status(None), "Unknown")
        self.assertEqual(normalize_reconciliation_status("On Hold"), "On Hold")

    def test_extract_jobs_with_status_extracts_all_and_normalizes(self):
        headers = ["Warehouse", "Job ID", "Reconciliation Status"]
        rows = [
            ["W1", "OUT-101", "Pending"],
            ["W2", "OUT-102", "on Progress"],
            ["W1", "out-101", "Pending"],  # duplicate ID
            ["W3", "OUT-103", "in progress"],
            ["W2", "OUT-104", "completed"],
            ["W1", "OUT-105", ""],
        ]
        results = extract_jobs_with_status(headers, rows)
        self.assertEqual(
            results,
            [
                {"job_id": "OUT-101", "status": "Pending"},
                {"job_id": "OUT-102", "status": "In Progress"},
                {"job_id": "OUT-103", "status": "In Progress"},
                {"job_id": "OUT-104", "status": "Completed"},
                {"job_id": "OUT-105", "status": "Unknown"},
            ],
        )

    def test_extract_jobs_with_status_without_status_column(self):
        headers = ["Job Number", "Customer"]
        rows = [["JB-1", "Acme"], ["JB-2", "Beta"]]
        results = extract_jobs_with_status(headers, rows)
        self.assertEqual(
            results,
            [
                {"job_id": "JB-1", "status": "Unknown"},
                {"job_id": "JB-2", "status": "Unknown"},
            ],
        )


class WebsiteDataGrabberUITests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk not available: {exc}")
        self.addCleanup(self.root.destroy)
        import tempfile
        from pathlib import Path
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.test_cfg_path = str(Path(self.tmp_dir.name) / "test_config.json")
        self.cfg_patcher = patch("outlook_email_gui.CONFIG_JSON_PATH", self.test_cfg_path)
        self.cfg_patcher.start()
        self.addCleanup(self.cfg_patcher.stop)
        self.pwd_save_patcher = patch("website_data_grabber._save_password")
        self.pwd_save_patcher.start()
        self.addCleanup(self.pwd_save_patcher.stop)

    def test_show_results_populates_treeview_and_breakdown(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        records = [
            {"job_id": "OUT-001", "status": "Pending"},
            {"job_id": "OUT-002", "status": "In Progress"},
            {"job_id": "OUT-003", "status": "Pending"},
        ]
        app._show_results(records)

        self.assertEqual(app.job_ids, ["OUT-001", "OUT-002", "OUT-003"])
        self.assertEqual(len(app.records), 3)
        self.assertIn("3 Job ID(s)", app.status.get())
        self.assertIn("2 Pending", app.status.get())
        self.assertIn("1 In Progress", app.status.get())

        # Verify Treeview content
        children = app.tree.get_children()
        self.assertEqual(len(children), 3)
        self.assertEqual(app.tree.item(children[0], "values"), ("OUT-001", "", "Pending", "▶ Start"))
        self.assertEqual(app.tree.item(children[1], "values"), ("OUT-002", "", "In Progress", "▶ Start"))
        self.assertEqual(app.tree.item(children[2], "values"), ("OUT-003", "", "Pending", "▶ Start"))

        # Verify records with Client
        app._show_results([{"job_id": "OUT-004", "client": "GAMMA", "status": "In Progress"}])
        child = app.tree.get_children()[0]
        self.assertEqual(app.tree.item(child, "values"), ("OUT-004", "GAMMA", "In Progress", "▶ Start"))

    def test_start_selected_job_dispatches_command_file(self):
        import json
        from website_data_grabber import _command_file
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        records = [{"job_id": "OUT-0000007024", "status": "In Progress"}]
        app._show_results(records)

        # Select the item
        children = app.tree.get_children()
        app.tree.selection_set(children[0])

        # Mock browser_process to appear running
        mock_proc = Mock()
        mock_proc.poll.return_value = None
        app.browser_process = mock_proc

        app.start_selected_job()

        cmd_file = _command_file()
        try:
            self.assertTrue(cmd_file.exists())
            data = json.loads(cmd_file.read_text(encoding="utf-8"))
            self.assertEqual(data["action"], "start_job")
            self.assertEqual(data["job_id"], "OUT-0000007024")
            self.assertIn("Sent Start request for Job ID 'OUT-0000007024'", app.status.get())
        finally:
            cmd_file.unlink(missing_ok=True)

    @patch("website_data_grabber.messagebox.showinfo")
    def test_start_selected_job_shows_info_when_no_row_selected(self, mock_info):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.tree.selection_set()  # clear selection
        app.start_selected_job()
        mock_info.assert_called_once()

    def test_export_csv_writes_job_id_and_reconciliation_status(self):
        import csv
        import tempfile
        from pathlib import Path

        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.records = [
            {"job_id": "OUT-001", "status": "Pending"},
            {"job_id": "OUT-002", "status": "In Progress"},
        ]
        app.job_ids = ["OUT-001", "OUT-002"]

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp_path = Path(tmp.name)

        try:
            with patch("website_data_grabber.filedialog.asksaveasfilename", return_value=str(tmp_path)):
                app.export_csv()

            with tmp_path.open(encoding="utf-8-sig") as f:
                reader = list(csv.reader(f))
            self.assertEqual(reader[0], ["Job ID", "Reconciliation Status"])
            self.assertEqual(reader[1], ["OUT-001", "Pending"])
            self.assertEqual(reader[2], ["OUT-002", "In Progress"])
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_browser_navigation_dispatches_ipc_commands(self):
        import json
        from website_data_grabber import _command_file
        app = WebsiteDataGrabberApp(self.root, config_store=None)

        # Mock browser_process to appear running
        mock_proc = Mock()
        mock_proc.poll.return_value = None
        app.browser_process = mock_proc

        cmd_file = _command_file()
        try:
            # Test go_back
            app.browser_go_back()
            self.assertTrue(cmd_file.exists())
            data = json.loads(cmd_file.read_text(encoding="utf-8"))
            self.assertEqual(data["action"], "go_back")
            cmd_file.unlink()

            # Test reload
            app.browser_reload()
            self.assertTrue(cmd_file.exists())
            data = json.loads(cmd_file.read_text(encoding="utf-8"))
            self.assertEqual(data["action"], "reload")
            cmd_file.unlink()

            # Test go_home
            app.browser_go_home()
            self.assertTrue(cmd_file.exists())
            data = json.loads(cmd_file.read_text(encoding="utf-8"))
            self.assertEqual(data["action"], "go_home")
            self.assertIn("clerk-dashboard", data["url"])
            cmd_file.unlink()
        finally:
            cmd_file.unlink(missing_ok=True)

    def test_browser_navigation_with_selenium_driver(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        mock_driver = Mock()
        app.driver = mock_driver

        app.browser_go_back()
        mock_driver.back.assert_called_once()
        self.assertIn("Navigated back in browser", app.status.get())

        app.browser_reload()
        mock_driver.refresh.assert_called_once()
        self.assertIn("Reloaded browser page", app.status.get())

        app.browser_go_home()
        mock_driver.get.assert_called_once()
        self.assertIn("Navigated to Reconciliation dashboard", app.status.get())

    @patch("website_data_grabber.messagebox.showinfo")
    def test_browser_navigation_when_browser_not_open(self, mock_info):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.driver = None
        app.browser_process = None

        app.browser_go_back()
        mock_info.assert_called_once()

        mock_info.reset_mock()
        app.browser_reload()
        mock_info.assert_called_once()

        mock_info.reset_mock()
        app.browser_go_home()
        mock_info.assert_called_once()

    def test_action_column_click_triggers_start_job(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app._show_results([{"job_id": "OUT-0000007024", "status": "Pending"}])
        children = app.tree.get_children()
        self.assertTrue(len(children) > 0)
        item = children[0]

        app.tree.identify_region = lambda x, y: "cell"
        app.tree.identify_column = lambda x: f"#{len(app.tree['columns'])}"
        app.tree.identify_row = lambda y: item

        app.start_selected_job = Mock()

        class DummyEvent:
            x = 250
            y = 20

        app._on_tree_button_1(DummyEvent())
        self.assertEqual(app._pressed_action_row, item)
        self.assertEqual(app.tree.selection(), (item,))

        app._on_tree_release_1(DummyEvent())
        app.start_selected_job.assert_called_once()
        self.assertIsNone(app._pressed_action_row)

    def test_non_action_column_click_does_not_trigger_start(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app._show_results([{"job_id": "OUT-0000007024", "status": "Pending"}])
        item = app.tree.get_children()[0]

        app.tree.identify_region = lambda x, y: "cell"
        app.tree.identify_column = lambda x: "#1"
        app.tree.identify_row = lambda y: item

        app.start_selected_job = Mock()

        class DummyEvent:
            x = 50
            y = 20

        app._on_tree_button_1(DummyEvent())
        self.assertIsNone(app._pressed_action_row)

        app._on_tree_release_1(DummyEvent())
        app.start_selected_job.assert_not_called()

    def test_action_column_hover_cursor(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app._show_results([{"job_id": "OUT-0000007024", "status": "Pending"}])
        item = app.tree.get_children()[0]

        app.tree.identify_region = lambda x, y: "cell"
        app.tree.identify_column = lambda x: f"#{len(app.tree['columns'])}" if x == 250 else "#1"
        app.tree.identify_row = lambda y: item

        class DummyEvent:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        app._on_tree_motion(DummyEvent(250, 20))
        self.assertEqual(str(app.tree.cget("cursor")), "hand2")

        app._on_tree_motion(DummyEvent(50, 20))
        self.assertEqual(str(app.tree.cget("cursor")), "")

        app._on_tree_leave()
        self.assertEqual(str(app.tree.cget("cursor")), "")

    def test_auto_refresh_badge_present(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        self.assertTrue(hasattr(app, "auto_refresh_badge"))
        self.assertIn("Auto-Refresh: 5s", app.auto_refresh_badge.cget("text"))

    def test_show_results_preserves_selection_on_update(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app._show_results([
            {"job_id": "OUT-001", "status": "Pending"},
            {"job_id": "OUT-002", "status": "In Progress"},
        ])
        children = app.tree.get_children()
        app.tree.selection_set(children[0])  # Select OUT-001

        # Re-render with updated status for OUT-001
        app._show_results([
            {"job_id": "OUT-001", "status": "Completed"},
            {"job_id": "OUT-002", "status": "In Progress"},
        ])
        new_sel = app.tree.selection()
        self.assertEqual(len(new_sel), 1)
        self.assertEqual(app.tree.item(new_sel[0], "values"), ("OUT-001", "", "Completed", "▶ Start"))

    def test_poll_updates_when_status_changes_without_id_change(self):
        import tempfile
        from pathlib import Path
        from website_data_grabber import _write_results
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "res.json"
            app = WebsiteDataGrabberApp(self.root, config_store=None)
            app.result_path = target
            app.records = [{"job_id": "OUT-001", "status": "Pending"}]
            app.job_ids = ["OUT-001"]

            # Write updated status for same job ID
            _write_results(target, ["OUT-001"], records=[{"job_id": "OUT-001", "status": "In Progress"}])
            app._poll_internal_browser_results()

            self.assertEqual(app.records[0]["status"], "In Progress")
            self.assertIn("1 In Progress", app.status.get())

    def test_treeview_has_client_column(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        self.assertEqual(app.tree["columns"], ("job_id", "client", "status", "action"))
        self.assertEqual(app.tree.heading("client")["text"], "Client")
        self.assertEqual(app.tree.heading("job_id")["text"], "Job ID")
        self.assertEqual(app.tree.heading("status")["text"], "Reconciliation Status")
        self.assertEqual(app.tree.heading("action")["text"], "Action")

    def test_export_csv_includes_client_column_when_present(self):
        import csv
        import tempfile
        from pathlib import Path

        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.records = [
            {"job_id": "OUT_0000007024", "client": "GAMMA", "status": "In Progress"},
            {"job_id": "OUT_0000006969", "client": "ACME", "status": "Pending"},
        ]
        app.job_ids = ["OUT_0000007024", "OUT_0000006969"]

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
            tmp_path = Path(tmp.name)

        try:
            with patch("website_data_grabber.filedialog.asksaveasfilename", return_value=str(tmp_path)):
                app.export_csv()

            with tmp_path.open(encoding="utf-8-sig") as f:
                reader = list(csv.reader(f))
            self.assertEqual(reader[0], ["Job ID", "Client", "Reconciliation Status"])
            self.assertEqual(reader[1], ["OUT_0000007024", "GAMMA", "In Progress"])
            self.assertEqual(reader[2], ["OUT_0000006969", "ACME", "Pending"])
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_status_tags_coloring_in_treeview(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        in_prog = app.tree.tag_configure("in_progress")
        self.assertEqual(in_prog["background"], "#fef9c3")
        self.assertEqual(in_prog["foreground"], "#b45309")

        pending = app.tree.tag_configure("pending")
        self.assertEqual(pending["background"], "#fee2e2")
        self.assertEqual(pending["foreground"], "#b91c1c")

        completed = app.tree.tag_configure("completed")
        self.assertEqual(completed["background"], "#dcfce7")
        self.assertEqual(completed["foreground"], "#15803d")

    def test_show_results_assigns_status_tags(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        records = [
            {"job_id": "OUT-1", "client": "GAMMA", "status": "In Progress"},
            {"job_id": "OUT-2", "client": "ACME", "status": "Pending"},
            {"job_id": "OUT-3", "client": "EFL", "status": "Completed"},
        ]
        app._show_results(records)
        children = app.tree.get_children()
        self.assertEqual(app.tree.item(children[0], "tags"), ("in_progress",))
        self.assertEqual(app.tree.item(children[1], "tags"), ("pending",))
        self.assertEqual(app.tree.item(children[2], "tags"), ("completed",))


class WebsiteDataGrabberJobStartedCallbackTests(unittest.TestCase):
    """Tests for the on_job_started callback bridge."""

    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        self.addCleanup(self.root.destroy)

    def _make_app_with_running_browser(self, callback=None):
        from website_data_grabber import _command_file
        app = WebsiteDataGrabberApp(self.root, config_store=None, on_job_started=callback)
        # Simulate a running browser process so start_selected_job reaches the dispatch
        mock_proc = Mock()
        mock_proc.poll.return_value = None
        app.browser_process = mock_proc
        return app

    def test_on_job_started_callback_invoked_with_job_id(self):
        """Callback is called with the selected job ID when browser is running."""
        from website_data_grabber import _command_file
        fired = []
        app = self._make_app_with_running_browser(callback=lambda jid: fired.append(jid))
        app._show_results([{"job_id": "OUT_0000007024", "status": "Pending"}])
        children = app.tree.get_children()
        app.tree.selection_set(children[0])

        try:
            app.start_selected_job()
        finally:
            _command_file().unlink(missing_ok=True)

        self.assertEqual(fired, ["OUT_0000007024"])

    def test_on_job_started_not_called_when_no_selection(self):
        """Callback must not fire when no row is selected."""
        fired = []
        app = self._make_app_with_running_browser(callback=lambda jid: fired.append(jid))
        app.tree.selection_set()  # clear selection
        with patch("website_data_grabber.messagebox.showinfo"):
            app.start_selected_job()
        self.assertEqual(fired, [])

    def test_on_job_started_callback_error_is_suppressed(self):
        """A raising callback must not propagate exceptions."""
        from website_data_grabber import _command_file
        def bad_callback(jid):
            raise RuntimeError("boom")

        app = self._make_app_with_running_browser(callback=bad_callback)
        app._show_results([{"job_id": "OUT_0000007024", "status": "Pending"}])
        children = app.tree.get_children()
        app.tree.selection_set(children[0])

        try:
            app.start_selected_job()  # must not raise
        finally:
            _command_file().unlink(missing_ok=True)

    def test_no_callback_does_not_raise(self):
        """app with no on_job_started works silently."""
        from website_data_grabber import _command_file
        app = self._make_app_with_running_browser(callback=None)
        app._show_results([{"job_id": "OUT_0000007024", "status": "Pending"}])
        children = app.tree.get_children()
        app.tree.selection_set(children[0])

        try:
            app.start_selected_job()  # must not raise
        finally:
            _command_file().unlink(missing_ok=True)


class WebsiteDataGrabberRestartTests(unittest.TestCase):
    """Tests for restart_browser button and method."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_restart_button_is_present(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        self.assertTrue(hasattr(app, "restart_button"))
        self.assertEqual(app.restart_button.cget("text"), "🔄 Restart Browser")

    def test_restart_browser_closes_active_browser_and_triggers_start(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        mock_process = Mock()
        mock_process.poll.return_value = None
        app.browser_process = mock_process
        app.browser_hwnd = 12345
        app._browser_embed_attempts = 10

        with patch.object(self.root, "after") as mock_after, patch.object(app, "start") as mock_start:
            app.restart_browser()
            # close_browser should have terminated the process
            mock_process.terminate.assert_called_once()
            self.assertIsNone(app.browser_process)
            self.assertIsNone(app.browser_hwnd)
            self.assertEqual(app._browser_embed_attempts, 0)
            self.assertEqual(app.status.get(), "Restarting internal browser...")

            # Verify self.root.after was called to schedule self.start
            mock_after.assert_called_once()
            args, _ = mock_after.call_args
            self.assertEqual(args[0], 150)
            self.assertEqual(args[1], app.start)

            # Invoke the scheduled callback directly
            args[1]()
            mock_start.assert_called_once()
