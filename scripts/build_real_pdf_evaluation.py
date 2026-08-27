#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import config as _config  # noqa: E402,F401 - .env dosyasını yükler
from backend.extractor import MAX_PDF_PAGES  # noqa: E402
from backend.summarizer import answer_question, summarize_long_text  # noqa: E402

DOCUMENTS = ROOT / "evals" / "documents"
OUTPUT = ROOT / "evals" / "datasets" / "real_turkish_pdfs.json"


CASES = (
    {
        "id": "kmu_stratejik_plan",
        "title": "Karamanoğlu Mehmetbey Üniversitesi Stratejik Planı",
        "file": "kmu_stratejik_plan.pdf",
        "pages": (6, 9),
        "facts": (
            (
                "Üniversite çağdaş ve etik değerleri benimseyen, hukukun üstünlüğüne inanan nitelikli bireyler yetiştirmeyi amaçlar.",
                (6,),
            ),
            (
                "Üniversite bilim, teknoloji, kültür ve sanata katkı sağlamayı özgörev edinmiştir.",
                (6,),
            ),
            (
                "Stratejik plan çalışmaları kurumsallaşma, eğitim-öğretim ve araştırma-geliştirme olmak üzere üç temel eksen üzerine kurulmuştur.",
                (8,),
            ),
            (
                "Kurumsallaşma ekseni etkin ve verimli bir idari yapı ile ulusal ve uluslararası tanınırlığı artırmayı hedefler.",
                (9,),
            ),
        ),
        "numbers": (("3", "stratejik plan üç temel eksen üzerine kurulmuştur", None),),
        "qa": (
            (
                "Üniversitenin stratejik planı kaç temel eksen üzerine kurulmuştur?",
                "Üç temel eksen üzerine kurulmuştur.",
                (8,),
            ),
            (
                "Kurumsallaşma ekseninin amacı nedir?",
                "Etkin ve verimli bir idari yapı kurmak, ulusal ve uluslararası tanınırlığı artırmak ve kurumsal gelişmeyi sağlamaktır.",
                (9,),
            ),
        ),
    },
    {
        "id": "stratejik_planlama_ders",
        "title": "Stratejik Planlama Ders Notu",
        "file": "stratejik_planlama_ders.pdf",
        "pages": (6, 11),
        "facts": (
            (
                "Kurum kavramının toplumbilimsel ve kamu örgütlenmesine ilişkin iki anlamı vardır.",
                (6,),
            ),
            (
                "Kuruluş, önceden belirlenmiş sınırlı ve somut bir amaca göre oluşturulan hizmet üreten örgütlü bütünlüktür.",
                (7,),
            ),
            (
                "Stratejik planlama İkinci Dünya Savaşı sonrasında özel sektörde uygulanmaya başlamıştır.",
                (9,),
            ),
            (
                "Alfred Chandler 1962 yılında strateji ile örgütlenme yapısı arasındaki bağlantıyı incelemiştir.",
                (10,),
            ),
            ("Igor Ansoff Corporate Strategy çalışmasını 1965 yılında yayımlamıştır.", (10,)),
        ),
        "numbers": (
            ("2", "kurum kavramının iki anlamı vardır", None),
            ("1962", "Alfred Chandler strateji ile örgütlenme yapısı", None),
            ("1965", "Igor Ansoff Corporate Strategy", None),
        ),
        "qa": (
            (
                "Kurum kavramının kaç anlamı vardır?",
                "İki anlamı vardır: toplumbilimsel anlam ve kamu örgütlenmesine ilişkin anlam.",
                (6,),
            ),
            (
                "Kuruluş ile kurum arasındaki temel fark nedir?",
                "Kuruluş yerel, somut ve sınırlı bir hizmete odaklanırken kurum daha geniş politika izler ve ülke veya bölge çapında yaygındır.",
                (7, 8),
            ),
        ),
    },
    {
        "id": "tubitak_2025_faaliyet_sunus",
        "title": "TÜBİTAK 2025 Faaliyet Raporu - Başkan Sunuşu",
        "file": "tubitak_2025_faaliyet.pdf",
        "pages": (9, 9),
        "facts": (
            (
                "Popüler Bilim Dergileri Ücretsiz Elektronik Arşivi yıl boyunca 12 milyon indirmeye ulaşmıştır.",
                (9,),
            ),
            ("Bilim Genç platformu 45,5 milyon görüntülenmeye ulaşmıştır.", (9,)),
        ),
        "numbers": (
            ("12", "Popüler Bilim Dergileri Ücretsiz Elektronik Arşivi milyon indirilme", None),
            ("45,5", "Bilim Genç platformu milyon görüntülenme", None),
        ),
        "qa": (
            (
                "Popüler Bilim Dergileri Ücretsiz Elektronik Arşivi kaç indirmeye ulaşmıştır?",
                "12 milyon indirmeye ulaşmıştır.",
                (9,),
            ),
            (
                "Bilim Genç platformu kaç görüntülenmeye ulaşmıştır?",
                "45,5 milyon görüntülenmeye ulaşmıştır.",
                (9,),
            ),
        ),
        "expect_page_limit_rejection": True,
    },
)


def extract_window(path: Path, start: int, end: int) -> tuple[str, int]:
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        pages = []
        for page_number in range(start, end + 1):
            text = (pdf.pages[page_number - 1].extract_text() or "").strip()
            pages.append(f"[Sayfa {page_number}]\n{text}")
    return "\n\n".join(pages), page_count


def generate_candidate(source_text: str, questions: tuple, retries: int = 3):
    """Kota/ağ gibi geçici sağlayıcı hatalarında belgeyi yeniden dener."""
    for attempt in range(1, retries + 1):
        try:
            started = time.perf_counter()
            summary = summarize_long_text(source_text, verified=True, length="balanced")
            qa_outputs = []
            for question, _answer, _pages in questions:
                answer, sources = answer_question(source_text, question)
                qa_outputs.append({"question": question, "answer": answer, "sources": sources})
            return summary, qa_outputs, time.perf_counter() - started
        except Exception as exc:
            if attempt == retries:
                raise
            wait_seconds = 70
            print(
                f"Geçici model hatası ({type(exc).__name__}); "
                f"{wait_seconds} saniye sonra {attempt + 1}/{retries} deneniyor...",
                flush=True,
            )
            time.sleep(wait_seconds)


def main() -> int:
    output_cases = []
    validation = []
    for case_index, spec in enumerate(CASES):
        # Kaynak kontrollü özet bir belge için birden fazla model çağrısı yapar.
        # Ücretsiz Gemini kotasında belgeler arası kısa bekleme 429 hatasını önler.
        if case_index:
            print("Gemini dakika kotası için 65 saniye bekleniyor...", flush=True)
            time.sleep(65)
        path = DOCUMENTS / spec["file"]
        source_text, page_count = extract_window(path, *spec["pages"])
        should_reject = page_count > MAX_PDF_PAGES
        validation.append(
            {
                "id": spec["id"],
                "page_count": page_count,
                "page_limit": MAX_PDF_PAGES,
                "expected_rejection": bool(spec.get("expect_page_limit_rejection")),
                "actual_rejection": should_reject,
                "passed": should_reject == bool(spec.get("expect_page_limit_rejection")),
            }
        )

        summary, qa_outputs, latency = generate_candidate(source_text, spec["qa"])

        output_cases.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "source_text": source_text,
                "document": {
                    "filename": spec["file"],
                    "page_count": page_count,
                    "evaluated_pages": list(range(spec["pages"][0], spec["pages"][1] + 1)),
                },
                "expected": {
                    "facts": [
                        {"text": fact, "source_pages": list(pages)} for fact, pages in spec["facts"]
                    ],
                    "numbers": [
                        {
                            "value": value,
                            "context": context,
                            **({"direction": direction} if direction else {}),
                        }
                        for value, context, direction in spec["numbers"]
                    ],
                    "qa": [
                        {"question": question, "answer": answer, "source_pages": list(pages)}
                        for question, answer, pages in spec["qa"]
                    ],
                },
                "candidate": {"summary": summary, "qa": qa_outputs, "latency_seconds": latency},
            }
        )
        print(f"{spec['id']}: model çıktısı üretildi ({latency:.1f} sn)", flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "name": "SmartDigest gerçek Türkçe PDF değerlendirmesi",
                "version": "1",
                "method": "Her belgenin seçili ve elle doğrulanmış sayfa penceresi değerlendirilmiştir.",
                "document_validation": validation,
                "cases": output_cases,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Veri kümesi: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
