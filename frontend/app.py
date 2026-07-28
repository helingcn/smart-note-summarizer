import streamlit as st
import requests
from datetime import datetime, timedelta

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="SmartDigest", page_icon="📝", layout="wide")

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] {
    font-size: 18px;
}
.stat-card {
    border-radius: 12px;
    padding: 18px 20px;
}
.stat-accent { background-color: #0C2A47; color: #B5D4F4; }
.stat-success { background-color: #173404; color: #C0DD97; }
.stat-label { font-size: 0.9rem; font-weight: 500; margin: 0; opacity: 0.85; }
.stat-value { font-size: 2rem; font-weight: 600; margin: 8px 0 0; }
.history-card {
    background-color: #161A23;
    border: 1px solid #2A2E3A;
    border-radius: 12px;
    padding: 18px 20px;
    margin-bottom: 14px;
}
.history-card p { font-size: 1rem !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div style="display:flex; align-items:center; gap:14px; margin-bottom:20px;">
  <div style="width:44px; height:44px; border-radius:12px; background:#378ADD; display:flex; align-items:center; justify-content:center; font-size:22px;">📝</div>
  <div>
    <p style="font-size:26px; font-weight:600; margin:0; color:#F2F2F0;">SmartDigest</p>
    <p style="font-size:15px; color:#9A9A96; margin:0;">Yerel yapay zeka ile akıllı özetleme</p>
  </div>
</div>
""", unsafe_allow_html=True)

try:
    resp = requests.get(f"{API_URL}/history")
    resp.raise_for_status()
    history_data = resp.json()
except requests.exceptions.RequestException:
    history_data = []
    st.error("Backend'e ulaşılamıyor. Sunucunun çalıştığından emin ol.")

total_count = len(history_data)

one_week_ago = datetime.now() - timedelta(days=7)
week_count = 0
for item in history_data:
    try:
        created = datetime.strptime(item["created_at"], "%Y-%m-%d %H:%M:%S")
        if created >= one_week_ago:
            week_count += 1
    except (ValueError, KeyError):
        pass

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
    <div class="stat-card stat-accent">
        <p class="stat-label">Toplam Özet</p>
        <p class="stat-value">{total_count}</p>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="stat-card stat-success">
        <p class="stat-label">Bu Hafta</p>
        <p class="stat-value">{week_count}</p>
    </div>
    """, unsafe_allow_html=True)

st.write("")

tab1, tab2 = st.tabs(["✨ Özetle", "🕘 Geçmiş"])

with tab1:
    secim = st.radio("Kaynak seç:", ["PDF Yükle", "Metin Yapıştır"], horizontal=True)
    text = None

    if secim == "PDF Yükle":
        uploaded_file = st.file_uploader("PDF dosyanı seç", type="pdf")
        if uploaded_file is not None:
            with st.spinner("PDF'ten metin çıkarılıyor..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                    response = requests.post(f"{API_URL}/extract", files=files)
                    response.raise_for_status()
                    text = response.json()["text"]
                    st.success(f"{len(text)} karakter çıkarıldı.")
                except requests.exceptions.RequestException as e:
                    st.error(f"Hata: {e}")
    else:
        text = st.text_area("Özetlenecek metni buraya yapıştırın", height=200)

    if st.button("Özetle", type="primary") and text:
        with st.status("Özetleniyor...", expanded=True) as status:
            st.write("Metin backend'e gönderiliyor...")
            try:
                status.update(label="Model özetliyor, bu biraz sürebilir...")
                response = requests.post(f"{API_URL}/summarize", json={"text": text})
                response.raise_for_status()
                summary = response.json()["summary"]
                status.update(label="Tamamlandı", state="complete", expanded=False)
                st.success("Özet hazır")
                st.write(summary)
            except requests.exceptions.RequestException as e:
                status.update(label="Hata oluştu", state="error")
                st.error(f"Hata: {e}")

with tab2:
    search_query = st.text_input("Ara", placeholder="Özet içinde ara...")

    filtered_data = history_data
    if search_query:
        filtered_data = [
            item for item in history_data
            if search_query.lower() in item["summary"].lower()
        ]

    if not filtered_data:
        st.info("Sonuç bulunamadı." if search_query else "Henüz kayıtlı özet yok.")
    else:
        for item in filtered_data:
            st.markdown(f"""
            <div class="history-card">
                <p style="font-size:12px; color:#9A9A96; margin:0 0 6px;">{item['created_at']}</p>
                <p style="font-size:13px; font-weight:600; margin:0 0 4px; color:#F2F2F0;">Özet</p>
                <p style="font-size:14px; margin:0; color:#D5D5D2;">{item['summary']}</p>
            </div>
            """, unsafe_allow_html=True)

            col_a, col_b, col_c = st.columns([1, 1, 4])
            with col_a:
                st.download_button(
                    "İndir",
                    data=item["summary"],
                    file_name=f"ozet_{item['id']}.txt",
                    key=f"download_{item['id']}"
                )
            with col_b:
                if st.button("Sil", key=f"delete_{item['id']}"):
                    requests.delete(f"{API_URL}/history/{item['id']}")
                    st.rerun()
            st.write("")