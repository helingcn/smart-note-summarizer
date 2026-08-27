"""SmartDigest backend çağrıları için ortak istemci yardımcıları."""

from typing import Any

import requests
import streamlit as st


def client_forward_headers() -> dict[str, str]:
    """Reverse proxy arkasındaki gerçek istemci IP'sini backend'e aktarır."""
    try:
        forwarded = st.context.headers.get("X-Forwarded-For")
        real_ip = st.context.headers.get("X-Real-Ip")
    except Exception:
        return {}
    value = forwarded or real_ip
    return {"X-Forwarded-For": value} if value else {}


class APIClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def headers(self, token: str | None = None) -> dict[str, str]:
        headers = client_forward_headers()
        active_token = token or st.session_state.get("access_token")
        if active_token:
            headers["Authorization"] = f"Bearer {active_token}"
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        timeout: Any = 10,
        **kwargs: Any,
    ) -> requests.Response:
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers={**self.headers(token), **kwargs.pop("headers", {})},
            timeout=timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response
