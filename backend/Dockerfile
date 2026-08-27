FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-tur \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-backend.txt .
RUN pip install --no-cache-dir -r requirements-backend.txt

COPY backend/ backend/
RUN addgroup --system smartdigest && adduser --system --ingroup smartdigest smartdigest \
    && mkdir -p /app/.smartdigest-data \
    && chown -R smartdigest:smartdigest /app

WORKDIR /app/backend
USER smartdigest
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
