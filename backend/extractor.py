from __future__ import annotations

import multiprocessing as mp
import queue
import shutil
from dataclasses import asdict, dataclass

import pdfplumber

MAX_PDF_PAGES = 150
PDF_TIMEOUT_SECONDS = 90


class PDFValidationError(ValueError):
    pass


@dataclass
class ExtractedPage:
    page: int
    text: str
    method: str = "text"


@dataclass
class ExtractedDocument:
    text: str
    pages: list[ExtractedPage]
    page_count: int
    ocr_used: bool


def has_pdf_signature(file_path: str) -> bool:
    with open(file_path, "rb") as file:
        return b"%PDF-" in file.read(1024)


def ocr_available() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        import pypdfium2  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def _ocr_page(file_path: str, page_index: int) -> str:
    import pypdfium2 as pdfium
    import pytesseract

    pdf = pdfium.PdfDocument(file_path)
    try:
        image = pdf[page_index].render(scale=2).to_pil()
        return pytesseract.image_to_string(image, lang="tur+eng").strip()
    finally:
        pdf.close()


def _extract_worker(file_path: str, output: mp.Queue) -> None:
    try:
        pages: list[ExtractedPage] = []
        used_ocr = False
        with pdfplumber.open(file_path) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise PDFValidationError(f"PDF en fazla {MAX_PDF_PAGES} sayfa olabilir.")
            for index, page in enumerate(pdf.pages):
                text = (page.extract_text() or "").strip()
                method = "text"
                if len(text) < 20 and ocr_available():
                    ocr_text = _ocr_page(file_path, index)
                    if len(ocr_text) > len(text):
                        text, method, used_ocr = ocr_text, "ocr", True
                pages.append(ExtractedPage(index + 1, text, method))

        combined = "\n\n".join(f"[Sayfa {page.page}]\n{page.text}" for page in pages if page.text)
        output.put(
            {
                "ok": True,
                "document": {
                    "text": combined,
                    "pages": [asdict(page) for page in pages],
                    "page_count": len(pages),
                    "ocr_used": used_ocr,
                },
            }
        )
    except Exception as error:
        message = str(error)
        lowered = message.lower()
        if "password" in lowered or "encrypted" in lowered:
            message = "Şifreli PDF dosyaları desteklenmiyor."
        elif not message:
            message = "PDF bozuk veya okunamıyor."
        output.put({"ok": False, "error": message})


def extract_pdf(file_path: str, timeout_seconds: int = PDF_TIMEOUT_SECONDS) -> ExtractedDocument:
    if not has_pdf_signature(file_path):
        raise PDFValidationError("Dosyanın içeriği geçerli bir PDF değil.")

    output: mp.Queue = mp.Queue(maxsize=1)
    process = mp.Process(target=_extract_worker, args=(file_path, output), daemon=True)
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2)
        raise TimeoutError("PDF işleme süresi sınırı aşıldı.")
    try:
        result = output.get(timeout=2)
    except queue.Empty as error:
        raise PDFValidationError("PDF bozuk veya okunamıyor.") from error
    if not result["ok"]:
        raise PDFValidationError(result["error"])
    data = result["document"]
    return ExtractedDocument(
        text=data["text"],
        pages=[ExtractedPage(**page) for page in data["pages"]],
        page_count=data["page_count"],
        ocr_used=data["ocr_used"],
    )
