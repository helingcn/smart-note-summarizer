from pathlib import Path

import database


def test_history_is_user_scoped_and_does_not_return_source(tmp_path: Path):
    db_path = tmp_path / "privacy.db"
    database.init_db(db_path)
    alice_id = database.save_summary(
        "alice", "Alice özeti", "çok gizli kaynak", 1, db_path
    )
    database.save_summary("bob", "Bob özeti", db_path=db_path)

    alice_history = database.get_history("alice", db_path=db_path)

    assert [item["id"] for item in alice_history] == [alice_id]
    assert "original_text" not in alice_history[0]
    assert alice_history[0]["has_source"] == 1
    assert database.get_summary_source("alice", alice_id, db_path) == "çok gizli kaynak"
    assert database.get_summary_source("bob", alice_id, db_path) is None


def test_delete_requires_record_ownership(tmp_path: Path):
    db_path = tmp_path / "ownership.db"
    database.init_db(db_path)
    item_id = database.save_summary("alice", "Özet", db_path=db_path)

    assert database.delete_summary("bob", item_id, db_path) is False
    assert database.delete_summary("alice", item_id, db_path) is True


def test_job_request_is_encrypted_and_claimed_once(tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    database.init_db(db_path)
    payload = '{"text":"çok gizli kuyruk metni","mode":"fast"}'
    database.create_job_record("job-1", "alice", payload, 10, db_path)

    with database.connection(db_path) as conn:
        stored = conn.execute(
            "SELECT encrypted_request FROM summary_jobs WHERE job_id='job-1'"
        ).fetchone()[0]
    assert b"cok gizli" not in stored
    assert database.claim_next_job("worker-a", db_path) == ("job-1", payload)
    assert database.claim_next_job("worker-b", db_path) is None


def test_job_queue_limit_is_enforced(tmp_path: Path):
    db_path = tmp_path / "limited-jobs.db"
    database.init_db(db_path)
    database.create_job_record("job-1", "alice", '{"text":"a"}', 1, db_path)
    import pytest

    with pytest.raises(OverflowError):
        database.create_job_record("job-2", "alice", '{"text":"b"}', 1, db_path)
