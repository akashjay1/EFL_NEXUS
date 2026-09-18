import unittest
from unittest.mock import Mock, patch
import tempfile
import tkinter as tk

from website_data_grabber import (
    DEFAULT_LOGIN_URL,
    WebsiteDataGrabberApp,
    extract_jobs_with_status,
    job_ids_from_rows,
    normalize_reconciliation_status,
    parse_refresh_seconds,
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


class WebsiteDataGrabberAutoRefreshTests(unittest.TestCase):
    """Tests for changing auto refresh time in Website Data Grabber."""

    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        self.addCleanup(self.root.destroy)

    def test_parse_refresh_seconds(self):
        self.assertEqual(parse_refresh_seconds("5s"), 5)
        self.assertEqual(parse_refresh_seconds("15 sec"), 15)
        self.assertEqual(parse_refresh_seconds("60"), 60)
        self.assertEqual(parse_refresh_seconds("Off"), 0)
        self.assertEqual(parse_refresh_seconds("manual"), 0)
        self.assertEqual(parse_refresh_seconds("disabled"), 0)
        self.assertEqual(parse_refresh_seconds("0"), 0)
        self.assertEqual(parse_refresh_seconds(None, default=5), 5)
        self.assertEqual(parse_refresh_seconds("", default=10), 10)
        self.assertEqual(parse_refresh_seconds(30), 30)

    def test_set_refresh_interval_updates_ui_badge_and_combobox(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        self.assertTrue(hasattr(app, "refresh_combo"))
        self.assertTrue(hasattr(app, "auto_refresh_badge"))

        # Set to 15 seconds
        app.set_refresh_interval("15s", save=False)
        self.assertEqual(app.refresh_seconds.get(), "15")
        self.assertEqual(app.refresh_combo.get(), "15s")
        self.assertIn("15s", app.auto_refresh_badge.cget("text"))

        # Set to Off
        app.set_refresh_interval("Off", save=False)
        self.assertEqual(app.refresh_seconds.get(), "0")
        self.assertEqual(app.refresh_combo.get(), "Off")
        self.assertIn("Off", app.auto_refresh_badge.cget("text"))

    def test_set_refresh_interval_dispatches_ipc_command_when_browser_running(self):
        from website_data_grabber import _command_file
        import json
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        mock_proc = Mock()
        mock_proc.poll.return_value = None
        app.browser_process = mock_proc

        cmd_file = _command_file()
        try:
            app.set_refresh_interval("30s", save=False)
            self.assertTrue(cmd_file.exists())
            payload = json.loads(cmd_file.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("action"), "set_refresh_interval")
            self.assertEqual(payload.get("seconds"), 30)
        finally:
            cmd_file.unlink(missing_ok=True)

    def test_set_refresh_interval_persists_to_config_store(self):
        mock_store = Mock()
        mock_store.config = {}
        mock_store.save.return_value = True

        app = WebsiteDataGrabberApp(self.root, config_store=mock_store)
        app.set_refresh_interval("10s", save=True)

        mock_store.save.assert_called_with(data_grabber_refresh_seconds="10")

    def test_set_connection_settings_syncs_refresh_seconds(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.set_connection_settings(
            login_url="https://active.efl3plofc.com/login",
            username="user@efl.com",
            password="pass",
            reconciliation_url="https://active.efl3plofc.com/clerk-dashboard",
            refresh_seconds="20",
        )
        self.assertEqual(app.refresh_seconds.get(), "20")
        self.assertEqual(app.refresh_combo.get(), "20s")
        self.assertIn("20s", app.auto_refresh_badge.cget("text"))

    @patch("website_data_grabber._save_password")
    def test_main_app_save_data_grabber_settings_persists_refresh_seconds(self, mock_save_pwd):
        from main_app import MainApp
        with patch.object(MainApp, "__init__", lambda self, *args, **kwargs: None):
            app = MainApp()
            app.root = self.root
            mock_store = Mock()
            mock_store.save.return_value = True
            app.config_store = mock_store
            app.grabber_login_url_entry = Mock(get=Mock(return_value="https://active.efl3plofc.com/login"))
            app.grabber_user_entry = Mock(get=Mock(return_value="user@efl.com"))
            app.grabber_pass_entry = Mock(get=Mock(return_value="pass123"))
            app.grabber_reconciliation_url_entry = Mock(get=Mock(return_value="https://active.efl3plofc.com/clerk-dashboard"))
            app.grabber_refresh_seconds_entry = Mock(get=Mock(return_value="15"))
            app.grabber_status_pill = Mock()
            app.grabber_msg_lbl = Mock()
            mock_tool6 = Mock()
            app.tool6_app = mock_tool6

            app._save_data_grabber_settings()

            mock_store.save.assert_called_once_with(
                data_grabber_login_url="https://active.efl3plofc.com/login",
                data_grabber_user="user@efl.com",
                data_grabber_reconciliation_url="https://active.efl3plofc.com/clerk-dashboard",
                data_grabber_refresh_seconds="15",
                data_grabber_sound_enabled=True,
                data_grabber_sound_path="",
            )
            mock_tool6.set_connection_settings.assert_called_once_with(
                "https://active.efl3plofc.com/login",
                "user@efl.com",
                "pass123",
                "https://active.efl3plofc.com/clerk-dashboard",
                "15",
                True,
                "",
            )


class WebsiteDataGrabberSoundNotificationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk not available: {exc}")
        self.addCleanup(self.root.destroy)

    @patch("website_data_grabber.play_notification_sound")
    def test_triggers_sound_when_new_pending_job_appears(self, mock_play_sound):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        records = [
            {"job_id": "JOB-101", "status": "Pending"},
            {"job_id": "JOB-102", "status": "In Progress"},
        ]
        app._show_results(records)

        mock_play_sound.assert_called_once()
        self.assertEqual(app._seen_pending_ids, {"job-101"})

    @patch("website_data_grabber.play_notification_sound")
    def test_does_not_retrigger_sound_on_subsequent_refresh_with_same_pending_job(self, mock_play_sound):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        records = [{"job_id": "JOB-101", "status": "Pending"}]

        # Initial detection plays sound
        app._show_results(records)
        self.assertEqual(mock_play_sound.call_count, 1)

        # Refresh cycle with same pending job should NOT play sound again
        app._show_results(records)
        self.assertEqual(mock_play_sound.call_count, 1)

    @patch("website_data_grabber.play_notification_sound")
    def test_triggers_sound_when_additional_pending_job_arrives(self, mock_play_sound):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        # First batch
        app._show_results([{"job_id": "JOB-101", "status": "Pending"}])
        self.assertEqual(mock_play_sound.call_count, 1)

        # Second batch with a new pending job
        app._show_results([
            {"job_id": "JOB-101", "status": "Pending"},
            {"job_id": "JOB-202", "status": "Pending"},
        ])
        self.assertEqual(mock_play_sound.call_count, 2)
        self.assertEqual(app._seen_pending_ids, {"job-101", "job-202"})

    @patch("website_data_grabber.play_notification_sound")
    def test_respects_sound_disabled(self, mock_play_sound):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.set_sound_enabled(False, save=False)
        self.assertFalse(app.sound_enabled.get())

        app._show_results([{"job_id": "JOB-999", "status": "Pending"}])
        mock_play_sound.assert_not_called()

    def test_toggle_sound_switches_state_and_updates_ui(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        self.assertTrue(app.sound_enabled.get())
        self.assertIn("On", app.sound_button.cget("text"))

        app.toggle_sound()
        self.assertFalse(app.sound_enabled.get())
        self.assertIn("Off", app.sound_button.cget("text"))

        app.toggle_sound()
        self.assertTrue(app.sound_enabled.get())
        self.assertIn("On", app.sound_button.cget("text"))

    @patch("threading.Thread")
    def test_play_notification_sound_spawns_daemon_thread(self, mock_thread):
        from website_data_grabber import play_notification_sound
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance

        result = play_notification_sound()
        self.assertTrue(result)
        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()


class WebsiteDataGrabberCreateGatepassTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk not available: {exc}")
        self.addCleanup(self.root.destroy)

    def test_extracts_all_gatepass_columns(self):
        headers = ["WH", "CLIENT", "JOB ID", "JOB TYPE", "VEHICLE", "GATE PASS", "SEAL NUMBER", "DELIVERY LOCATION", "STATUS"]
        rows = [
            ["EGDC", "GAMMA", "OUT_0000007024", "OUTBOUND", "V-101", "GP-999", "SL-888", "Colombo Hub", "Pending"],
            ["ESKD", "TLP", "IN_0000004138", "INBOUND", "V-202", "GP-111", "", "", "Pending"],
        ]
        records = extract_jobs_with_status(headers, rows, include_details=True)
        self.assertEqual(len(records), 2)
        r1 = records[0]
        self.assertEqual(r1["job_id"], "OUT_0000007024")
        self.assertEqual(r1["client"], "GAMMA")
        self.assertEqual(r1["warehouse"], "EGDC")
        self.assertEqual(r1["gatepass"], "GP-999")
        self.assertEqual(r1["seal"], "SL-888")
        self.assertEqual(r1["delivery_location"], "Colombo Hub")

        r2 = records[1]
        self.assertEqual(r2["job_id"], "IN_0000004138")
        self.assertEqual(r2["client"], "TLP")
        self.assertEqual(r2["warehouse"], "ESKD")
        self.assertEqual(r2["gatepass"], "GP-111")

    def test_create_gatepass_button_styling(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        self.assertTrue(hasattr(app, "create_gatepass_btn"))
        self.assertEqual(app.create_gatepass_btn.cget("text"), "Create Gatepass")
        self.assertEqual(app.create_gatepass_btn.cget("bg"), "#dc2626")
        self.assertEqual(app.create_gatepass_btn.cget("fg"), "#ffffff")

    def test_create_gatepass_selected_job_calls_callback(self):
        callback_mock = Mock()
        app = WebsiteDataGrabberApp(self.root, config_store=None, on_create_gatepass=callback_mock)
        test_records = [{
            "job_id": "OUT_0000007024",
            "client": "GAMMA",
            "status": "Pending",
            "warehouse": "EGDC",
            "gatepass": "GP-999",
            "seal": "SL-888",
            "delivery_location": "Colombo Hub",
        }]
        app._show_results(test_records)
        # Select first row in tree
        children = app.tree.get_children()
        self.assertTrue(len(children) > 0)
        app.tree.selection_set(children[0])

        app.create_gatepass_selected_job()
        callback_mock.assert_called_once_with(test_records[0])

    def test_korber_prefill_gdn_sets_all_five_fields(self):
        from korber_tool import KorberApp
        lane_frame = tk.Frame(self.root)
        lane = KorberApp(self.root, container=lane_frame, standalone=False, profile_name="test_lane")
        lane.prefill_gdn(
            warehouse="EGDC",
            client="GAMMA",
            gatepass="GP-999",
            delivery_location="Colombo Hub",
            seal="SL-888",
        )
        self.assertEqual(lane.notebook.index("current"), 0)
        self.assertEqual(lane.warehouse_entry.get(), "EGDC")
        self.assertEqual(lane.client_entry.get(), "GAMMA")
        self.assertEqual(lane.gatepass_entry.get(), "GP-999")
        self.assertEqual(lane.delivery_entry.get(), "Colombo Hub")
        self.assertEqual(lane.seal_entry.get(), "SL-888")

    def test_korber_prefill_grn_sets_two_fields(self):
        from korber_tool import KorberApp
        lane_frame = tk.Frame(self.root)
        lane = KorberApp(self.root, container=lane_frame, standalone=False, profile_name="test_lane")
        lane.prefill_grn(
            warehouse="ESKD",
            gatepass="GP-111",
        )
        self.assertEqual(lane.notebook.index("current"), 1)
        self.assertEqual(lane.grn_warehouse_entry.get(), "ESKD")
        self.assertEqual(lane.grn_gatepass_entry.get(), "GP-111")

    def test_main_app_create_gatepass_routing_out(self):
        from main_app import MainApp
        with patch.object(MainApp, "__init__", lambda self, *args, **kwargs: None):
            app = MainApp()
            app.root = self.root
            mock_lane = Mock()
            app.tool1_lanes = {"a": mock_lane}
            app._ensure_tool1 = Mock()
            app.show_page = Mock()

            app._create_gatepass_for_job({
                "job_id": "OUT_0000007024",
                "client": "GAMMA",
                "warehouse": "EGDC",
                "gatepass": "GP-999",
                "seal": "SL-888",
                "delivery_location": "Colombo Hub",
            })
            # Process after callback
            self.root.update()

            mock_lane.prefill_gdn.assert_called_once_with(
                warehouse="EGDC",
                client="GAMMA",
                gatepass="GP-999",
                delivery_location="Colombo Hub",
                seal="SL-888",
            )
            app.show_page.assert_called_once_with("tool1")

    def test_main_app_create_gatepass_routing_in(self):
        from main_app import MainApp
        with patch.object(MainApp, "__init__", lambda self, *args, **kwargs: None):
            app = MainApp()
            app.root = self.root
            mock_lane = Mock()
            app.tool1_lanes = {"a": mock_lane}
            app._ensure_tool1 = Mock()
            app.show_page = Mock()

            app._create_gatepass_for_job({
                "job_id": "IN_0000004138",
                "warehouse": "ESKD",
                "gatepass": "GP-111",
            })
            self.root.update()

            mock_lane.prefill_grn.assert_called_once_with(
                warehouse="ESKD",
                gatepass="GP-111",
            )
            app.show_page.assert_called_once_with("tool1")

    def test_korber_prefill_gdn_defaults_missing_delivery_and_seal_to_na(self):
        from korber_tool import KorberApp
        lane_frame = tk.Frame(self.root)
        lane = KorberApp(self.root, container=lane_frame, standalone=False, profile_name="test_lane")
        lane.prefill_gdn(
            warehouse="EGDC",
            client="GAMMA",
            gatepass="GP-999",
            delivery_location="",
            seal="-",
        )
        self.assertEqual(lane.delivery_entry.get(), "N/A")
        self.assertEqual(lane.seal_entry.get(), "N/A")

    def test_main_app_create_gatepass_defaults_missing_fields_to_na(self):
        from main_app import MainApp
        with patch.object(MainApp, "__init__", lambda self, *args, **kwargs: None):
            app = MainApp()
            app.root = self.root
            mock_lane = Mock()
            app.tool1_lanes = {"a": mock_lane}
            app._ensure_tool1 = Mock()
            app.show_page = Mock()

            app._create_gatepass_for_job({
                "job_id": "OUT_0000007024",
                "client": "GAMMA",
                "warehouse": "EGDC",
                "gatepass": "GP-999",
                "seal": "",
                "delivery_location": "-",
            })
            self.root.update()

            mock_lane.prefill_gdn.assert_called_once_with(
                warehouse="EGDC",
                client="GAMMA",
                gatepass="GP-999",
                delivery_location="N/A",
                seal="N/A",
            )

    def test_website_data_grabber_create_gatepass_defaults_missing_fields_to_na(self):
        callback_mock = Mock()
        app = WebsiteDataGrabberApp(self.root, standalone=True, on_create_gatepass=callback_mock)
        test_records = [
            {"job_id": "OUT_0000008888", "client": "CLIENT_X", "status": "Pending", "warehouse": "EGDC", "gatepass": "GP-123", "seal": "", "delivery_location": ""},
        ]
        app._show_results(test_records)
        children = app.tree.get_children()
        self.assertTrue(len(children) > 0)
        app.tree.selection_set(children[0])

        app.create_gatepass_selected_job()
        expected = dict(test_records[0])
        expected["seal"] = "N/A"
        expected["delivery_location"] = "N/A"
        callback_mock.assert_called_once_with(expected)


class WebsiteDataGrabberDownloadTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk not available: {exc}")
        self.addCleanup(self.root.destroy)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    def test_get_downloads_folder_returns_valid_path(self):
        from website_data_grabber import get_downloads_folder
        folder = get_downloads_folder()
        self.assertTrue(folder.exists())
        self.assertTrue(folder.is_dir())

    def test_get_unique_download_path_avoids_collisions(self):
        from pathlib import Path
        from website_data_grabber import get_unique_download_path
        target_dir = Path(self.tmp_dir.name)

        p1 = get_unique_download_path("Inventory_By_Gate_Pass.xlsx", folder=target_dir)
        self.assertEqual(p1.name, "Inventory_By_Gate_Pass.xlsx")
        p1.write_text("v1")

        p2 = get_unique_download_path("Inventory_By_Gate_Pass.xlsx", folder=target_dir)
        self.assertEqual(p2.name, "Inventory_By_Gate_Pass (1).xlsx")
        p2.write_text("v2")

        p3 = get_unique_download_path("Inventory_By_Gate_Pass.xlsx", folder=target_dir)
        self.assertEqual(p3.name, "Inventory_By_Gate_Pass (2).xlsx")

    def test_results_bridge_save_downloaded_file_writes_bytes(self):
        import base64
        from pathlib import Path
        from website_data_grabber import ResultsBridge
        test_dir = Path(self.tmp_dir.name)
        cmd_file = test_dir / "cmd.json"
        bridge = ResultsBridge(cmd_file)

        raw_bytes = b"PK\x03\x04test_excel_content"
        b64_str = base64.b64encode(raw_bytes).decode("ascii")

        with patch("website_data_grabber.get_downloads_folder", return_value=test_dir):
            res = bridge.save_downloaded_file({
                "filename": "1789647753_Inventory_By_Gate_Pass (90).xlsx",
                "data": b64_str,
                "url": "https://active.efl3plofc.com/mas-active-new/storage/app/public/uploads/1789647753_Inventory_By_Gate_Pass%20(90).xlsx",
                "job_id": "16697",
            })

        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("filename"), "1789647753_Inventory_By_Gate_Pass (90).xlsx")
        saved_file = test_dir / "1789647753_Inventory_By_Gate_Pass (90).xlsx"
        self.assertTrue(saved_file.exists())
        self.assertEqual(saved_file.read_bytes(), raw_bytes)

    def test_results_bridge_save_downloaded_file_handles_invalid_data(self):
        from pathlib import Path
        from website_data_grabber import ResultsBridge
        test_dir = Path(self.tmp_dir.name)
        bridge = ResultsBridge(test_dir / "cmd.json")

        res = bridge.save_downloaded_file({
            "filename": "bad.xlsx",
            "data": 12345,  # not string or bytes
        })
        self.assertFalse(res.get("success"))
        self.assertIn("Invalid data format", res.get("error", ""))

    def test_results_bridge_save_downloaded_file_writes_ipc_event(self):
        import base64
        import json
        from pathlib import Path
        from website_data_grabber import ResultsBridge
        test_dir = Path(self.tmp_dir.name)
        bridge = ResultsBridge(test_dir / "cmd.json")
        dl_event_file = test_dir / "event.json"

        with patch("website_data_grabber.get_downloads_folder", return_value=test_dir), \
             patch("website_data_grabber._download_event_file", return_value=dl_event_file):
            bridge.save_downloaded_file({
                "filename": "test.xlsx",
                "data": base64.b64encode(b"test").decode("ascii"),
                "job_id": "16697",
            })

        self.assertTrue(dl_event_file.exists())
        event_data = json.loads(dl_event_file.read_text(encoding="utf-8"))
        self.assertEqual(event_data.get("action"), "file_downloaded")
        self.assertEqual(event_data.get("filename"), "test.xlsx")
        self.assertEqual(event_data.get("job_id"), "16697")

    def test_download_files_btn_exists_in_ui(self):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        self.assertTrue(hasattr(app, "download_files_btn"))
        self.assertEqual(app.download_files_btn.cget("text"), "📥 Download Files")
        self.assertEqual(app.download_files_btn.cget("bg"), "#0284c7")

    def test_download_selected_job_files_dispatches_ipc_command(self):
        import json
        from website_data_grabber import _command_file
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        records = [{"job_id": "OUT_0000007024", "status": "In Progress"}]
        app._show_results(records)

        children = app.tree.get_children()
        app.tree.selection_set(children[0])

        mock_proc = Mock()
        mock_proc.poll.return_value = None
        app.browser_process = mock_proc

        cmd_file = _command_file()
        try:
            app.download_selected_job_files()
            self.assertTrue(cmd_file.exists())
            payload = json.loads(cmd_file.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("action"), "download_job_files")
            self.assertEqual(payload.get("job_id"), "OUT_0000007024")
            self.assertIn("Requested file download for Job ID 'OUT_0000007024'", app.status.get())
        finally:
            cmd_file.unlink(missing_ok=True)

    @patch("website_data_grabber.messagebox.showinfo")
    def test_download_selected_job_files_shows_info_when_no_selection(self, mock_info):
        app = WebsiteDataGrabberApp(self.root, config_store=None)
        app.tree.selection_set()
        app.download_selected_job_files()
        mock_info.assert_called_once()

    def test_poll_updates_status_on_download_event(self):
        import json
        from pathlib import Path
        test_dir = Path(self.tmp_dir.name)
        dl_event_file = test_dir / "test_dl.json"
        dl_event_file.write_text(json.dumps({
            "action": "file_downloaded",
            "filename": "1789647753_Inventory_By_Gate_Pass (90).xlsx",
            "time": 9999999999.0,
        }), encoding="utf-8")

        with patch("website_data_grabber._download_event_file", return_value=dl_event_file):
            app = WebsiteDataGrabberApp(self.root, config_store=None)
            app.download_event_path = dl_event_file
            app._last_download_time = 0.0
            app._poll_internal_browser_results()

        self.assertIn("1789647753_Inventory_By_Gate_Pass (90).xlsx", app.status.get())
        self.assertIn("saved to Downloads folder", app.status.get())







