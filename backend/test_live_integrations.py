"""Dış servis/ikili gerektiren, açıkça seçilerek çalıştırılan testler."""

import os
import shutil

import pytest


@pytest.mark.live_api
def test_real_gemini_call_returns_grounded_answer():
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY tanımlı değil")
    from summarizer import ask_model

    answer = ask_model("Kaynak: SmartDigest kontrol kodu 7319'dur. Yalnızca kontrol kodunu yaz.")
    assert "7319" in answer


@pytest.mark.ocr
def test_real_tesseract_extracts_scanned_pdf(tmp_path):
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract kurulu değil")
    pytest.importorskip("pypdfium2")
    pytest.importorskip("pytesseract")
    from extractor import extract_pdf
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 500), "white")
    font = ImageFont.load_default(size=72)
    ImageDraw.Draw(image).text(
        (80, 180), "SMARTDIGEST OCR TEST 7319", fill="black", font=font, stroke_width=1
    )
    pdf_path = tmp_path / "scan.pdf"
    image.save(pdf_path, "PDF", resolution=150)

    document = extract_pdf(str(pdf_path))
    normalized = document.text.upper().replace(" ", "")
    assert document.ocr_used is True
    assert "SMARTDIGEST" in normalized
