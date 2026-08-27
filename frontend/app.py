import html
import os
import time

import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_local_storage import LocalStorage

from api_client import APIClient, client_forward_headers
from auth_ui import render_account
from history_ui import render_history
from state import initialize_session_state
from summary_ui import copy_summary_button, render_summary_section
from summary_utils import (
    clean_summary_text,
    concise_overview,
    email_draft,
    error_detail,
    meeting_notes,
    numeric_facts,
    summary_sections,
)

API_URL = os.getenv("SMARTDIGEST_API_URL", "http://127.0.0.1:8000")
MAX_SUMMARY_INPUT_CHARS = 100_000  # backend/main.py ile aynı sınır
api = APIClient(API_URL)

st.set_page_config(page_title="SmartDigest", page_icon="◆", layout="wide")

with open(os.path.join(os.path.dirname(__file__), "styles.css"), encoding="utf-8") as styles_file:
    st.markdown(f"<style>{styles_file.read()}</style>", unsafe_allow_html=True)

initialize_session_state()

local_storage = LocalStorage()


def auth_headers() -> dict:
    return api.headers()


verify_token = st.query_params.get("verify_token")
if verify_token:
    try:
        response = requests.post(
            f"{API_URL}/auth/verify-email", headers=client_forward_headers(),
            json={"token": verify_token}, timeout=10
        )
        response.raise_for_status()
        st.success("E-posta adresiniz doğrulandı. Şimdi giriş yapabilirsiniz.")
    except requests.exceptions.RequestException as error:
        st.error(f"E-posta doğrulanamadı: {error_detail(error)}")
    st.query_params.clear()

reset_token = st.query_params.get("reset_token")
if reset_token and not st.session_state.access_token:
    st.markdown('<p class="sd-name">SmartDigest · Şifre sıfırlama</p>', unsafe_allow_html=True)
    with st.form("reset_password_form"):
        reset_password_value = st.text_input("Yeni şifre", type="password")
        reset_password_confirm = st.text_input("Yeni şifreyi tekrar yazın", type="password")
        reset_submitted = st.form_submit_button("Şifreyi güncelle", type="primary")
    if reset_submitted:
        if reset_password_value != reset_password_confirm:
            st.error("Şifreler eşleşmiyor.")
        else:
            try:
                response = requests.post(
                    f"{API_URL}/auth/reset-password",
                    headers=client_forward_headers(),
                    json={"token": reset_token, "new_password": reset_password_value},
                    timeout=10,
                )
                response.raise_for_status()
                st.query_params.clear()
                st.success("Şifreniz güncellendi. Giriş yapabilirsiniz.")
            except requests.exceptions.RequestException as error:
                st.error(f"Şifre güncellenemedi: {error_detail(error)}")
    st.stop()


if not st.session_state.access_token:
    # F5 ile sayfa yenilendiğinde st.session_state sıfırlanır (yeni WebSocket
    # bağlantısı = Streamlit'in gözünde yeni oturum); tarayıcının localStorage'ında
    # kalıcı olarak sakladığımız token varsa burada geri yüklüyoruz.
    stored_token = local_storage.getItem("smartdigest_token")
    if stored_token:
        try:
            me_response = requests.get(
                f"{API_URL}/auth/me",
                headers={
                    "Authorization": f"Bearer {stored_token}",
                    **client_forward_headers(),
                },
                timeout=6,
            )
            me_response.raise_for_status()
            st.session_state.access_token = stored_token
            st.session_state.user_email = me_response.json()["email"]
            st.session_state.user_role = me_response.json().get("role", "user")
        except requests.exceptions.RequestException:
            local_storage.deleteItem("smartdigest_token")

if not st.session_state.access_token:
    st.markdown('<p class="sd-name">SmartDigest</p>', unsafe_allow_html=True)
    login_tab, register_tab = st.tabs(["Giriş yap", "Kayıt ol"])
    with login_tab:
        with st.form("login_form"):
            login_email = st.text_input("E-posta", key="login_email")
            login_password = st.text_input("Şifre", type="password", key="login_password")
            login_submitted = st.form_submit_button(
                "Giriş yap", type="primary", use_container_width=True
            )
        if login_submitted:
            try:
                response = requests.post(
                    f"{API_URL}/auth/login",
                    headers=client_forward_headers(),
                    json={"email": login_email, "password": login_password},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                st.session_state.access_token = data["access_token"]
                st.session_state.user_email = data["email"]
                st.session_state.user_role = data.get("role", "user")
                local_storage.setItem("smartdigest_token", data["access_token"])
                time.sleep(0.3)
                st.rerun()
            except requests.exceptions.RequestException as error:
                st.error(f"Giriş başarısız: {error_detail(error)}")
        with st.expander("Şifremi unuttum", expanded=False):
            forgot_email = st.text_input("Hesap e-postası", key="forgot_email")
            if st.button("Sıfırlama bağlantısı gönder", key="forgot_submit"):
                try:
                    response = requests.post(
                        f"{API_URL}/auth/forgot-password",
                        headers=client_forward_headers(),
                        json={"email": forgot_email}, timeout=10,
                    )
                    response.raise_for_status()
                    data = response.json()
                    st.success(data["message"])
                    if data.get("development_token"):
                        st.info(f"Geliştirme doğrulama kodu: {data['development_token']}")
                except requests.exceptions.RequestException as error:
                    st.error(f"İstek gönderilemedi: {error_detail(error)}")
    with register_tab:
        with st.form("register_form"):
            register_email = st.text_input("E-posta", key="register_email")
            register_password = st.text_input(
                "Şifre (en az 8 karakter)", type="password", key="register_password"
            )
            register_submitted = st.form_submit_button(
                "Kayıt ol", type="primary", use_container_width=True
            )
        if register_submitted:
            try:
                response = requests.post(
                    f"{API_URL}/auth/register",
                    headers=client_forward_headers(),
                    json={"email": register_email, "password": register_password},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("verification_required"):
                    st.success("Kayıt oluşturuldu. E-posta adresinize gönderilen bağlantıyla hesabınızı doğrulayın.")
                    if data.get("development_token"):
                        st.info(f"Geliştirme doğrulama kodu: {data['development_token']}")
                else:
                    st.session_state.access_token = data["access_token"]
                    st.session_state.user_email = data["email"]
                    st.session_state.user_role = data.get("role", "user")
                    local_storage.setItem("smartdigest_token", data["access_token"])
                    time.sleep(0.3)
                    st.rerun()
            except requests.exceptions.RequestException as error:
                st.error(f"Kayıt başarısız: {error_detail(error)}")
    st.stop()

@st.cache_data(show_spinner="Belgeden metin çıkarılıyor...")
def extract_pdf_text(file_bytes: bytes, file_name: str) -> dict:
    """Aynı dosya baytlarıyla tekrar çağrılırsa API'ye gitmeden önbellekten döner;
    aksi hâlde dosya değişmese bile her Streamlit rerun'unda (ör. bir segmented
    control'e tıklamak) PDF yeniden ayrıştırılır/OCR'lanırdı."""
    response = requests.post(
        f"{API_URL}/extract",
        headers=auth_headers(),
        files={"file": (file_name, file_bytes, "application/pdf")},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


header_left, header_right = st.columns([5, 1.4])
with header_left:
    st.markdown("""
    <p class="sd-name">SmartDigest</p>
    <p class="sd-privacy">Özetleme için metinler Gemini API'ye (Google) gönderilir.</p>
    """, unsafe_allow_html=True)
with header_right:
    st.caption(st.session_state.user_email)
    if st.button("Çıkış yap", use_container_width=True):
        st.session_state.access_token = None
        st.session_state.user_email = None
        st.session_state.user_role = "user"
        local_storage.deleteItem("smartdigest_token")
        time.sleep(0.3)
        st.rerun()

try:
    response = requests.get(f"{API_URL}/history", headers=auth_headers(), timeout=4)
    response.raise_for_status()
    history_data = response.json()
except requests.exceptions.RequestException:
    history_data = []
    st.warning("Geçmişe şu an ulaşılamıyor. Backend sunucusunun çalıştığını kontrol edin.")

tab1, tab2, tab3 = st.tabs(["Yeni özet", "Geçmiş", "Hesap"])

with tab1:
    with st.container(border=True):
        st.markdown('<p class="sd-panel-title">İçeriğini ekle</p><p class="sd-panel-copy">Bir PDF yükle veya özetlemek istediğin metni yapıştır.</p>', unsafe_allow_html=True)
        choice = st.segmented_control(
            "Kaynak", ["PDF yükle", "Metin yapıştır"],
            default="PDF yükle", required=True, label_visibility="collapsed",
        )

        st.markdown('<p class="sd-field-label">Özet modu</p>', unsafe_allow_html=True)
        mode = st.segmented_control(
            "Özet modu",
            ["fast", "verified"],
            format_func=lambda value: "Hızlı" if value == "fast" else "Kaynak kontrollü",
            default="fast", required=True, label_visibility="collapsed",
            help="Hızlı mod tek işlemde özetler. Kaynak kontrollü mod ikinci geçiş yapar ve maddelere sayfa/destek bilgisi ekler; destek puanı kelime örtüşmesine dayanır, insan doğrulaması veya anlamsal doğrulama değildir.",
        )
        st.caption("Hızlı: daha kısa bekleme · Kaynak kontrollü: sayfa kaynağı ve kelime örtüşmesi puanıyla ikinci geçiş")

        st.markdown('<p class="sd-field-label">Özet uzunluğu</p>', unsafe_allow_html=True)
        length = st.segmented_control(
            "Özet uzunluğu",
            ["balanced", "detailed"],
            format_func=lambda value: {"balanced": "Dengeli", "detailed": "Detaylı"}[value],
            default="balanced", required=True, label_visibility="collapsed",
        )

        retain_source = st.checkbox(
            "Kaynak belgeyi geçmişte şifreli sakla",
            value=False,
            help="Kapalıyken yalnızca özet saklanır. Açıkken kaynak metin seçilen süre sonunda otomatik silinir.",
        )
        st.caption(
            "Belge içeriği özetleme ve belgeyle sohbet sırasında Gemini API'ye "
            "gönderilir. Kaynak saklama kapalıysa işlem tamamlandıktan sonra geçmişe kaydedilmez."
        )
        retention_days = 7
        if retain_source:
            retention_days = st.selectbox(
                "Kaynağı otomatik sil",
                [1, 7, 30],
                index=1,
                format_func=lambda days: f"{days} gün sonra",
            )

        st.markdown('<p class="sd-field-label">İçerik</p>', unsafe_allow_html=True)
        text = None
        if choice == "PDF yükle":
            uploaded_file = st.file_uploader("PDF belgesi", type="pdf", label_visibility="collapsed")
            if uploaded_file:
                try:
                    extracted = extract_pdf_text(uploaded_file.getvalue(), uploaded_file.name)
                    text = extracted["text"]
                    method = " · OCR kullanıldı" if extracted.get("ocr_used") else ""
                    st.caption(
                        f"✓ {uploaded_file.name} · {extracted.get('page_count', '?')} sayfa · "
                        f"{len(text):,} karakter okundu{method}"
                    )
                except requests.exceptions.RequestException as error:
                    st.error(f"PDF işlenemedi: {error_detail(error)}")
            submitted = st.button("Özeti oluştur", type="primary", use_container_width=True)
        else:
            # Form içindeki text_area'da Streamlit yalnızca Ctrl/Cmd+Enter'ı forma
            # gönderme (submit) tetikleyicisi sayar; düz Enter satır başı yapar. Aşağıdaki
            # script, Shift'siz düz Enter'ı yakalayıp satır eklemeden Ctrl/Cmd+Enter'a
            # dönüştürür; böylece Streamlit'in kendi doğrulanmış gönderim akışı çalışır.
            with st.form("paste_text_form", border=False):
                text = st.text_area("Özetlenecek metin", height=220, placeholder="Metnini buraya yapıştır…", label_visibility="collapsed", key="paste_text")
                st.caption(f"En fazla {MAX_SUMMARY_INPUT_CHARS:,} karakter kabul edilir.")
                submitted = st.form_submit_button("Özeti oluştur", type="primary", use_container_width=True)
                components.html(
                    """
                    <script>
                      (function() {
                        const doc = window.parent.document;
                        if (doc._smartdigestEnterHandler) {
                          doc.removeEventListener('keydown', doc._smartdigestEnterHandler);
                        }
                        const handler = function(e) {
                          if (e.key !== 'Enter' || e.shiftKey || e.ctrlKey || e.metaKey) return;
                          const target = e.target;
                          if (!target || target.tagName !== 'TEXTAREA') return;
                          if (target.getAttribute('aria-label') !== 'Özetlenecek metin') return;
                          e.preventDefault();
                          target.dispatchEvent(new KeyboardEvent('keydown', {
                            key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
                            bubbles: true, cancelable: true, ctrlKey: true, metaKey: true,
                          }));
                        };
                        doc.addEventListener('keydown', handler);
                        doc._smartdigestEnterHandler = handler;
                      })();
                    </script>
                    """,
                    height=0,
                )
            if text and st.session_state.latest_summary:
                st.button("Temizle", use_container_width=True, on_click=lambda: st.session_state.update(paste_text=""))

        if submitted:
            if not text:
                st.warning("Lütfen özetlenecek bir metin ekleyin.")
            elif len(text) > MAX_SUMMARY_INPUT_CHARS:
                st.warning(
                    f"Metin çok uzun ({len(text):,} karakter, maks. "
                    f"{MAX_SUMMARY_INPUT_CHARS:,}). Lütfen kısaltıp tekrar deneyin."
                )
            else:
                try:
                    response = requests.post(
                        f"{API_URL}/jobs",
                        headers=auth_headers(),
                        json={
                            "text": text,
                            "mode": mode,
                            "length": length,
                            "retain_source": retain_source,
                            "retention_days": retention_days,
                        },
                        timeout=15,
                    )
                    response.raise_for_status()
                    st.session_state.active_job_id = response.json()["job_id"]
                    st.session_state.pending_summary_text = text
                    st.session_state.pending_summary_length = length
                    st.session_state.active_job_poll_count = 0
                    st.rerun()
                except requests.exceptions.RequestException as error:
                    st.error(f"Özet oluşturulamadı: {error_detail(error)}")

    if st.session_state.active_job_id:
        @st.fragment(run_every=1)
        def _poll_active_job():
            job_id = st.session_state.active_job_id
            if not job_id:
                return
            try:
                job_response = requests.get(
                    f"{API_URL}/jobs/{job_id}", headers=auth_headers(), timeout=10
                )
                job_response.raise_for_status()
                job = job_response.json()
            except requests.exceptions.RequestException as error:
                st.session_state.active_job_id = None
                st.error(f"İş durumu alınamadı: {error_detail(error)}")
                st.rerun()
                return

            st.session_state.active_job_poll_count += 1
            progress_col, cancel_col = st.columns([5, 1])
            with progress_col:
                # Backend artık taslak/doğrulama/kanıt eşleştirme gibi gerçek
                # adımlarda ilerleme bildiriyor (summarize_long_text'teki
                # on_progress geri çağrısı); burada onu doğrudan yansıtıyoruz.
                st.progress(job["progress"], text=job["message"])
            with cancel_col:
                if st.button("İptal et", key=f"cancel_{job_id}", use_container_width=True):
                    try:
                        requests.delete(f"{API_URL}/jobs/{job_id}", headers=auth_headers(), timeout=10)
                    except requests.exceptions.RequestException:
                        pass

            if job["status"] == "succeeded":
                st.session_state.latest_summary = job["summary"]
                st.session_state.latest_evidence = job.get("evidence", [])
                st.session_state.latest_text = st.session_state.pending_summary_text
                st.session_state.latest_length = st.session_state.pending_summary_length
                st.session_state.chat_messages = []
                st.session_state.scroll_to_summary = True
                st.session_state.active_job_id = None
                st.rerun()
            elif job["status"] == "cancelled":
                st.session_state.active_job_id = None
                st.info("İşlem iptal edildi.")
            elif job["status"] == "failed":
                st.session_state.active_job_id = None
                st.error(job.get("error") or job["message"])
            elif st.session_state.active_job_poll_count >= 240:
                # Normalde birkaç Gemini çağrısı toplam 1-2 dakikada tamamlanır;
                # 240 saniyeyi geçmesi backend'de takılmış bir isteğe işaret eder.
                # Kullanıcıyı sonsuza kadar bekletmek yerine net bir hata ile
                # bilgilendiriyoruz.
                st.session_state.active_job_id = None
                st.error(
                    "Özetleme beklenenden uzun sürdü ve zaman aşımına uğradı. "
                    "Lütfen tekrar deneyin."
                )

        _poll_active_job()

    summary = st.session_state.latest_summary
    if summary:
        is_detailed = st.session_state.get("latest_length") == "detailed"
        sections = summary_sections(summary)
        overview = (
            clean_summary_text(str(sections["overview"]))
            if is_detailed
            else concise_overview(str(sections["overview"]))
        )
        numeric_items = {clean_summary_text(item) for item in sections["numbers"]}
        highlights = [
            cleaned
            for item in sections["highlights"]
            if (cleaned := clean_summary_text(item)) and cleaned not in numeric_items
        ][:8 if is_detailed else 5]
        facts = numeric_facts(sections["numbers"])

        st.markdown(
            '<div id="summary-anchor" class="sd-result-head">'
            '<p class="sd-result-title">Özet</p>'
            '<p class="sd-result-subtitle">Kanıt ve ayrıntılar aşağıdaki bölümlerde.</p></div>',
            unsafe_allow_html=True,
        )
        if st.session_state.get("scroll_to_summary"):
            st.session_state.scroll_to_summary = False
            components.html(
                """
                <script>
                  const anchor = window.parent.document.getElementById('summary-anchor');
                  if (anchor) anchor.scrollIntoView({behavior: 'smooth', block: 'start'});
                </script>
                """,
                height=0,
            )
        st.markdown(
            '<div class="sd-summary-card"><p class="sd-summary-label">'
            + ("Detaylı özet" if is_detailed else "Kısa özet")
            + '</p>'
            f'<p class="sd-summary-copy">{html.escape(overview)}</p></div>',
            unsafe_allow_html=True,
        )

        if highlights:
            st.markdown('<p class="sd-section-label">Ana bulgular</p>', unsafe_allow_html=True)
            st.markdown(
                '<ul class="sd-highlights">'
                + "".join(f"<li>{html.escape(item)}</li>" for item in highlights)
                + "</ul>",
                unsafe_allow_html=True,
            )

        if facts:
            st.markdown('<p class="sd-section-label">Öne çıkan sayılar</p>', unsafe_allow_html=True)
            st.markdown(
                '<div class="sd-facts">'
                + "".join(
                    '<div class="sd-fact">'
                    f'<p class="sd-fact-value">{html.escape(value)}</p>'
                    f'<p class="sd-fact-copy">{html.escape(description)}</p></div>'
                    for value, description in facts
                )
                + "</div>",
                unsafe_allow_html=True,
            )

        action1, action2, action3 = st.columns([2, 1, 2])
        with action1:
            st.download_button("↓ TXT indir", summary, "smartdigest_ozet.txt", use_container_width=True)
        with action2:
            copy_summary_button(summary)
        with action3:
            if st.button("Yeni özet", use_container_width=True):
                st.session_state.latest_summary = None
                st.session_state.latest_evidence = []
                st.session_state.latest_text = None
                st.session_state.latest_length = "balanced"
                st.session_state.chat_messages = []
                st.rerun()

        evidence = st.session_state.get("latest_evidence", [])
        if evidence:
            with st.expander(f"Kaynak kanıtları ({len(evidence)})", expanded=False):
                st.caption(
                    "Kaynak kontrollü modda aday parçalar kelime eşleşmesiyle bulunur; ardından iddia ile "
                    "kanıt arasındaki anlam ilişkisi ayrıca değerlendirilir. Sonuçlar otomatik kontroldür "
                    "ve kritik kararlarda kaynak belgeyle karşılaştırılmalıdır."
                )
                status_labels = {
                    "supported": "Destekleniyor",
                    "review": "İncelenmeli",
                    "weak": "Zayıf eşleşme",
                }
                for index, item in enumerate(evidence, 1):
                    status = item.get("status", "review")
                    label = status_labels.get(status, "İncelenmeli")
                    verification = (
                        f"anlamsal güven %{round(item['confidence'] * 100)}"
                        if item.get("verification") == "semantic" and item.get("confidence") is not None
                        else f"kelime desteği %{item['support']}"
                    )
                    st.markdown(
                        f'<div class="sd-evidence-item">'
                        f'<p class="sd-evidence-claim">{index}. {html.escape(item["claim"])}</p>'
                        f'<p class="sd-evidence-meta">Sayfa {item["page"]}, paragraf {item["paragraph"]} · '
                        f'<span class="sd-badge {status}">{label}</span> · {verification}</p>'
                        f'<p class="sd-quote">"{html.escape(item["quote"])}"</p></div>',
                        unsafe_allow_html=True,
                    )

        with st.expander("Ayrıntılı analiz", expanded=is_detailed):
            render_summary_section("Tüm önemli noktalar", sections["important"])
            render_summary_section("Sayısal bulgular", sections["numbers"], "number")
            render_summary_section("Sonuç ve öneriler", sections["results"], "result")
            st.markdown("##### Modelin özgün çıktısı")
            st.markdown(summary)

        with st.expander("Dışa aktar", expanded=False):
            export1, export2, export3 = st.columns(3)
            with export1:
                st.download_button("Markdown", summary, "smartdigest_ozet.md", mime="text/markdown", use_container_width=True)
            with export2:
                st.download_button("Toplantı notu", meeting_notes(summary), "toplanti_notu.md", mime="text/markdown", use_container_width=True)
            with export3:
                st.download_button("E-posta taslağı", email_draft(summary), "eposta_taslagi.txt", mime="text/plain", use_container_width=True)

        with st.expander("Belgeyle sohbet", expanded=False):
            st.caption("Sorular yalnızca bu özetin oluşturulduğu belgeden yanıtlanır.")
            # text_input tek satırlı olduğundan form içinde Enter, ana özetleme
            # kutusundaki gibi ekstra bir JS hack'ine gerek kalmadan formu gönderir.
            with st.form("chat_form", border=False):
                question = st.text_input(
                    "Belgeye soru sor",
                    placeholder="Örneğin: Projenin en önemli riski nedir?",
                    key="document_question",
                )
                ask_submitted = st.form_submit_button("Soruyu yanıtla")
            if ask_submitted:
                if not question:
                    st.warning("Lütfen bir soru yazın.")
                else:
                    with st.spinner("Belgede ilgili bölümler aranıyor..."):
                        try:
                            response = requests.post(
                                f"{API_URL}/chat",
                                headers=auth_headers(),
                                json={"text": st.session_state.latest_text, "question": question},
                                timeout=(5, 180),
                            )
                            response.raise_for_status()
                            st.session_state.chat_messages.append({"question": question, **response.json()})
                            st.rerun()
                        except requests.exceptions.RequestException as error:
                            st.error(f"Soru yanıtlanamadı: {error_detail(error)}")
            for message in reversed(st.session_state.chat_messages):
                st.markdown(f"**Soru:** {message['question']}")
                st.write(message["answer"])
                if message["sources"]:
                    st.markdown("**Kullanılan kaynak parçaları**")
                    for source in message["sources"]:
                        st.caption(source)

with tab2:
    render_history(history_data, API_URL, auth_headers)
with tab3:
    render_account(API_URL, auth_headers, local_storage)
