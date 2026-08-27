"""Streamlit'ten bağımsız, test edilebilir saf metin/özet işleme yardımcıları.

Bu modül hiçbir `streamlit` çağrısı yapmaz; böylece `app.py`'yi (ve onun
çalışma zamanı yan etkilerini: sayfa yapılandırması, backend'e istek atma vb.)
başlatmadan doğrudan içe aktarılıp test edilebilir.
"""

import re

import requests


def error_detail(error: requests.exceptions.RequestException) -> str:
    """Backend'in JSON gövdesindeki `detail` mesajını çıkarır; yoksa ham istisnayı döndürür."""
    response = getattr(error, "response", None)
    if response is not None:
        try:
            return response.json()["detail"]
        except (ValueError, KeyError):
            pass
    return str(error)


def meeting_notes(summary: str) -> str:
    return f"""# Toplantı Notu\n\n## Belge özeti\n{summary}\n\n## Görüşülecek noktalar\n- Özet içindeki kritik bulguları değerlendirin.\n- Riskler ve sonraki adımlar için sorumluları belirleyin.\n"""


def email_draft(summary: str) -> str:
    return f"""Konu: Belge özeti\n\nMerhaba,\n\nBelgenin kısa özeti aşağıdadır:\n\n{summary}\n\nİyi çalışmalar."""


def summary_sections(summary: str) -> dict[str, list[str] | str]:
    """Backend'in Markdown özetini dört taranabilir sunum bölümüne ayırır."""
    overview_match = re.search(
        r"###\s*Özet\s*\n(.*?)(?=\n###\s*Öne çıkanlar|\Z)",
        summary,
        flags=re.DOTALL | re.IGNORECASE,
    )
    overview = overview_match.group(1).strip() if overview_match else summary.strip()
    highlight_match = re.search(
        r"###\s*Öne çıkanlar\s*\n(.*)", summary, flags=re.DOTALL | re.IGNORECASE
    )
    raw_highlights = highlight_match.group(1) if highlight_match else ""
    highlights = []
    for line in raw_highlights.splitlines():
        item = re.sub(r"^\s*[-*•]\s*", "", line).strip()
        item = re.sub(r"^\[(?:Kritik|Önemli|Detay)\]\s*", "", item, flags=re.IGNORECASE)
        if item:
            highlights.append(item)

    number_pattern = re.compile(r"(?:%\s*)?\d+(?:[.,]\d+)*(?:\s*%)?")
    result_pattern = re.compile(
        r"\b(sonuç|sonuc|arttı|azaldı|sağladı|başardı|gösterdi|bulundu|"
        r"öneri|öneriliyor|gerekiyor|planlanıyor|hedefleniyor|risk|sınırlı)\w*",
        re.IGNORECASE,
    )
    numbers, results, important = [], [], []
    for item in highlights:
        if number_pattern.search(item):
            numbers.append(item)
        elif result_pattern.search(item):
            results.append(item)
        else:
            important.append(item)

    return {
        "overview": overview,
        "highlights": highlights,
        "important": important,
        "numbers": numbers,
        "results": results,
    }


def clean_summary_text(value: str) -> str:
    """Sunumda kaynak parantezlerini kaldırıp metni tek satırda temizler."""
    value = re.sub(r"\s*_?\((?:Kaynak|Sayfa|Destek).*?\)_?\s*", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def concise_overview(value: str, limit: int = 5) -> str:
    """Ana özeti en fazla beş cümlede tutar; ayrıntılar aşağıdaki kapalı bölümde kalır."""
    cleaned = clean_summary_text(value)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    return " ".join(sentences[:limit]) if sentences else cleaned


def numeric_facts(items: list[str], limit: int = 4) -> list[tuple[str, str]]:
    """Sayısal bulgulardan hızlı taranabilir küçük metrik kartları üretir."""
    facts = []
    for item in items:
        cleaned = clean_summary_text(item)
        values = re.findall(
            r"(?:%\s*)?\d+(?:[.,]\d+)*(?:\s*(?:%|milyon|milyar|bin|TL|saat|gün|ay|yıl|kavşak))?",
            cleaned,
            flags=re.IGNORECASE,
        )
        if not values:
            continue
        value = " → ".join(part.strip() for part in values[:2])
        caption = cleaned if len(cleaned) <= 74 else f"{cleaned[:71].rsplit(' ', 1)[0]}…"
        facts.append((value, caption))
        if len(facts) >= limit:
            break
    return facts
