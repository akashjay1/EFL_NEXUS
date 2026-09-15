import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import efl_app


class EFLAppQueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = efl_app.EFLApp.__new__(efl_app.EFLApp)
        self.app.user_id = "Akash"
        self.app.user_code = "CSSUN151"
        self.app.gs_manager = Mock(connected=True)
        self.app.selected_date = datetime(2026, 9, 14)
        self.app._show_message = Mock()
        self.app._refresh_all_counts = Mock()

    @patch("efl_app.enqueue_job")
    def test_successful_reconciliation_submission_is_queued(self, enqueue_job):
        self.app.gs_manager.append_row_sheet1.return_value = True

        result = self.app._save_to_sheet1(
            "GDN Reconciliation:", {"job_id": "JOB-100", "job_status": "New"}
        )

        self.assertTrue(result)
        enqueue_job.assert_called_once_with("JOB-100", "GDN Reconciliation:", "Akash")

    @patch("efl_app.enqueue_job")
    def test_failed_sheet_write_is_not_queued(self, enqueue_job):
        self.app.gs_manager.append_row_sheet1.return_value = False

        result = self.app._save_to_sheet1(
            "GRN Reconciliation:", {"job_id": "JOB-101", "job_status": "New"}
        )

        self.assertFalse(result)
        enqueue_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
