import json
import tempfile
import unittest
from pathlib import Path

from reconciliation_queue import (
    choose_pending_job,
    clear_queue,
    complete_job,
    enqueue_job,
    get_reconciliation_output_folder,
    is_reconciliation_task,
    list_pending_jobs,
    safe_job_folder_name,
)


class ReconciliationQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.queue_file = Path(self.temp_dir.name) / "queue.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_enqueue_persists_metadata_in_fifo_order(self):
        enqueue_job("JOB-2", "GDN Reconciliation:", "alice", queue_file=self.queue_file)
        enqueue_job("JOB-1", "GRN Reconciliation:", "bob", queue_file=self.queue_file)
        jobs = list_pending_jobs(self.queue_file)
        self.assertEqual(["JOB-2", "JOB-1"], [job["job_id"] for job in jobs])
        self.assertEqual("GDN Reconciliation", jobs[0]["task_type"])
        self.assertTrue(jobs[0]["submitted_at"])

    def test_enqueue_deduplicates_job_ids_case_insensitively(self):
        enqueue_job("Job-10", "GDN Reconciliation", "alice", queue_file=self.queue_file)
        enqueue_job("job-10", "GRN Reconciliation", "bob", queue_file=self.queue_file)
        jobs = list_pending_jobs(self.queue_file)
        self.assertEqual(1, len(jobs))
        self.assertEqual("Job-10", jobs[0]["job_id"])

    def test_complete_removes_only_matching_job(self):
        enqueue_job("JOB-1", "GDN Reconciliation", "alice", queue_file=self.queue_file)
        enqueue_job("JOB-2", "GDN Reconciliation", "alice", queue_file=self.queue_file)
        self.assertTrue(complete_job("job-1", self.queue_file))
        self.assertFalse(complete_job("missing", self.queue_file))
        self.assertEqual(["JOB-2"], [job["job_id"] for job in list_pending_jobs(self.queue_file)])

    def test_clear_queue_removes_all_pending_jobs(self):
        enqueue_job("JOB-1", "GDN Reconciliation", "alice", queue_file=self.queue_file)
        enqueue_job("JOB-2", "GRN Reconciliation", "bob", queue_file=self.queue_file)
        self.assertEqual(2, clear_queue(self.queue_file))
        self.assertEqual([], list_pending_jobs(self.queue_file))
        self.assertEqual(0, clear_queue(self.queue_file))

    def test_missing_and_malformed_files_are_treated_as_empty(self):
        self.assertEqual([], list_pending_jobs(self.queue_file))
        self.queue_file.write_text("not json", encoding="utf-8")
        self.assertEqual([], list_pending_jobs(self.queue_file))
        enqueue_job("RECOVERED", "GDN Reconciliation", "alice", queue_file=self.queue_file)
        with self.queue_file.open("r", encoding="utf-8") as handle:
            self.assertEqual("RECOVERED", json.load(handle)["pending"][0]["job_id"])

    def test_safe_job_folder_name_blocks_invalid_and_reserved_names(self):
        self.assertEqual("ABC_123_45", safe_job_folder_name("ABC/123:45"))
        self.assertEqual("job", safe_job_folder_name("..."))
        self.assertEqual("_CON", safe_job_folder_name("CON"))

    def test_only_gdn_and_grn_reconciliation_tasks_are_eligible(self):
        self.assertTrue(is_reconciliation_task("GDN Reconciliation:"))
        self.assertTrue(is_reconciliation_task("grn reconciliation"))
        self.assertFalse(is_reconciliation_task("GDN Creation:"))
        self.assertFalse(is_reconciliation_task("Load Plan or Asn:"))

    def test_output_folder_is_built_below_base_folder(self):
        folder = get_reconciliation_output_folder(Path("C:/Reports"), "JOB/42")
        self.assertEqual(Path("C:/Reports") / "JOB_42", folder)

    def test_oldest_pending_job_is_selected_automatically(self):
        jobs = [{"job_id": "JOB-1"}, {"job_id": "JOB-2"}]
        self.assertEqual("JOB-1", choose_pending_job(jobs))
        self.assertEqual("JOB-2", choose_pending_job(jobs, "job-2"))
        self.assertEqual("JOB-1", choose_pending_job(jobs, "completed-job"))
        self.assertEqual("", choose_pending_job([]))


if __name__ == "__main__":
    unittest.main()
