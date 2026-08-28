"""app.py için Streamlit AppTest entegrasyon testleri.

Gerçek HTTP yapılmaz: `APIClient` ve tarayıcı `LocalStorage` bileşeni
MagicMock ile değiştirilir. Amaç, app.py'deki akış mantığını (giriş, özet
oluşturma, geçmişten "Aç", şifre sıfırlama) refactor'lara karşı sabitlemek.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).parent / "app.py")
TOKEN = "test-access-token"


@pytest.fixture
def env():
    """API ve LocalStorage sahtelerini kurar; her testte cache temizler."""
    api = MagicMock(name="APIClient")
    storage = MagicMock(name="LocalStorage")
    storage.getItem.return_value = None
    st.cache_data.clear()
    with (
        patch("api_client.APIClient", return_value=api),
        patch("streamlit_local_storage.LocalStorage", return_value=storage),
    ):
        yield api, storage
    st.cache_data.clear()


def _authed(at: AppTest) -> AppTest:
    at.session_state["access_token"] = TOKEN
    at.session_state["user_email"] = "user@example.com"
    at.session_state["user_role"] = "user"
    return at


# --- Giriş akışı -----------------------------------------------------------


def test_login_form_shown_when_unauthenticated(env):
    api, _ = env
    api.get_json.return_value = []
    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    assert not at.exception
    labels = [w.label for w in at.text_input]
    assert "E-posta" in labels
    assert any("Şifre" in label for label in labels)


def test_successful_login_stores_token(env):
    api, storage = env
    api.post_json.return_value = {
        "access_token": TOKEN,
        "email": "user@example.com",
        "role": "user",
    }
    api.get_json.return_value = []

    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    at.text_input(key="login_email").set_value("user@example.com")
    at.text_input(key="login_password").set_value("hunter2222")
    at.button[0].click().run()

    assert not at.exception
    assert at.session_state["access_token"] == TOKEN
    storage.setItem.assert_called_with("smartdigest_token", TOKEN)
    login_call = api.post_json.call_args
    assert login_call.args[0] == "/auth/login"


def test_failed_login_shows_error(env):
    api, _ = env
    api.get_json.return_value = []
    api.post_json.side_effect = requests.exceptions.RequestException("401")

    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    at.text_input(key="login_email").set_value("user@example.com")
    at.text_input(key="login_password").set_value("wrongpass9")
    at.button[0].click().run()

    assert not at.exception
    assert at.session_state["access_token"] is None
    assert any("Giriş başarısız" in e.value for e in at.error)


# --- Kimliği doğrulanmış görünüm -----------------------------------------


def test_authenticated_app_renders_new_summary_view(env):
    api, _ = env
    api.get_json.return_value = []
    at = _authed(AppTest.from_file(APP_PATH, default_timeout=15)).run()

    assert not at.exception
    assert list(at.radio[0].options) == ["Yeni özet", "Geçmiş"]
    assert at.session_state["active_view"] == "Yeni özet"
    assert any(b.label == "Özeti oluştur" for b in at.button)


def test_history_is_fetched_once_and_cached(env):
    api, _ = env
    api.get_json.return_value = []
    at = _authed(AppTest.from_file(APP_PATH, default_timeout=15)).run()
    at.run()  # ikinci rerun
    history_calls = [c for c in api.get_json.call_args_list if c.args and c.args[0] == "/history"]
    assert len(history_calls) == 1


# --- Özet oluşturma ------------------------------------------------------


def test_paste_text_and_submit_creates_job(env):
    api, _ = env
    # /jobs POST işi kuyruğa alır; ardından poll fragment'i çalışır, ona da
    # geçerli bir "running" yanıtı verilmeli ki test iş oluşturmayı ölçebilsin.
    api.get_json.side_effect = lambda path, **kw: (
        {"job_id": "job-1", "status": "running", "progress": 30, "message": "Belge özetleniyor."}
        if path.startswith("/jobs/")
        else []
    )
    api.post_json.return_value = {"job_id": "job-1", "status": "queued"}

    at = _authed(AppTest.from_file(APP_PATH, default_timeout=15)).run()
    at.segmented_control[0].set_value("Metin yapıştır").run()
    at.text_area(key="paste_text").set_value("Yeterince uzun bir belge metni. " * 5)
    next(b for b in at.button if b.label == "Özeti oluştur").click().run()

    assert not at.exception
    job_call = next(c for c in api.post_json.call_args_list if c.args[0] == "/jobs")
    assert job_call.kwargs["json"]["mode"] == "fast"
    assert job_call.kwargs["json"]["text"].startswith("Yeterince uzun")
    assert at.session_state["active_job_id"] == "job-1"


def test_job_success_renders_summary(env):
    api, _ = env
    api.get_json.side_effect = lambda path, **kw: (
        {
            "job_id": "job-1",
            "status": "succeeded",
            "progress": 100,
            "message": "Özet hazır.",
            "summary": "### Özet\nBu bir test özetidir.",
            "evidence": [],
        }
        if path.startswith("/jobs/")
        else []
    )

    at = _authed(AppTest.from_file(APP_PATH, default_timeout=15))
    at.session_state["active_job_id"] = "job-1"
    at.session_state["pending_summary_text"] = "kaynak metin"
    at.session_state["pending_summary_length"] = "balanced"
    at.session_state["active_job_poll_count"] = 0
    at.run()

    assert not at.exception
    assert at.session_state["latest_summary"] == "### Özet\nBu bir test özetidir."
    assert any("test özetidir" in m.value for m in at.markdown)


# --- Geçmişten "Aç" ----------------------------------------------------


def test_reopen_summary_from_history(env):
    api, _ = env
    history = [
        {
            "id": 7,
            "summary": "### Özet\nGeçmişten gelen özet.",
            "created_at": "2026-08-01T10:00:00",
            "has_source": False,
            "source_expires_at": None,
        }
    ]
    api.get_json.return_value = history

    at = _authed(AppTest.from_file(APP_PATH, default_timeout=15)).run()
    at.session_state["active_view"] = "Geçmiş"
    at.run()
    [b for b in at.button if b.label == "Aç"][0].click().run()

    assert not at.exception
    assert at.session_state["latest_summary"] == "### Özet\nGeçmişten gelen özet."
    assert at.session_state["active_view"] == "Yeni özet"
    assert at.session_state["latest_text"] is None


def test_reopen_summary_fetches_retained_source(env):
    api, _ = env
    history = [
        {
            "id": 9,
            "summary": "### Özet\nKaynaklı özet.",
            "created_at": "2026-08-02T10:00:00",
            "has_source": True,
            "source_expires_at": "2026-09-02",
        }
    ]

    def get_json(path, **kw):
        if path == "/history/9/source":
            return {"text": "saklanan kaynak metni"}
        return history

    api.get_json.side_effect = get_json

    at = _authed(AppTest.from_file(APP_PATH, default_timeout=15)).run()
    at.session_state["active_view"] = "Geçmiş"
    at.run()
    [b for b in at.button if b.label == "Aç"][0].click().run()

    assert not at.exception
    assert at.session_state["latest_text"] == "saklanan kaynak metni"


# --- Şifre sıfırlama ---------------------------------------------------


def test_password_reset_form_submits(env):
    api, _ = env
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    at.query_params["reset_token"] = "reset-xyz"
    at.run()

    assert not at.exception
    at.text_input[0].set_value("YeniSifre123")
    at.text_input[1].set_value("YeniSifre123")
    at.button[0].click().run()

    reset_call = next(
        c for c in api.post_json.call_args_list if c.args[0] == "/auth/reset-password"
    )
    assert reset_call.kwargs["json"]["token"] == "reset-xyz"
    assert reset_call.kwargs["json"]["new_password"] == "YeniSifre123"


def test_password_reset_rejects_mismatch(env):
    api, _ = env
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    at.query_params["reset_token"] = "reset-xyz"
    at.run()
    at.text_input[0].set_value("YeniSifre123")
    at.text_input[1].set_value("BaskaSifre999")
    at.button[0].click().run()

    assert not at.exception
    assert any("eşleşmiyor" in e.value for e in at.error)
    assert not any(
        c.args and c.args[0] == "/auth/reset-password" for c in api.post_json.call_args_list
    )
