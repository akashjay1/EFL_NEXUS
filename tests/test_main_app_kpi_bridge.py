"""Tests for MainApp._prefill_kpi_for_job — the Tool 6 → Tool 4 bridge."""
import unittest
from unittest.mock import Mock, patch

import main_app


class MainAppKPIBridgeTests(unittest.TestCase):
    def _make_main_app(self):
        """Construct a bare MainApp skeleton with only the attributes the bridge needs."""
        app = main_app.MainApp.__new__(main_app.MainApp)
        app.root = Mock()
        app.tool4_app = Mock()
        app.tool4_error = None
        return app

    def test_out_prefix_routes_to_gdn(self):
        app = self._make_main_app()
        app.tool4_app.prefill_reconciliation_job.return_value = True
        app.show_page = Mock()

        scheduled = []
        app.root.after.side_effect = lambda delay, fn: scheduled.append(fn)

        app._prefill_kpi_for_job("OUT_0000007024")
        self.assertEqual(len(scheduled), 1)
        with patch.object(app, "_ensure_tool4"):
            scheduled[0]()

        app.tool4_app.prefill_reconciliation_job.assert_called_once_with(
            "OUT_0000007024", "GDN Reconciliation:"
        )
        app.show_page.assert_called_once_with("tool4")

    def test_in_prefix_routes_to_grn(self):
        app = self._make_main_app()
        app.tool4_app.prefill_reconciliation_job.return_value = True
        app.show_page = Mock()

        scheduled = []
        app.root.after.side_effect = lambda delay, fn: scheduled.append(fn)

        app._prefill_kpi_for_job("IN_0000001234")
        with patch.object(app, "_ensure_tool4"):
            scheduled[0]()

        app.tool4_app.prefill_reconciliation_job.assert_called_once_with(
            "IN_0000001234", "GRN Reconciliation:"
        )
        app.show_page.assert_called_once_with("tool4")

    def test_unknown_prefix_is_noop(self):
        app = self._make_main_app()
        app.tool4_app.prefill_reconciliation_job = Mock()
        app.show_page = Mock()

        scheduled = []
        app.root.after.side_effect = lambda delay, fn: scheduled.append(fn)

        app._prefill_kpi_for_job("JOB_0000001234")

        self.assertEqual(scheduled, [])
        app.tool4_app.prefill_reconciliation_job.assert_not_called()
        app.show_page.assert_not_called()

    def test_prefix_matching_is_case_insensitive(self):
        app = self._make_main_app()
        app.tool4_app.prefill_reconciliation_job.return_value = True
        app.show_page = Mock()

        scheduled = []
        app.root.after.side_effect = lambda delay, fn: scheduled.append(fn)

        app._prefill_kpi_for_job("out_0000007999")
        with patch.object(app, "_ensure_tool4"):
            scheduled[0]()

        app.tool4_app.prefill_reconciliation_job.assert_called_once_with(
            "out_0000007999", "GDN Reconciliation:"
        )

    def test_does_not_navigate_when_prefill_returns_false(self):
        app = self._make_main_app()
        app.tool4_app.prefill_reconciliation_job.return_value = False
        app.show_page = Mock()

        scheduled = []
        app.root.after.side_effect = lambda delay, fn: scheduled.append(fn)

        app._prefill_kpi_for_job("OUT_0000007024")
        with patch.object(app, "_ensure_tool4"):
            scheduled[0]()

        app.show_page.assert_not_called()

    def test_does_not_navigate_when_tool4_is_none(self):
        app = self._make_main_app()
        app.tool4_app = None
        app.show_page = Mock()

        scheduled = []
        app.root.after.side_effect = lambda delay, fn: scheduled.append(fn)

        app._prefill_kpi_for_job("OUT_0000007024")
        with patch.object(app, "_ensure_tool4"):
            scheduled[0]()

        app.show_page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
