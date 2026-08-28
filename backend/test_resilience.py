"""Kalıcılık, eşzamanlılık, limit aşımı ve anahtar davranışı testleri."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import auth
import database
import pytest
import security
from auth import DistributedRateLimiter
from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.requests import Request


def test_interrupted_job_is_requeued_after_restart(tmp_path):
    db_path = tmp_path / "restart.db"
    database.init_db(db_path)
    database.create_job_record("job-1", "alice", '{"text":"belge"}', 10, db_path)
    assert database.claim_next_job("dead-worker", db_path)[0] == "job-1"
    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with database.connection(db_path) as conn:
        conn.execute("UPDATE summary_jobs SET lease_expires_at=? WHERE job_id='job-1'", (expired,))

    assert database.recover_interrupted_jobs(db_path) == 1
    assert database.claim_next_job("new-worker", db_path)[0] == "job-1"


def test_concurrent_sqlite_writes_are_not_lost(tmp_path):
    db_path = tmp_path / "concurrent.db"
    database.init_db(db_path)

    def write(index: int) -> int:
        return database.save_summary("alice", f"özet-{index}", db_path=db_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(write, range(40)))

    assert len(set(ids)) == 40
    assert len(database.get_history("alice", limit=100, db_path=db_path)) == 40


def _request(ip: str) -> Request:
    return Request({"type": "http", "headers": [], "client": (ip, 1234)})


def test_auth_rate_limit_cannot_be_bypassed_with_different_accounts(monkeypatch):
    monkeypatch.setattr(auth, "_redis_client", None)
    limiter = DistributedRateLimiter()
    request = _request("203.0.113.10")
    for index in range(30):
        limiter.check_auth(request, f"user-{index}@example.com", "register")
    with pytest.raises(HTTPException) as blocked:
        limiter.check_auth(request, "new-address@example.com", "register")
    assert blocked.value.status_code == 429


def test_encrypted_data_fails_closed_when_key_is_lost(monkeypatch):
    original = security._fernet
    encrypted = security.encrypt_source("kritik belge")
    monkeypatch.setattr(security, "_fernet", Fernet(Fernet.generate_key()))
    with pytest.raises(ValueError, match="şifresi çözülemedi"):
        security.decrypt_source(encrypted)
    monkeypatch.setattr(security, "_fernet", original)
    assert security.decrypt_source(encrypted) == "kritik belge"
