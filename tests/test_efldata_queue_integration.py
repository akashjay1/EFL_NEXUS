import unittest
from unittest.mock import Mock, patch

import efldatamanager


class UserDataQueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original_records_cache = efldatamanager._records_cache
        efldatamanager._records_cache = []

    def tearDown(self):
        efldatamanager._records_cache = self.original_records_cache

    @patch("efldatamanager.add_activity_log")
    @patch("efldatamanager._save_local_disk_cache")
    @patch("efldatamanager.enqueue_job")
    @patch("efldatamanager.check_duplicate", return_value=(False, None))
    @patch("efldatamanager.connect_to_sheets")
    def test_successful_reconciliation_submission_is_queued(
        self, connect_to_sheets, _check_duplicate, enqueue_job, _save_cache, _activity_log
    ):
        sheet = Mock()
        connect_to_sheets.return_value = (sheet, "Connected")

        success, _message, _existing_user = efldatamanager.save_to_sheet(
            "GDN Reconciliation:", "JOB-100", "New", "alice"
        )

        self.assertTrue(success)
        sheet.append_row.assert_called_once()
        enqueue_job.assert_called_once_with("JOB-100", "GDN Reconciliation:", "alice")

    @patch("efldatamanager.add_activity_log")
    @patch("efldatamanager._save_local_disk_cache")
    @patch("efldatamanager.enqueue_job")
    @patch("efldatamanager.check_duplicate", return_value=(False, None))
    @patch("efldatamanager.connect_to_sheets")
    def test_unrelated_successful_submission_is_not_queued(
        self, connect_to_sheets, _check_duplicate, enqueue_job, _save_cache, _activity_log
    ):
        connect_to_sheets.return_value = (Mock(), "Connected")

        success, _message, _existing_user = efldatamanager.save_to_sheet(
            "GDN Creation:", "JOB-101", "New", "alice"
        )

        self.assertTrue(success)
        enqueue_job.assert_not_called()

    @patch("efldatamanager.add_activity_log")
    @patch("efldatamanager.enqueue_job")
    @patch("efldatamanager.check_duplicate", return_value=(False, None))
    @patch("efldatamanager.connect_to_sheets")
    def test_failed_sheet_write_is_not_queued(
        self, connect_to_sheets, _check_duplicate, enqueue_job, _activity_log
    ):
        sheet = Mock()
        sheet.append_row.side_effect = RuntimeError("write failed")
        connect_to_sheets.return_value = (sheet, "Connected")

        success, _message, _existing_user = efldatamanager.save_to_sheet(
            "GRN Reconciliation:", "JOB-102", "New", "alice"
        )

        self.assertFalse(success)
        enqueue_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
