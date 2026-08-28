import html
import os
import time

import requests
import streamlit as st
from api_client import APIClient
from auth_ui import render_account
from history_ui import render_history
from state import clear_summary_state, initialize_session_state
from streamlit_local_storage import LocalStorage
from summary_ui import copy_summary_button, render_summary_section
from summary_utils import (
    clean_summary_text,
    concise_overview,
    email_draft,
    error_detail,
    meeting_notes,
    numeric_chips,
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


@st.cache_data(ttl=15, show_spinner=False)
def fetch_history(token: str) -> list[dict]:
    """Geçmiş, token başına 15 sn önbelleklenir; aksi hâlde her Streamlit
    rerun'unda (bir segmented control'e tıklamak bile) backend'e istek atardı.
    Geçmişi değiştiren işlemler `fetch_history.clear()` çağırır."""
    return api.get_json("/history", token=token, timeout=4)


verify_token = st.query_params.get("verify_token")
if verify_token:
    try:
        api.post_json("/auth/verify-email", json={"token": verify_token})
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
                api.post_json(
                    "/auth/reset-password",
                    json={"token": reset_token, "new_password": reset_password_value},
                )
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
            me = api.get_json("/auth/me", token=stored_token, timeout=6)
            st.session_state.access_token = stored_token
            st.session_state.user_email = me["email"]
            st.session_state.user_role = me.get("role", "user")
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
                data = api.post_json(
                    "/auth/login",
                    json={"email": login_email, "password": login_password},
                )
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
                    data = api.post_json("/auth/forgot-password", json={"email": forgot_email})
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
                data = api.post_json(
                    "/auth/register",
                    json={"email": register_email, "password": register_password},
                )
                if data.get("verification_required"):
                    st.success(
                        "Kayıt oluşturuldu. E-posta adresinize gönderilen bağlantıyla hesabınızı doğrulayın."
                    )
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
def extract_pdf_text(file_bytes: bytes, file_name: str, token: str) -> dict:
    """Aynı dosya baytlarıyla tekrar çağrılırsa API'ye gitmeden önbellekten döner;
    aksi hâlde dosya değişmese bile her Streamlit rerun'unda (ör. bir segmented
    control'e tıklamak) PDF yeniden ayrıştırılır/OCR'lanırdı. `token` yalnızca
    önbellek anahtarına dahil olması için parametredir."""
    return api.post_json(
        "/extract",
        token=token,
        files={"file": (file_name, file_bytes, "application/pdf")},
        timeout=60,
    )


st.markdown(
    """
    <div class="sd-product-header">
      <p class="sd-name">SmartDigest</p>
      <h1 class="sd-page-title">Belge Özetleme ve Kaynak Analizi</h1>
      <p class="sd-page-subtitle">PDF belgelerini veya metinleri özetleyin; önemli bulguları,
      sayıları ve kaynak eşleşmelerini tek yerde inceleyin.</p>
      <p class="sd-privacy">Belge içeriği özetleme sırasında Google Gemini API'ye gönderilir.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

header_space, header_account = st.columns([5, 1.2])
with header_account:
    with st.popover("Hesap", use_container_width=True):
        st.caption(st.session_state.user_email)
        render_account(api, local_storage)
        if st.button("Bu cihazdan çıkış yap", use_container_width=True):
            st.session_state.access_token = None
            st.session_state.user_email = None
            st.session_state.user_role = "user"
            local_storage.deleteItem("smartdigest_token")
            fetch_history.clear()
            time.sleep(0.3)
            st.rerun()

try:
    history_data = fetch_history(st.session_state.access_token)
except requests.exceptions.RequestException:
    history_data = []
    st.warning("Geçmişe şu an ulaşılamıyor. Backend sunucusunun çalıştığını kontrol edin.")

# st.tabs sekme seçimini session_state'te tutamaz; geçmişten "Aç" ile sonuç
# görünümüne geçebilmek için görünümü kendimiz kontrol ediyoruz. `key=` KULLANMA:
# widget oluşturulduktan sonra load_summary_into_view'in st.session_state.active_view'i
# değiştirmesi StreamlitAPIException verirdi. index + geri yazma bunu aşar.
_VIEWS = ["Yeni özet", "Geçmiş"]
_current_view = (
    st.session_state.active_view if st.session_state.active_view in _VIEWS else _VIEWS[0]
)
view = st.radio(
    "Görünüm",
    _VIEWS,
    index=_VIEWS.index(_current_view),
    horizontal=True,
    label_visibility="collapsed",
)
st.session_state.active_view = view

if view == "Yeni özet":
    with st.container(border=True):
        st.markdown(
            '<p class="sd-panel-title">Belgenizi ekleyin</p>'
            '<p class="sd-panel-copy">Özetlemeye başlamak için bir PDF seçin veya metin yapıştırın.</p>',
            unsafe_allow_html=True,
        )
        choice = st.segmented_control(
            "Kaynak",
            ["PDF yükle", "Metin yapıştır"],
            default="PDF yükle",
            required=True,
            label_visibility="collapsed",
        )

        text = None
        if choice == "PDF yükle":
            uploaded_file = st.file_uploader(
                "PDF belgesi", type="pdf", label_visibility="collapsed"
            )
            if uploaded_file:
                try:
                    extracted = extract_pdf_text(
                        uploaded_file.getvalue(),
                        uploaded_file.name,
                        st.session_state.access_token,
                    )
                    text = extracted["text"]
                    method = " · OCR kullanıldı" if extracted.get("ocr_used") else ""
                    st.success(
                        f"{uploaded_file.name} · {extracted.get('page_count', '?')} sayfa · "
                        f"{len(text):,} karakter okundu{method}"
                    )
                except requests.exceptions.RequestException as error:
                    st.error(f"PDF işlenemedi: {error_detail(error)}")
        else:
            text = st.text_area(
                "Özetlenecek metin",
                height=220,
                placeholder="Özetlemek istediğiniz metni buraya yapıştırın…",
                label_visibility="collapsed",
                key="paste_text",
            )
            st.caption(
                f"En fazla {MAX_SUMMARY_INPUT_CHARS:,} karakter · Enter ile özetle, "
                "Shift+Enter ile alt satır"
            )
            # st.text_area çok satırlı olduğundan Enter varsayılan olarak alt satır
            # açar. Kullanıcı metni yapıştırıp Enter'a basınca doğrudan özetlemeye
            # geçmek istiyor: ana dokümana bir kez kapsayıcı (capture) keydown
            # dinleyicisi enjekte edip Enter'ı yakalıyor, metni commit etmek için
            # textarea'yı blur ediyor ve "Özeti oluştur" düğmesi aktifleşince
            # tıklıyoruz. Dinleyici parent realm'de yaşadığından rerun'larda kalıcı.
            # st.iframe, components.v1.html'in yerini alan güncel API'dir; HTML
            # string'ini JS çalıştıran bir iframe'de gömer.
            st.iframe(
                """
                <script>
                (function () {
                  const doc = window.parent.document;
                  if (doc.__sdPasteEnter) return;
                  doc.__sdPasteEnter = true;
                  const s = doc.createElement('script');
                  s.textContent = `
                    document.addEventListener('keydown', function (e) {
                      if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
                      const ta = e.target;
                      if (!ta || ta.tagName !== 'TEXTAREA' || !ta.closest) return;
                      if (!ta.closest('[data-testid=stTextArea]')) return;
                      e.preventDefault();
                      e.stopPropagation();
                      ta.blur();
                      let n = 0;
                      const t = setInterval(function () {
                        const b = Array.from(document.querySelectorAll('button'))
                          .find(function (x) { return x.textContent.trim() === 'Özeti oluştur'; });
                        if (b && !b.disabled) { b.click(); clearInterval(t); }
                        if (++n > 25) clearInterval(t);
                      }, 100);
                    }, true);
                  `;
                  doc.head.appendChild(s);
                })();
                </script>
                """,
                height=1,  # st.iframe 0'ı kabul etmiyor; 1px görünmez
            )

        mode = "fast"
        length = "balanced"
        retain_source = False
        retention_days = 7
        with st.expander("Gelişmiş ayarlar", expanded=False):
            st.markdown('<p class="sd-field-label">Özet modu</p>', unsafe_allow_html=True)
            mode = st.segmented_control(
                "Özet modu",
                ["fast", "verified"],
                format_func=lambda value: "Hızlı" if value == "fast" else "Kaynak kontrollü",
                default="fast",
                required=True,
                label_visibility="collapsed",
                help="Kaynak kontrollü mod, özet iddialarını belgedeki ilgili sayfalarla otomatik olarak eşleştirir.",
            )
            st.caption("Kaynak kontrollü mod, iddiaları ilgili belge bölümleriyle eşleştirir.")

            st.markdown('<p class="sd-field-label">Özet uzunluğu</p>', unsafe_allow_html=True)
            length = st.segmented_control(
                "Özet uzunluğu",
                ["balanced", "detailed"],
                format_func=lambda value: {"balanced": "Dengeli", "detailed": "Detaylı"}[value],
                default="balanced",
                required=True,
                label_visibility="collapsed",
            )

            retain_source = st.checkbox(
                "Kaynak belgeyi geçmişte şifreli sakla",
                value=False,
                help="Kapalıyken yalnızca özet saklanır. Açıkken kaynak seçilen süre sonunda silinir.",
            )
            if retain_source:
                retention_days = st.selectbox(
                    "Kaynağı otomatik sil",
                    [1, 7, 30],
                    index=1,
                    format_func=lambda days: f"{days} gün sonra",
                )

        st.caption("Varsayılan ayar: hızlı, dengeli özet. Kaynak metin geçmişte saklanmaz.")
        submitted = st.button(
            "Özeti oluştur", type="primary", use_container_width=True, disabled=not bool(text)
        )
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
                    job = api.post_json(
                        "/jobs",
                        json={
                            "text": text,
                            "mode": mode,
                            "length": length,
                            "retain_source": retain_source,
                            "retention_days": retention_days,
                        },
                        timeout=15,
                    )
                    st.session_state.active_job_id = job["job_id"]
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
                job = api.get_json(f"/jobs/{job_id}", timeout=10)
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
                        api.delete(f"/jobs/{job_id}", timeout=10)
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
                fetch_history.clear()  # yeni özet kaydedildi
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
        # Sayısal maddeler "Ana bulgular"dan çıkarılmaz; kartlar yalnızca hızlı
        # tarama katmanıdır, bulgunun kendisi listede de kalır. Aksi hâlde
        # maddelerin çoğu sayısalsa liste neredeyse boş görünüyordu.
        highlights: list[str] = []
        seen_highlights: set[str] = set()
        for item in sections["highlights"]:
            cleaned = clean_summary_text(item)
            if cleaned and cleaned.casefold() not in seen_highlights:
                seen_highlights.add(cleaned.casefold())
                highlights.append(cleaned)
        highlights = highlights[: 8 if is_detailed else 5]
        chips = numeric_chips(
            overview, sections["numbers"], len(st.session_state.get("latest_text") or "")
        )

        st.markdown(
            '<div id="summary-anchor" class="sd-result-head">'
            '<p class="sd-result-title">Özet</p>'
            '<p class="sd-result-subtitle">Kanıt ve ayrıntılar aşağıdaki bölümlerde.</p></div>',
            unsafe_allow_html=True,
        )
        if st.session_state.get("scroll_to_summary"):
            st.session_state.scroll_to_summary = False
            st.iframe(
                """
                <script>
                  const anchor = window.parent.document.getElementById('summary-anchor');
                  if (anchor) anchor.scrollIntoView({behavior: 'smooth', block: 'start'});
                </script>
                """,
                height=1,  # st.iframe 0'ı kabul etmiyor; 1px görünmez
            )
        chip_html = (
            '<div class="sd-chips">'
            + "".join(f'<span class="sd-chip">{html.escape(chip)}</span>' for chip in chips)
            + "</div>"
            if chips
            else ""
        )
        st.markdown(
            '<div class="sd-summary-card"><p class="sd-summary-label">'
            + ("Detaylı özet" if is_detailed else "Kısa özet")
            + "</p>"
            f'<p class="sd-summary-copy">{html.escape(overview)}</p></div>{chip_html}',
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

        action1, action2, action3 = st.columns(3)
        with action1:
            if st.button("Yeni özet oluştur", type="primary", use_container_width=True):
                clear_summary_state()
                st.rerun()
        with action2:
            copy_summary_button(summary)
        with action3:
            st.download_button(
                "TXT indir", summary, "smartdigest_ozet.txt", use_container_width=True
            )

        evidence = st.session_state.get("latest_evidence", [])
        if evidence:
            with st.container():
                st.markdown('<span class="sd-exp-primary"></span>', unsafe_allow_html=True)
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
                            if item.get("verification") == "semantic"
                            and item.get("confidence") is not None
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

        with st.container():
            st.markdown('<span class="sd-exp-primary"></span>', unsafe_allow_html=True)
            chat_expander = st.expander("Belgeyle sohbet", expanded=False)
        with chat_expander:
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
                if not st.session_state.latest_text:
                    st.warning(
                        "Bu özetin kaynak metni saklanmadığı için belge sohbeti kullanılamıyor."
                    )
                elif not question:
                    st.warning("Lütfen bir soru yazın.")
                else:
                    with st.spinner("Belgede ilgili bölümler aranıyor..."):
                        try:
                            answer = api.post_json(
                                "/chat",
                                json={
                                    "text": st.session_state.latest_text,
                                    "question": question,
                                },
                                timeout=(5, 180),
                            )
                            st.session_state.chat_messages.append({"question": question, **answer})
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

        with st.expander("Ayrıntılı analiz", expanded=is_detailed):
            render_summary_section("Tüm önemli noktalar", sections["important"])
            render_summary_section("Sayısal bulgular", sections["numbers"], "number")
            render_summary_section("Sonuç ve öneriler", sections["results"], "result")
            st.markdown("##### Modelin özgün çıktısı")
            st.markdown(summary)

        with st.container():
            st.markdown('<span class="sd-exp-muted"></span>', unsafe_allow_html=True)
            export_expander = st.expander("Dışa aktar", expanded=False)
        with export_expander:
            export1, export2, export3 = st.columns(3)
            with export1:
                st.download_button(
                    "Markdown",
                    summary,
                    "smartdigest_ozet.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with export2:
                st.download_button(
                    "Toplantı notu",
                    meeting_notes(summary),
                    "toplanti_notu.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with export3:
                st.download_button(
                    "E-posta taslağı",
                    email_draft(summary),
                    "eposta_taslagi.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

if view == "Geçmiş":
    render_history(history_data, api, fetch_history.clear)
