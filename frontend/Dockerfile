FROM python:3.13-slim

WORKDIR /app
COPY requirements-frontend.txt .
RUN pip install --no-cache-dir -r requirements-frontend.txt

COPY frontend/ frontend/
COPY .streamlit/ .streamlit/
RUN addgroup --system smartdigest && adduser --system --ingroup smartdigest smartdigest \
    && chown -R smartdigest:smartdigest /app

USER smartdigest
EXPOSE 8501
HEALTHCHECK --interval=20s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2)" || exit 1
CMD ["streamlit", "run", "frontend/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
