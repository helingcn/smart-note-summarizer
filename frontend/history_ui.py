"""Özet geçmişi görünümü ve kayıt işlemleri."""

import html
from collections.abc import Callable

import requests
import streamlit as st
from summary_utils import error_detail


def render_history(
    history_data: list[dict], api_url: str, auth_headers: Callable[[], dict]
) -> None:
    privacy_left, privacy_right = st.columns([3, 2])
    with privacy_left:
        st.caption(
            "Geçmiş, SmartDigest sunucusundaki kullanıcı hesabınıza özel veritabanında tutulur."
        )
    with privacy_right:
        clear_confirmed = st.checkbox(
            "Tüm kayıtları silmeyi onaylıyorum", key="clear_history_confirm"
        )
        if st.button(
            "Tüm geçmişi sil",
            type="secondary",
            disabled=not clear_confirmed,
            use_container_width=True,
        ):
            try:
                requests.delete(
                    f"{api_url}/history", headers=auth_headers(), timeout=10
                ).raise_for_status()
                st.session_state.latest_summary = None
                st.session_state.latest_evidence = []
                st.session_state.latest_text = None
                st.session_state.latest_length = "balanced"
                st.session_state.chat_messages = []
                st.rerun()
            except requests.exceptions.RequestException as error:
                st.error(f"Geçmiş temizlenemedi: {error_detail(error)}")
    search_query = st.text_input(
        "Geçmişte ara", placeholder="Özetlerde ara…", label_visibility="collapsed"
    )
    filtered_data = [
        item
        for item in history_data
        if not search_query or search_query.lower() in item["summary"].lower()
    ]
    if not filtered_data:
        st.info("Aramana uygun özet bulunamadı." if search_query else "Henüz kayıtlı bir özet yok.")
    for item in filtered_data:
        item_id = item["id"]
        safe_summary = html.escape(item["summary"])
        preview = safe_summary if len(safe_summary) <= 330 else f"{safe_summary[:330]}…"
        meta = f"{len(item['summary']):,} karakter"
        if item.get("has_source") and item.get("source_expires_at"):
            meta += f" · kaynak {item['source_expires_at'][:10]} tarihine kadar saklanıyor"
        st.markdown(
            f'<div class="sd-history-item"><p class="sd-history-date">{item["created_at"]}</p>'
            f'<p class="sd-history-summary">{preview}</p>'
            f'<p class="sd-history-meta">{meta}</p></div>',
            unsafe_allow_html=True,
        )
        action1, action2, action3, _ = st.columns([1.1, 1, 1.3, 3.6])
        with action1:
            st.download_button(
                "Özeti indir", item["summary"], f"ozet_{item_id}.txt", key=f"download_{item_id}"
            )
        with action2:
            confirm_key = f"confirm_delete_{item_id}"
            if st.session_state.get(confirm_key):
                if st.button("Emin misin?", key=f"delete_confirm_{item_id}", type="primary"):
                    try:
                        requests.delete(
                            f"{api_url}/history/{item_id}", headers=auth_headers(), timeout=10
                        ).raise_for_status()
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                    except requests.exceptions.RequestException as error:
                        st.error(f"Kayıt silinemedi: {error_detail(error)}")
            elif st.button("Sil", key=f"delete_{item_id}"):
                st.session_state[confirm_key] = True
                st.rerun()
        with action3:
            if item.get("has_source"):
                source_key = f"fetched_source_{item_id}"
                if source_key in st.session_state:
                    st.download_button(
                        "Kaynağı indir",
                        st.session_state[source_key],
                        f"kaynak_{item_id}.txt",
                        key=f"download_source_{item_id}",
                    )
                elif st.button("Kaynağı getir", key=f"fetch_source_{item_id}"):
                    try:
                        source_response = requests.get(
                            f"{api_url}/history/{item_id}/source",
                            headers=auth_headers(),
                            timeout=10,
                        )
                        source_response.raise_for_status()
                        st.session_state[source_key] = source_response.json()["text"]
                        st.rerun()
                    except requests.exceptions.RequestException as error:
                        st.error(f"Kaynak getirilemedi: {error_detail(error)}")
