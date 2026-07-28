import streamlit as st
import requests
from datetime import datetime, timedelta

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="SmartDigest", page_icon="📝", layout="wide")

st.markdown("""
<style>
.stat-card {
    border-radius: 10px;
    padding: 14px 16px;
}
.stat-accent { background-color: #E6F1FB; color: #0C447C; }
.stat-success { background-color: #EAF3DE; color: #27500A; }
.stat-label { font-size: 13px; font-weight: 500; margin: 0; }
.stat-value { font-size: 24px; font-weight: 700; margin: 4px 0 0; }
.history-card {
    border: 1px solid rgba(128,128,128,0.25);
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

st.title("📝 SmartDigest")
st.caption("Yerel yapay zeka ile akıllı özetleme")

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
        with st.spinner("Özetleniyor, bu biraz sürebilir..."):
            try:
                response = requests.post(f"{API_URL}/summarize", json={"text": text})
                response.raise_for_status()
                summary = response.json()["summary"]
                st.success("Özet hazır")
                st.write(summary)
            except requests.exceptions.RequestException as e:
                st.error(f"Hata: {e}")

with tab2:
    if not history_data:
        st.info("Henüz kayıtlı özet yok.")
    else:
        for item in history_data:
            st.markdown(f"""
            <div class="history-card">
                <p style="font-size:12px; color:#888; margin:0 0 6px;">{item['created_at']}</p>
                <p style="font-size:13px; font-weight:600; margin:0 0 4px;">Özet</p>
                <p style="font-size:14px; margin:0;">{item['summary']}</p>
            </div>
            """, unsafe_allow_html=True)