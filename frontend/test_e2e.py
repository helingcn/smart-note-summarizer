"""Çalışan Streamlit uygulamasına karşı tarayıcı smoke testi."""

import os

import pytest

pytestmark = pytest.mark.e2e


def test_login_screen_is_accessible():
    sync_api = pytest.importorskip("playwright.sync_api")
    base_url = os.getenv("SMARTDIGEST_E2E_URL")
    if not base_url:
        pytest.skip("SMARTDIGEST_E2E_URL tanımlı değil")
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(base_url, wait_until="networkidle")
        assert page.get_by_text("SmartDigest", exact=True).first.is_visible()
        assert page.get_by_role("tab", name="Giriş yap").is_visible()
        browser.close()
