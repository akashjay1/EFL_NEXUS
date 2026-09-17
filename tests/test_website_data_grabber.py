from website_data_grabber import DEFAULT_LOGIN_URL, job_ids_from_rows


def test_uses_confirmed_portal_login_url():
    assert DEFAULT_LOGIN_URL == "https://active.efl3plofc.com/login"


def test_extracts_and_deduplicates_job_id_column():
    result = job_ids_from_rows(
        ["Warehouse", "Job ID", "Status"],
        [["A", " JOB-100 ", "Open"], ["B", "job-100", "Closed"], ["C", "JOB-200", "Open"]],
    )
    assert result == ["JOB-100", "JOB-200"]


def test_accepts_exact_custom_column_name():
    result = job_ids_from_rows(["Load Reference", "State"], [["REF-1", "Open"]], "Load Reference")
    assert result == ["REF-1"]


def test_returns_no_values_when_table_has_no_job_column():
    assert job_ids_from_rows(["Order", "State"], [["A1", "Open"]]) == []


def test_filters_to_pending_reconciliation_status_only():
    result = job_ids_from_rows(
        ["Job ID", "Reconciliation Status"],
        [["OUT-1", "Pending"], ["OUT-2", "on Progress"], ["OUT-3", "pending"]],
        required_status="Pending",
    )
    assert result == ["OUT-1", "OUT-3"]
