import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from extractor import PDFValidationError, extract_pdf, has_pdf_signature


def test_rejects_file_without_pdf_signature(tmp_path):
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"This is not a PDF")
    assert has_pdf_signature(str(fake_pdf)) is False
    with pytest.raises(PDFValidationError, match="geçerli bir PDF"):
        extract_pdf(str(fake_pdf))
