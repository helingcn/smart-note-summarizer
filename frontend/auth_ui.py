"""Hesap güvenliği ve yönetici arayüzü."""

import time
from typing import Any

import requests
import streamlit as st
from api_client import APIClient
from summary_utils import error_detail


def render_account(api: APIClient, local_storage: Any) -> None:
    st.markdown("#### Şifre ve güvenlik")

    with st.form("change_password_form"):
        current_password = st.text_input(
            "Mevcut şifre", type="password", autocomplete="current-password"
        )
        new_password = st.text_input("Yeni şifre", type="password", autocomplete="new-password")
        change_password_submitted = st.form_submit_button("Şifreyi değiştir")
    if change_password_submitted:
        try:
            api.post_json(
                "/auth/change-password",
                json={"current_password": current_password, "new_password": new_password},
                timeout=15,
            )
            st.session_state.access_token = None
            local_storage.deleteItem("smartdigest_token")
            st.success("Şifre değiştirildi. Tüm oturumlar kapatıldı; tekrar giriş yapın.")
            time.sleep(1)
            st.rerun()
        except requests.exceptions.RequestException as error:
            st.error(f"Şifre değiştirilemedi: {error_detail(error)}")

    if st.button("Tüm cihazlardaki oturumları kapat"):
        try:
            api.post_json("/auth/logout-all")
            st.session_state.access_token = None
            local_storage.deleteItem("smartdigest_token")
            st.rerun()
        except requests.exceptions.RequestException as error:
            st.error(f"Oturumlar kapatılamadı: {error_detail(error)}")

    st.divider()
    st.markdown("#### Veri ve hesap")
    with st.expander("Hesabı kalıcı olarak sil", expanded=False):
        st.warning(
            "Bu işlem hesabınızı, özetlerinizi ve saklanan kaynaklarınızı geri alınamaz biçimde siler."
        )
        with st.form("delete_account_form"):
            delete_password = st.text_input(
                "Onay için şifreniz", type="password", autocomplete="current-password"
            )
            delete_confirm = st.checkbox("Hesabımın ve tüm verilerimin silinmesini onaylıyorum")
            delete_submitted = st.form_submit_button("Hesabı sil", disabled=not delete_confirm)
        if delete_submitted:
            try:
                api.delete("/auth/account", json={"password": delete_password}, timeout=15)
                st.session_state.clear()
                local_storage.deleteItem("smartdigest_token")
                st.rerun()
            except requests.exceptions.RequestException as error:
                st.error(f"Hesap silinemedi: {error_detail(error)}")

    if st.session_state.user_role == "admin":
        st.markdown("### Kullanıcı yönetimi")
        try:
            for user in api.get_json("/admin/users"):
                left, right = st.columns([4, 1])
                with left:
                    state = "devre dışı" if user["disabled"] else "aktif"
                    st.write(f"{user['email']} · {user['role']} · {state}")
                with right:
                    if user["email"] != st.session_state.user_email:
                        target_disabled = not bool(user["disabled"])
                        if st.button(
                            "Etkinleştir" if user["disabled"] else "Devre dışı bırak",
                            key=f"admin_user_{user['id']}",
                        ):
                            api.patch_json(
                                f"/admin/users/{user['id']}",
                                json={"disabled": target_disabled},
                            )
                            st.rerun()
        except requests.exceptions.RequestException as error:
            st.error(f"Kullanıcılar alınamadı: {error_detail(error)}")
