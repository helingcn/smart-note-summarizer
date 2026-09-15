"""main.py'deki HTTP route'larını, JWT tabanlı auth'u, rate limiter'ı ve
job_manager entegrasyonunu uçtan uca (FastAPI TestClient ile) test eder.
Gemini API'ye gerçek çağrı yapılmaz; summarize_long_text/build_summary_evidence/
answer_question sahtelerle değiştirilir. Kullanıcı kayıtları gerçek ama izole
bir SQLite dosyasında tutulur (üretim veritabanına dokunulmaz)."""

import threading
import time

import database
import job_manager as job_manager_module
import main
import pytest
from auth import RateLimiter
from fastapi.testclient import TestClient

client = TestClient(main.app)


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("api") / "test.db"
    original = database.DB_PATH
    database.DB_PATH = db_path
    database.init_db(db_path)
    try:
        yield
    finally:
        database.DB_PATH = original


@pytest.fixture(autouse=True)
def _permissive_auth_rate_limiter(monkeypatch):
    # auth_rate_limiter (auth.py) e-posta başına çok sıkı (5/5dk); paylaşılan
    # singleton olduğu için testler arasında sızmaması adına her testte taze,
    # bol limitli bir örnekle değiştiriyoruz. Asıl davranışı test eden fonksiyon
    # kendi içinde bunu tekrar, bilinçli olarak dar bir limitle override ediyor.
    monkeypatch.setattr(main, "auth_rate_limiter", RateLimiter(limit=1000, window_seconds=300))


@pytest.fixture(scope="module")
def auth_headers(_isolated_db):
    response = client.post(
        "/auth/register", json={"email": "test@example.com", "password": "test1234"}
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _wait_for_terminal(job_id: str, headers: dict, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{job_id}", headers=headers)
        job = response.json()
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise TimeoutError(f"İş zaman aşımına uğradı: {job_id}")


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_register_rejects_invalid_email():
    response = client.post("/auth/register", json={"email": "gecersiz", "password": "test1234"})
    assert response.status_code == 400


def test_register_rejects_domain_without_tld():
    # Eski elle yazılmış kontrol ("@" in email and len(email) >= 5) bunu kabul
    # ederdi; gerçek RFC uyumlu EmailStr doğrulaması TLD/domain eksikliğini yakalar.
    response = client.post("/auth/register", json={"email": "a@bcde", "password": "test1234"})
    assert response.status_code == 400


def test_register_rejects_short_password():
    response = client.post("/auth/register", json={"email": "kisa@example.com", "password": "123"})
    assert response.status_code == 400


def test_register_duplicate_email_is_rejected(auth_headers):
    response = client.post(
        "/auth/register", json={"email": "test@example.com", "password": "baskasifre1"}
    )
    assert response.status_code == 409


def test_register_rate_limit_blocks_repeated_attempts(monkeypatch):
    monkeypatch.setattr(main, "auth_rate_limiter", RateLimiter(limit=3, window_seconds=60))
    email = "kayit-spam@example.com"
    first = client.post("/auth/register", json={"email": email, "password": "test1234"})
    assert first.status_code == 201
    for _ in range(2):
        response = client.post("/auth/register", json={"email": email, "password": "test1234"})
        assert response.status_code == 409
    blocked = client.post("/auth/register", json={"email": email, "password": "test1234"})
    assert blocked.status_code == 429


def test_register_race_condition_returns_409_not_500(monkeypatch):
    # get_user_by_email'i her zaman None döndürecek şekilde sahteleyerek, iki
    # isteğin ön-kontrolü aynı anda geçtiği yarış senaryosunu simüle ediyoruz;
    # asıl korumanın (UNIQUE kısıtı + create_user'daki try/except) çalıştığını
    # ve bunun temiz bir 409'a çevrildiğini (çirkin bir 500 yerine) doğrular.
    monkeypatch.setattr(main, "get_user_by_email", lambda email: None)
    email = "yaris@example.com"
    first = client.post("/auth/register", json={"email": email, "password": "test1234"})
    assert first.status_code == 201
    second = client.post("/auth/register", json={"email": email, "password": "test1234"})
    assert second.status_code == 409


def test_login_success_returns_token():
    response = client.post(
        "/auth/login", json={"email": "test@example.com", "password": "test1234"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "test@example.com"
    assert body["access_token"]


def test_login_wrong_password_is_rejected():
    response = client.post(
        "/auth/login", json={"email": "test@example.com", "password": "yanlis-sifre"}
    )
    assert response.status_code == 401


def test_login_unknown_email_is_rejected():
    response = client.post(
        "/auth/login", json={"email": "olmayan@example.com", "password": "test1234"}
    )
    assert response.status_code == 401


def test_login_unknown_email_still_hashes_password(monkeypatch):
    # Zamanlama sızıntısını kapatan asıl mekanizma: e-posta bulunamasa bile
    # verify_password (dolayısıyla pahalı PBKDF2 hesaplaması) DUMMY_PASSWORD_HASH
    # ile çağrılıyor mu, gerçek kullanıcı bulunduğundaki ile aynı yol mu izleniyor.
    calls = []
    monkeypatch.setattr(
        main,
        "verify_password",
        lambda password, stored_hash: calls.append(stored_hash) or False,
    )
    response = client.post("/auth/login", json={"email": "hicyok@example.com", "password": "x"})
    assert response.status_code == 401
    assert calls == [main.DUMMY_PASSWORD_HASH]


def test_login_rate_limit_blocks_repeated_attempts(monkeypatch):
    monkeypatch.setattr(main, "auth_rate_limiter", RateLimiter(limit=3, window_seconds=60))
    for _ in range(3):
        response = client.post(
            "/auth/login", json={"email": "kabakuvvet@example.com", "password": "yanlis"}
        )
        assert response.status_code == 401
    blocked = client.post(
        "/auth/login", json={"email": "kabakuvvet@example.com", "password": "yanlis"}
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_forgot_and_reset_password_flow():
    email = "reset-flow@example.com"
    registered = client.post("/auth/register", json={"email": email, "password": "eskisifre1"})
    assert registered.status_code == 201
    forgot = client.post("/auth/forgot-password", json={"email": email})
    assert forgot.status_code == 200
    token = forgot.json()["development_token"]
    assert token
    reset = client.post(
        "/auth/reset-password",
        json={"token": token, "new_password": "yenisifre1"},
    )
    assert reset.status_code == 200
    assert (
        client.post("/auth/login", json={"email": email, "password": "yenisifre1"}).status_code
        == 200
    )
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": token, "new_password": "baskasifre1"},
        ).status_code
        == 400
    )


def test_logout_all_invalidates_existing_token():
    email = "logout-all@example.com"
    registered = client.post("/auth/register", json={"email": email, "password": "test1234"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    assert client.post("/auth/logout-all", headers=headers).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_delete_account_removes_login():
    email = "delete-me@example.com"
    registered = client.post("/auth/register", json={"email": email, "password": "test1234"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    deleted = client.request(
        "DELETE", "/auth/account", headers=headers, json={"password": "test1234"}
    )
    assert deleted.status_code == 200
    assert (
        client.post("/auth/login", json={"email": email, "password": "test1234"}).status_code == 401
    )


def test_me_returns_authenticated_email(auth_headers):
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"email": "test@example.com", "role": "user"}


def test_missing_token_is_rejected():
    response = client.post("/jobs", json={"text": "merhaba"})
    assert response.status_code == 401


def test_invalid_token_is_rejected():
    response = client.post(
        "/jobs", json={"text": "merhaba"}, headers={"Authorization": "Bearer gecersiz-token"}
    )
    assert response.status_code == 401


def test_empty_text_is_rejected(auth_headers):
    response = client.post("/jobs", json={"text": "   "}, headers=auth_headers)
    assert response.status_code == 400


def test_text_over_limit_is_rejected(auth_headers):
    long_text = "a" * (main.MAX_SUMMARY_INPUT_CHARS + 1)
    response = client.post("/jobs", json={"text": long_text}, headers=auth_headers)
    assert response.status_code == 422


def test_rate_limit_returns_429(auth_headers, monkeypatch):
    monkeypatch.setattr(main, "rate_limiter", RateLimiter(limit=2, window_seconds=60))
    for _ in range(2):
        response = client.get("/history", headers=auth_headers)
        assert response.status_code == 200
    limited = client.get("/history", headers=auth_headers)
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


def test_job_success_returns_summary_and_evidence(auth_headers, monkeypatch):
    monkeypatch.setattr(
        job_manager_module, "summarize_long_text", lambda *a, **k: "### Özet\nTest özeti."
    )
    monkeypatch.setattr(
        job_manager_module,
        "build_summary_evidence",
        lambda summary, text: [
            {
                "claim": "Test özeti.",
                "page": 1,
                "paragraph": 1,
                "quote": "kaynak",
                "support": 90,
                "status": "supported",
            }
        ],
    )
    monkeypatch.setattr(job_manager_module, "save_summary", lambda **k: 1)

    created = client.post("/jobs", json={"text": "kaynak metin"}, headers=auth_headers)
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    job = _wait_for_terminal(job_id, auth_headers)
    assert job["status"] == "succeeded"
    assert job["summary"] == "### Özet\nTest özeti."
    assert job["evidence"][0]["status"] == "supported"
    assert job["error"] is None


def test_job_not_found_returns_404(auth_headers):
    response = client.get("/jobs/olmayan-id", headers=auth_headers)
    assert response.status_code == 404


def test_job_generic_error_is_sanitized(auth_headers, monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("sqlite3.OperationalError: iç dosya yolu /etc/gizli sızmasın")

    monkeypatch.setattr(job_manager_module, "summarize_long_text", _raise)

    created = client.post("/jobs", json={"text": "kaynak metin"}, headers=auth_headers)
    job_id = created.json()["job_id"]

    job = _wait_for_terminal(job_id, auth_headers)
    assert job["status"] == "failed"
    assert job["error"] == "Özetleme sırasında bir hata oluştu."
    assert "gizli" not in job["error"]


def test_job_quota_error_uses_quota_message(auth_headers, monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")

    monkeypatch.setattr(job_manager_module, "summarize_long_text", _raise)

    created = client.post("/jobs", json={"text": "kaynak metin"}, headers=auth_headers)
    job_id = created.json()["job_id"]

    job = _wait_for_terminal(job_id, auth_headers)
    assert job["status"] == "failed"
    assert job["error"] == main.GEMINI_QUOTA_MESSAGE


def test_cancel_running_job_then_completes_as_cancelled(auth_headers, monkeypatch):
    release = threading.Event()

    def _blocking_summarize(*args, **kwargs):
        release.wait(timeout=5)
        return "### Özet\nGeç kalan özet."

    monkeypatch.setattr(job_manager_module, "summarize_long_text", _blocking_summarize)
    monkeypatch.setattr(job_manager_module, "save_summary", lambda **k: 1)

    created = client.post("/jobs", json={"text": "kaynak metin"}, headers=auth_headers)
    job_id = created.json()["job_id"]

    cancel = client.delete(f"/jobs/{job_id}", headers=auth_headers)
    assert cancel.status_code == 200

    release.set()
    job = _wait_for_terminal(job_id, auth_headers)
    assert job["status"] == "cancelled"


def test_cancel_unknown_job_returns_404(auth_headers):
    response = client.delete("/jobs/olmayan-id", headers=auth_headers)
    assert response.status_code == 404


def test_extract_rejects_non_pdf_extension(auth_headers):
    response = client.post(
        "/extract",
        headers=auth_headers,
        files={"file": ("not_a_pdf.txt", b"merhaba", "text/plain")},
    )
    assert response.status_code == 400


def test_extract_rejects_wrong_mime_type(auth_headers):
    response = client.post(
        "/extract",
        headers=auth_headers,
        files={"file": ("dosya.pdf", b"%PDF-1.4 ...", "image/png")},
    )
    assert response.status_code == 400


def test_chat_requires_non_empty_fields(auth_headers):
    response = client.post("/chat", json={"text": "", "question": "soru"}, headers=auth_headers)
    assert response.status_code == 400


def test_chat_rejects_oversized_document(auth_headers):
    response = client.post(
        "/chat",
        json={"text": "x" * 100_001, "question": "soru"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_chat_rejects_oversized_question(auth_headers):
    response = client.post(
        "/chat",
        json={"text": "belge", "question": "x" * 2_001},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_chat_returns_answer_and_sources(auth_headers, monkeypatch):
    monkeypatch.setattr(
        main, "answer_question", lambda text, question: ("Cevap.", ["Sayfa 1: kanıt"])
    )
    response = client.post(
        "/chat", json={"text": "belge metni", "question": "soru"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json() == {"answer": "Cevap.", "sources": ["Sayfa 1: kanıt"]}


def test_history_endpoints_use_wired_database_functions(auth_headers, monkeypatch):
    monkeypatch.setattr(
        main,
        "get_history",
        lambda user_id, limit, offset: [
            {
                "id": 1,
                "summary": "Özet",
                "created_at": "2026-01-01T00:00:00",
                "has_source": False,
                "source_expires_at": None,
            }
        ],
    )
    monkeypatch.setattr(main, "get_summary_source", lambda user_id, item_id: None)
    monkeypatch.setattr(main, "delete_summary", lambda user_id, item_id: False)
    monkeypatch.setattr(main, "clear_history", lambda user_id: 3)

    listed = client.get("/history", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == 1

    missing_source = client.get("/history/1/source", headers=auth_headers)
    assert missing_source.status_code == 404

    missing_delete = client.delete("/history/1", headers=auth_headers)
    assert missing_delete.status_code == 404

    cleared = client.delete("/history", headers=auth_headers)
    assert cleared.status_code == 200
    assert cleared.json() == {"status": "cleared", "deleted": 3}
