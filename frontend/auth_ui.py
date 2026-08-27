"""Hesap güvenliği ve yönetici arayüzü."""

import time
from collections.abc import Callable
from typing import Any

import requests
import streamlit as st
from summary_utils import error_detail


def render_account(api_url: str, auth_headers: Callable[[], dict], local_storage: Any) -> None:
    st.markdown("#### Şifre ve güvenlik")

    with st.form("change_password_form"):
        current_password = st.text_input("Mevcut şifre", type="password")
        new_password = st.text_input("Yeni şifre", type="password")
        change_password_submitted = st.form_submit_button("Şifreyi değiştir")
    if change_password_submitted:
        try:
            response = requests.post(
                f"{api_url}/auth/change-password",
                headers=auth_headers(),
                json={"current_password": current_password, "new_password": new_password},
                timeout=15,
            )
            response.raise_for_status()
            st.session_state.access_token = None
            local_storage.deleteItem("smartdigest_token")
            st.success("Şifre değiştirildi. Tüm oturumlar kapatıldı; tekrar giriş yapın.")
            time.sleep(1)
            st.rerun()
        except requests.exceptions.RequestException as error:
            st.error(f"Şifre değiştirilemedi: {error_detail(error)}")

    if st.button("Tüm cihazlardaki oturumları kapat"):
        try:
            requests.post(
                f"{api_url}/auth/logout-all", headers=auth_headers(), timeout=10
            ).raise_for_status()
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
            delete_password = st.text_input("Onay için şifreniz", type="password")
            delete_confirm = st.checkbox("Hesabımın ve tüm verilerimin silinmesini onaylıyorum")
            delete_submitted = st.form_submit_button("Hesabı sil", disabled=not delete_confirm)
        if delete_submitted:
            try:
                requests.delete(
                    f"{api_url}/auth/account",
                    headers=auth_headers(),
                    json={"password": delete_password},
                    timeout=15,
                ).raise_for_status()
                st.session_state.clear()
                local_storage.deleteItem("smartdigest_token")
                st.rerun()
            except requests.exceptions.RequestException as error:
                st.error(f"Hesap silinemedi: {error_detail(error)}")

    if st.session_state.user_role == "admin":
        st.markdown("### Kullanıcı yönetimi")
        try:
            users_response = requests.get(
                f"{api_url}/admin/users", headers=auth_headers(), timeout=10
            )
            users_response.raise_for_status()
            for user in users_response.json():
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
                            requests.patch(
                                f"{api_url}/admin/users/{user['id']}",
                                headers=auth_headers(),
                                json={"disabled": target_disabled},
                                timeout=10,
                            ).raise_for_status()
                            st.rerun()
        except requests.exceptions.RequestException as error:
            st.error(f"Kullanıcılar alınamadı: {error_detail(error)}")
