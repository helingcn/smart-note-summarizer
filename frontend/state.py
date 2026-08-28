"""Streamlit oturum durumunun tek merkezden yönetimi."""

import streamlit as st

DEFAULTS: dict[str, object] = {
    "access_token": None,
    "user_email": None,
    "user_role": "user",
    "active_view": "Yeni özet",
    "latest_summary": None,
    "latest_evidence": [],
    "latest_text": None,
    "latest_length": "balanced",
    "chat_messages": [],
    "active_job_id": None,
}


def initialize_session_state() -> None:
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value.copy() if isinstance(value, list) else value


def clear_auth_state() -> None:
    st.session_state.access_token = None
    st.session_state.user_email = None
    st.session_state.user_role = "user"


def clear_summary_state() -> None:
    st.session_state.latest_summary = None
    st.session_state.latest_evidence = []
    st.session_state.latest_text = None
    st.session_state.latest_length = "balanced"
    st.session_state.chat_messages = []
    st.session_state.active_job_id = None


def load_summary_into_view(
    summary: str, source_text: str | None = None, length: str = "balanced"
) -> None:
    """Geçmişten bir özeti sonuç görünümüne yükler. Kaynak kanıtları yalnızca
    yeni üretimde hesaplandığından burada boş kalır; kaynak metin saklanmışsa
    belge sohbeti yine çalışır."""
    st.session_state.latest_summary = summary
    st.session_state.latest_evidence = []
    st.session_state.latest_text = source_text
    st.session_state.latest_length = length
    st.session_state.chat_messages = []
    st.session_state.active_job_id = None
    st.session_state.active_view = "Yeni özet"
    st.session_state.scroll_to_summary = True
