"""Kullanıcıya ait özetleri ve isteğe bağlı şifreli kaynakları saklar."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import DB_PATH
from security import decrypt_source, encrypt_source


def _utc_now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(summaries)")}


def init_db(db_path: Path | None = None) -> None:
    with connection(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'local',
                original_text TEXT,
                encrypted_source BLOB,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                source_expires_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS summary_jobs (
                job_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL,
                summary TEXT,
                evidence TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                encrypted_request BLOB,
                worker_id TEXT,
                lease_expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON summary_jobs(status, created_at)"
        )
        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(summary_jobs)")}
        if "lease_expires_at" not in job_columns:
            conn.execute("ALTER TABLE summary_jobs ADD COLUMN lease_expires_at TEXT")
        existing = _columns(conn)
        additions = {
            "user_id": "TEXT NOT NULL DEFAULT 'local'",
            "encrypted_source": "BLOB",
            "source_expires_at": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE summaries ADD COLUMN {name} {declaration}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summaries_user_created "
            "ON summaries(user_id, created_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                email_verified INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL DEFAULT 'user',
                disabled INTEGER NOT NULL DEFAULT 0,
                token_version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        user_additions = {
            "email_verified": "INTEGER NOT NULL DEFAULT 1",
            "role": "TEXT NOT NULL DEFAULT 'user'",
            "disabled": "INTEGER NOT NULL DEFAULT 0",
            "token_version": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, declaration in user_additions.items():
            if name not in user_columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {declaration}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                purpose TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_account_tokens_lookup "
            "ON account_tokens(token_hash, purpose, expires_at)"
        )

    migrate_legacy_plaintext_sources(db_path)
    purge_expired_sources(db_path)


def migrate_legacy_plaintext_sources(db_path: Path | None = None) -> int:
    """Eski açık metinleri şifreler; 30 gün sonra otomatik silinecek hale getirir."""
    migrated = 0
    expires_at = (_utc_now() + timedelta(days=30)).isoformat()
    with connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, original_text FROM summaries
            WHERE original_text IS NOT NULL AND original_text != ''
              AND encrypted_source IS NULL
            """
        ).fetchall()
        for row in rows:
            conn.execute(
                """
                UPDATE summaries
                SET encrypted_source = ?, original_text = NULL, source_expires_at = ?
                WHERE id = ?
                """,
                (encrypt_source(row["original_text"]), expires_at, row["id"]),
            )
            migrated += 1
    return migrated


def purge_expired_sources(db_path: Path | None = None) -> int:
    now_dt = _utc_now()
    now = now_dt.isoformat()
    with connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE summaries
            SET encrypted_source = NULL, original_text = NULL, source_expires_at = NULL
            WHERE source_expires_at IS NOT NULL AND source_expires_at <= ?
            """,
            (now,),
        )
        return cursor.rowcount


def save_summary(
    user_id: str,
    summary: str,
    source_text: str | None = None,
    retention_days: int | None = None,
    db_path: Path | None = None,
) -> int:
    encrypted_source = None
    expires_at = None
    if source_text:
        if retention_days not in {1, 7, 30}:
            raise ValueError("Kaynak saklama süresi 1, 7 veya 30 gün olmalıdır.")
        encrypted_source = encrypt_source(source_text)
        expires_at = (_utc_now() + timedelta(days=retention_days)).isoformat()

    with connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO summaries
                (user_id, original_text, encrypted_source, summary, created_at, source_expires_at)
            VALUES (?, NULL, ?, ?, ?, ?)
            """,
            (user_id, encrypted_source, summary, _utc_now().isoformat(), expires_at),
        )
        return int(cursor.lastrowid)


def get_history(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[dict]:
    purge_expired_sources(db_path)
    with connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, summary, created_at,
                   encrypted_source IS NOT NULL AS has_source,
                   source_expires_at
            FROM summaries
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, max(1, min(limit, 100)), max(0, offset)),
        ).fetchall()
        return [dict(row) for row in rows]


def get_summary_source(user_id: str, summary_id: int, db_path: Path | None = None) -> str | None:
    purge_expired_sources(db_path)
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT encrypted_source FROM summaries WHERE id = ? AND user_id = ?",
            (summary_id, user_id),
        ).fetchone()
    if row is None or row["encrypted_source"] is None:
        return None
    return decrypt_source(row["encrypted_source"])


def delete_summary(user_id: str, summary_id: int, db_path: Path | None = None) -> bool:
    with connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM summaries WHERE id = ? AND user_id = ?",
            (summary_id, user_id),
        )
        return cursor.rowcount > 0


def clear_history(user_id: str, db_path: Path | None = None) -> int:
    with connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM summaries WHERE user_id = ?", (user_id,))
        return cursor.rowcount


def create_user(
    email: str,
    password_hash: str,
    db_path: Path | None = None,
    *,
    email_verified: bool = False,
    role: str = "user",
) -> int:
    with connection(db_path) as conn:
        try:
            cursor = conn.execute(
                """INSERT INTO users
                   (email, password_hash, email_verified, role, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (email, password_hash, int(email_verified), role, _utc_now().isoformat()),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("Bu e-posta adresi zaten kayıtlı.") from error
        return int(cursor.lastrowid)


def get_user_by_email(email: str, db_path: Path | None = None) -> dict | None:
    with connection(db_path) as conn:
        row = conn.execute(
            """SELECT id, email, password_hash, email_verified, role, disabled,
                      token_version, created_at
               FROM users WHERE email = ?""",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def create_account_token(
    user_id: int, purpose: str, ttl_minutes: int, db_path: Path | None = None
) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = _utc_now()
    with connection(db_path) as conn:
        conn.execute(
            "UPDATE account_tokens SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL",
            (now.isoformat(), user_id, purpose),
        )
        conn.execute(
            """INSERT INTO account_tokens
               (user_id, purpose, token_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                user_id,
                purpose,
                token_hash,
                (now + timedelta(minutes=ttl_minutes)).isoformat(),
                now.isoformat(),
            ),
        )
    return raw_token


def consume_account_token(raw_token: str, purpose: str, db_path: Path | None = None) -> dict | None:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = _utc_now().isoformat()
    with connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT t.id AS token_id, u.* FROM account_tokens t
               JOIN users u ON u.id=t.user_id
               WHERE t.token_hash=? AND t.purpose=? AND t.used_at IS NULL
                 AND t.expires_at > ?""",
            (token_hash, purpose, now),
        ).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE account_tokens SET used_at=? WHERE id=?", (now, row["token_id"]))
        return dict(row)


def mark_email_verified(user_id: int, db_path: Path | None = None) -> None:
    with connection(db_path) as conn:
        conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))


def verify_email_token(raw_token: str, db_path: Path | None = None) -> bool:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = _utc_now().isoformat()
    with connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT id, user_id FROM account_tokens
               WHERE token_hash=? AND purpose='verify_email' AND used_at IS NULL
                 AND expires_at > ?""",
            (token_hash, now),
        ).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE users SET email_verified=1 WHERE id=?", (row["user_id"],))
        conn.execute("UPDATE account_tokens SET used_at=? WHERE id=?", (now, row["id"]))
        return True


def reset_password_with_token(
    raw_token: str, password_hash: str, db_path: Path | None = None
) -> bool:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = _utc_now().isoformat()
    with connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT id, user_id FROM account_tokens
               WHERE token_hash=? AND purpose='reset_password' AND used_at IS NULL
                 AND expires_at > ?""",
            (token_hash, now),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            """UPDATE users SET password_hash=?, token_version=token_version+1
               WHERE id=?""",
            (password_hash, row["user_id"]),
        )
        conn.execute("UPDATE account_tokens SET used_at=? WHERE id=?", (now, row["id"]))
        return True


def update_password(user_id: int, password_hash: str, db_path: Path | None = None) -> None:
    with connection(db_path) as conn:
        conn.execute(
            """UPDATE users SET password_hash=?, token_version=token_version+1
               WHERE id=?""",
            (password_hash, user_id),
        )


def revoke_all_sessions(user_id: int, db_path: Path | None = None) -> None:
    with connection(db_path) as conn:
        conn.execute("UPDATE users SET token_version=token_version+1 WHERE id=?", (user_id,))


def delete_user_account(user_id: int, email: str, db_path: Path | None = None) -> None:
    with connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM summaries WHERE user_id=?", (email,))
        conn.execute("DELETE FROM summary_jobs WHERE user_id=?", (email,))
        conn.execute("DELETE FROM account_tokens WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


def list_users(limit: int = 100, db_path: Path | None = None) -> list[dict]:
    with connection(db_path) as conn:
        rows = conn.execute(
            """SELECT id, email, email_verified, role, disabled, created_at
               FROM users ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


def set_user_disabled(user_id: int, disabled: bool, db_path: Path | None = None) -> bool:
    with connection(db_path) as conn:
        cursor = conn.execute(
            """UPDATE users SET disabled=?, token_version=token_version+1
               WHERE id=?""",
            (int(disabled), user_id),
        )
        return cursor.rowcount > 0


def create_job_record(
    job_id: str,
    user_id: str,
    request_payload: str,
    queue_limit: int,
    db_path: Path | None = None,
) -> None:
    now = _utc_now().isoformat()
    with connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT COUNT(*) FROM summary_jobs WHERE status IN ('queued', 'running')"
        ).fetchone()[0]
        if active >= queue_limit:
            raise OverflowError("Özetleme kuyruğu dolu.")
        conn.execute(
            """
            INSERT INTO summary_jobs
                (job_id, user_id, status, progress, message, encrypted_request,
                 created_at, updated_at)
            VALUES (?, ?, 'queued', 0, 'İş kuyruğa alındı.', ?, ?, ?)
            """,
            (job_id, user_id, encrypt_source(request_payload), now, now),
        )


def claim_next_job(worker_id: str, db_path: Path | None = None) -> tuple[str, str] | None:
    """Sıradaki işi atomik sahiplenir; aynı SQLite'ı kullanan süreçler çakışmaz."""
    now_dt = _utc_now()
    now = now_dt.isoformat()
    lease_expires = (now_dt + timedelta(minutes=2)).isoformat()
    with connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT job_id, encrypted_request FROM summary_jobs
            WHERE cancel_requested = 0 AND (
                status = 'queued' OR
                (status = 'running' AND lease_expires_at <= ?)
            )
            ORDER BY created_at LIMIT 1
            """,
            (now,),
        ).fetchone()
        if row is None:
            return None
        changed = conn.execute(
            """
            UPDATE summary_jobs SET status='running', progress=10,
                message='Belge özetleniyor.', worker_id=?, lease_expires_at=?, updated_at=?
            WHERE job_id=? AND cancel_requested=0 AND (
                status='queued' OR (status='running' AND lease_expires_at <= ?)
            )
            """,
            (worker_id, lease_expires, now, row["job_id"], now),
        ).rowcount
        if not changed:
            return None
        return row["job_id"], decrypt_source(row["encrypted_request"])


def recover_interrupted_jobs(db_path: Path | None = None) -> int:
    """Worker lease süresi dolmuş yarım işleri yeniden kuyruğa döndürür."""
    now = _utc_now().isoformat()
    with connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE summary_jobs SET status='queued', progress=0,
                message='Sunucu yeniden başlatıldı; iş tekrar kuyruğa alındı.', worker_id=NULL,
                lease_expires_at=NULL, updated_at=?
            WHERE status='running' AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
            """,
            (now, now),
        )
        return cursor.rowcount


def update_job_record(job_id: str, db_path: Path | None = None, **values) -> None:
    allowed = {
        "status",
        "progress",
        "message",
        "summary",
        "evidence",
        "error",
        "cancel_requested",
        "worker_id",
        "encrypted_request",
        "lease_expires_at",
    }
    values = {key: value for key, value in values.items() if key in allowed}
    if "evidence" in values and not isinstance(values["evidence"], str):
        values["evidence"] = json.dumps(values["evidence"], ensure_ascii=False)
    if not values:
        return
    now = _utc_now()
    values["updated_at"] = now.isoformat()
    if values.get("status") == "running" or (
        "progress" in values and values.get("status") not in {"succeeded", "failed", "cancelled"}
    ):
        values["lease_expires_at"] = (now + timedelta(minutes=2)).isoformat()
    assignments = ", ".join(f"{name} = ?" for name in values)
    with connection(db_path) as conn:
        conn.execute(
            f"UPDATE summary_jobs SET {assignments} WHERE job_id = ?",
            (*values.values(), job_id),
        )


def heartbeat_job(job_id: str, worker_id: str, db_path: Path | None = None) -> bool:
    now = _utc_now()
    with connection(db_path) as conn:
        cursor = conn.execute(
            """UPDATE summary_jobs SET lease_expires_at=?, updated_at=?
               WHERE job_id=? AND worker_id=? AND status='running'""",
            ((now + timedelta(minutes=2)).isoformat(), now.isoformat(), job_id, worker_id),
        )
        return cursor.rowcount > 0


def get_job_record(user_id: str, job_id: str, db_path: Path | None = None) -> dict | None:
    with connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT job_id, status, progress, message, summary, evidence, error
            FROM summary_jobs WHERE job_id=? AND user_id=?
            """,
            (job_id, user_id),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["evidence"] = json.loads(data["evidence"] or "[]")
    return data


def job_cancel_requested(job_id: str, db_path: Path | None = None) -> bool:
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT cancel_requested FROM summary_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    return bool(row and row["cancel_requested"])


def cancel_job_record(user_id: str, job_id: str, db_path: Path | None = None) -> bool:
    now = _utc_now().isoformat()
    with connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM summary_jobs WHERE job_id=? AND user_id=?",
            (job_id, user_id),
        ).fetchone()
        if row is None or row["status"] in {"succeeded", "failed", "cancelled"}:
            return False
        if row["status"] == "queued":
            conn.execute(
                """UPDATE summary_jobs SET status='cancelled', progress=100,
                   message='İşlem başlamadan iptal edildi.', cancel_requested=1,
                   encrypted_request=NULL, updated_at=? WHERE job_id=?""",
                (now, job_id),
            )
        else:
            conn.execute(
                """UPDATE summary_jobs SET cancel_requested=1,
                   message='İptal istendi; mevcut yapay zekâ çağrısı bitince duracak.',
                   updated_at=? WHERE job_id=?""",
                (now, job_id),
            )
        return True


def purge_old_jobs(hours: int, db_path: Path | None = None) -> int:
    cutoff = (_utc_now() - timedelta(hours=hours)).isoformat()
    with connection(db_path) as conn:
        cursor = conn.execute(
            """DELETE FROM summary_jobs WHERE updated_at < ?
               AND status IN ('succeeded', 'failed', 'cancelled')""",
            (cutoff,),
        )
        return cursor.rowcount


init_db()
