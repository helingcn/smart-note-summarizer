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


_NUM = r"\d+(?:[.,]\d+)*"
_UNIT_WORDS = (
    "milyon",
    "milyar",
    "trilyon",
    "katrilyon",
    "bin",
    "TL",
    "₺",
    "dolar",
    "avro",
    "euro",
    "€",
    "$",
    "saniye",
    "dakika",
    "saat",
    "gün",
    "hafta",
    "ay",
    "yıl",
    "kişi",
    "adet",
    "kez",
    "kat",
    "puan",
    "derece",
    "santigrat",
    "kilometrekare",
    "kilometre",
    "metrekare",
    "metre",
    "hektar",
    "km",
)
_UNIT = "|".join(sorted((re.escape(word) for word in _UNIT_WORDS), key=len, reverse=True))

_RANGE_WORDS = {
    "iki": "2",
    "üç": "3",
    "uc": "3",
    "dört": "4",
    "dort": "4",
    "beş": "5",
    "bes": "5",
    "altı": "6",
    "alti": "6",
    "yedi": "7",
    "sekiz": "8",
    "dokuz": "9",
    "on": "10",
}
_RANGE_TOKEN = r"\d+(?:[.,]\d+)?|" + "|".join(_RANGE_WORDS)
_RANGE_STOP_UNITS = {
    "ve",
    "veya",
    "ile",
    "ila",
    "arası",
    "arasında",
    "gibi",
    "olan",
    "kadar",
    "daha",
    "en",
    "yaklaşık",
    "ortalama",
    "oranında",
    "katına",
    "arttı",
    "azaldı",
    "yükseldi",
    "düştü",
    "çıktı",
}

_RANGE_RE = re.compile(
    rf"\b(?P<a>{_RANGE_TOKEN})\s*(?:-|–|—|ila|ile)\s*(?P<b>{_RANGE_TOKEN})\b"
    rf"(?:\s*(?P<unit>%|°[Cc]?|[a-zçğıöşü]{{2,}}))?",
    re.IGNORECASE,
)
_VALUE_RE = re.compile(
    rf"(?P<pct>%\s?{_NUM}|{_NUM}\s?%|yüzde\s?{_NUM})"
    rf"|(?P<num>{_NUM})(?:\s?(?P<unit>{_UNIT})\w*)?",
    re.IGNORECASE,
)
_CHANGE_RE = re.compile(
    r"→|'?(?:den|dan|ten|tan)\b|\biken\b|\bart[ıi]\w*|\byüksel\w*|\bdüş\w*"
    r"|\bazal\w*|\bçık[tı]\w*|\bgeriled\w*|\bkatlan\w*|\bindi\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def _bare(number: str) -> str:
    return number.replace(".", "").replace(",", "")


def fact_value(text: str) -> str | None:
    """Bir bulgu cümlesinden karta yazılacak en anlamlı sayısal ifadeyi seçer.

    - "üç ila dört kovan" / "2-3 derece" gibi aralıkları "3-4 kovan" biçiminde verir.
    - Bir değişim anlatılıyorsa ("1.500 iken ... 3.500") "1.500 → 3.500" üretir.
    - Tek anlamlı değer birimli/oranlıysa onu ("30 metre") tercih eder.
    - Cümlede yalnızca çıplak bir yıl (2008, 2021) varsa kart üretmez; yıl tek
      başına "öne çıkan sayı" değildir.
    """
    range_match = _RANGE_RE.search(text)
    if range_match:
        start = _RANGE_WORDS.get(range_match["a"].lower(), range_match["a"])
        end = _RANGE_WORDS.get(range_match["b"].lower(), range_match["b"])
        unit = (range_match["unit"] or "").strip()
        if unit.lower() in _RANGE_STOP_UNITS or unit.lower().startswith("yıl"):
            unit = ""
        both_years = bool(_YEAR_RE.match(_bare(start)) and _YEAR_RE.match(_bare(end)))
        if start != end and not both_years:
            return f"{start}-{end} {unit}".strip()

    candidates: list[tuple[str, str]] = []  # (görünen, çıplak sayı)
    for match in _VALUE_RE.finditer(text):
        if match.group("pct"):
            digits = re.sub(r"[^\d.,]", "", match.group("pct"))
            candidates.append((f"%{digits}", _bare(digits)))
            continue
        number = match.group("num")
        unit = match.group("unit") or ""
        candidates.append((f"{number} {unit}".strip(), _bare(number)))

    meaningful = [item for item in candidates if not _YEAR_RE.match(item[1])]
    if not meaningful:
        return None

    if len(meaningful) >= 2 and _CHANGE_RE.search(text):
        return f"{meaningful[0][0]} → {meaningful[1][0]}"

    def rank(item: tuple[str, str]) -> tuple[int, float]:
        display, bare = item
        has_unit = 1 if any(char.isalpha() for char in display) or "%" in display else 0
        try:
            magnitude = float(bare.replace(",", "."))
        except ValueError:
            magnitude = 0.0
        return has_unit, magnitude

    return max(meaningful, key=rank)[0]


def numeric_facts(items: list[str], limit: int = 6) -> list[str]:
    """Verilen metin parçalarından tekilleştirilmiş sayısal değerleri sırayla
    döndürür (ör. ["1.500 → 3.500", "2-3 derece"]). Bağlam/etiket üretmez;
    değerler yanlarındaki maddeden okunur."""
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = fact_value(clean_summary_text(item))
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        values.append(value)
        if len(values) >= limit:
            break
    return values


# "Öne çıkan sayılar" çipleri yalnızca belge, 3 maddelik bir özetin sayıları
# tek başına taşıyamayacağı kadar uzunsa gösterilir. Eşik, backend'in "kısa
# belge" sınırıyla (word_target'taki 3.500) aynı.
MIN_CHARS_FOR_CHIPS = 3_500
MIN_CHIP_COUNT = 3


def numeric_chips(
    overview: str,
    numeric_highlights: list[str],
    source_length: int,
    *,
    limit: int = 6,
) -> list[str]:
    """Kısa özetin altında gösterilecek ikincil sayı çiplerini üretir.

    Manşet sayıları (ör. "1.500 → 3.500", "30 metre") çoğu zaman yalnızca özet
    cümlelerinde geçtiğinden hem özeti hem sayısal maddeleri tararız. Belge
    kısaysa ya da en az 3 farklı anlamlı sayı çıkmıyorsa hiç gösterilmez;
    o durumda maddeler zaten yeterli.
    """
    if source_length < MIN_CHARS_FOR_CHIPS:
        return []
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", clean_summary_text(overview))
        if part.strip()
    ]
    values = numeric_facts(sentences + list(numeric_highlights), limit)
    return values if len(values) >= MIN_CHIP_COUNT else []
