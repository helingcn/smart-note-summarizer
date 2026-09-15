"""Özet geçmişi görünümü ve kayıt işlemleri."""

import html
from collections.abc import Callable

import requests
import streamlit as st
from api_client import APIClient
from state import clear_summary_state, load_summary_into_view
from summary_utils import error_detail


def render_history(
    history_data: list[dict], api: APIClient, on_history_change: Callable[[], None]
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
                api.delete("/history")
                on_history_change()
                # Görüntülenen özet de artık geçmişte yok; eski davranışla tutarlı
                # olarak sonuç görünümünü de temizliyoruz.
                clear_summary_state()
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
        with st.container(border=True):
            st.markdown('<span class="sd-history-card"></span>', unsafe_allow_html=True)
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
            action1, action2, action3, action4 = st.columns([1.1, 1.1, 1, 3.3])
            with action1:
                if st.button("Aç", key=f"open_{item_id}", type="primary"):
                    source_text = None
                    if item.get("has_source"):
                        try:
                            source_text = api.get_json(f"/history/{item_id}/source")["text"]
                        except requests.exceptions.RequestException as error:
                            st.warning(f"Kaynak metin yüklenemedi: {error_detail(error)}")
                    load_summary_into_view(item["summary"], source_text)
                    st.rerun()
            with action2:
                st.download_button(
                    "İndir", item["summary"], f"ozet_{item_id}.txt", key=f"download_{item_id}"
                )
            with action3:
                confirm_key = f"confirm_delete_{item_id}"
                if st.session_state.get(confirm_key):
                    if st.button("Emin misin?", key=f"delete_confirm_{item_id}", type="primary"):
                        try:
                            api.delete(f"/history/{item_id}")
                            st.session_state.pop(confirm_key, None)
                            on_history_change()
                            st.rerun()
                        except requests.exceptions.RequestException as error:
                            st.error(f"Kayıt silinemedi: {error_detail(error)}")
                elif st.button("Sil", key=f"delete_{item_id}"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            with action4:
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
                            st.session_state[source_key] = api.get_json(
                                f"/history/{item_id}/source"
                            )["text"]
                            st.rerun()
                        except requests.exceptions.RequestException as error:
                            st.error(f"Kaynak getirilemedi: {error_detail(error)}")
