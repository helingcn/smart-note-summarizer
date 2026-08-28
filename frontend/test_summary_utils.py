from unittest.mock import Mock

import requests
from summary_utils import (
    clean_summary_text,
    concise_overview,
    email_draft,
    error_detail,
    meeting_notes,
    numeric_chips,
    numeric_facts,
    summary_sections,
)


def test_summary_sections_splits_overview_and_highlights():
    summary = (
        "### Özet\nProje başarıyla tamamlandı.\n\n"
        "### Öne çıkanlar\n"
        "- [Kritik] Bütçe %20 arttı.\n"
        "- [Önemli] Kullanıcı sayısı 500 oldu.\n"
        "- [Detay] Ekip beş kişiden oluşuyor."
    )
    sections = summary_sections(summary)
    assert sections["overview"] == "Proje başarıyla tamamlandı."
    assert sections["highlights"] == [
        "Bütçe %20 arttı.",
        "Kullanıcı sayısı 500 oldu.",
        "Ekip beş kişiden oluşuyor.",
    ]


def test_summary_sections_categorizes_numbers_and_results():
    summary = (
        "### Özet\nGenel bakış.\n\n"
        "### Öne çıkanlar\n"
        "- Bütçe 100 milyon TL oldu.\n"
        "- Proje riskli görülüyor.\n"
        "- Ekip yeni ofise taşındı."
    )
    sections = summary_sections(summary)
    assert sections["numbers"] == ["Bütçe 100 milyon TL oldu."]
    assert sections["results"] == ["Proje riskli görülüyor."]
    assert sections["important"] == ["Ekip yeni ofise taşındı."]


def test_summary_sections_without_highlights_falls_back_to_full_text():
    summary = "Sadece düz metin, başlık yok."
    sections = summary_sections(summary)
    assert sections["overview"] == summary
    assert sections["highlights"] == []


def test_clean_summary_text_strips_source_parentheses():
    text = "Bütçe %20 arttı. _(Kaynak: s. 3 · destek %80)_ Devam metni."
    assert clean_summary_text(text) == "Bütçe %20 arttı. Devam metni."


def test_clean_summary_text_collapses_whitespace():
    assert clean_summary_text("Çoklu   boşluk\n\nvar.") == "Çoklu boşluk var."


def test_concise_overview_limits_sentence_count():
    text = " ".join(f"Cümle {i}." for i in range(1, 8))
    result = concise_overview(text, limit=3)
    assert result == "Cümle 1. Cümle 2. Cümle 3."


def test_numeric_facts_returns_deduped_value_list():
    items = ["Bütçe 45 milyon TL'den 58 milyon TL'ye yükseldi."]
    assert numeric_facts(items) == ["45 milyon → 58 milyon"]


def test_numeric_facts_skips_items_without_numbers():
    assert numeric_facts(["Sayı içermeyen bir cümle."]) == []


def test_numeric_facts_keeps_word_range_as_digits():
    items = ["Sağlıklı bir koloni için km² başına en fazla üç ila dört kovan önerilir."]
    assert numeric_facts(items) == ["3-4 kovan"]


def test_numeric_facts_prefers_unit_value_over_bare_year():
    items = ["Bakanlık 2021 yılında kovanların en az 30 metre uzakta olmasını önerdi."]
    assert numeric_facts(items) == ["30 metre"]


def test_numeric_facts_renders_change_with_arrow():
    items = ["Kayıtlı kovan sayısı 2008'de 1.500 iken 2013'te 3.500'ü aşmıştır."]
    assert numeric_facts(items) == ["1.500 → 3.500"]


def test_numeric_facts_does_not_join_unrelated_numbers():
    items = ["Kılavuz 2021'de yayımlandı ve 30 metrelik bir kural getirdi."]
    assert numeric_facts(items) == ["30 metre"]


def test_numeric_facts_deduplicates_identical_values():
    items = ["Bütçe %20 arttı.", "Katılım %20 arttı."]
    assert numeric_facts(items) == ["%20"]


def test_numeric_facts_skips_year_only_items():
    assert numeric_facts(["Londra'daki artış 2008 krizinin ardından hızlandı."]) == []


def test_numeric_facts_ignores_year_range_prefers_real_change():
    items = [
        "Kovan sayısı 2008 ile 2013 yılları arasında 1.500 seviyesinden 3.500'ün üzerine çıkmıştır."
    ]
    assert numeric_facts(items) == ["1.500 → 3.500"]


_LONG_OVERVIEW = (
    "Kayıtlı kovan sayısı 1.500 seviyesinden 3.500'ün üzerine çıkmıştır. "
    "Şehir merkezleri 2 ila 3 derece daha sıcaktır. "
    "Kılavuz kovanların en az 30 metre uzakta olmasını önerir."
)


def test_numeric_chips_mines_overview_and_highlights():
    highlights = ["Sağlıklı koloni için km² başına üç ila dört kovan gerekir."]
    chips = numeric_chips(_LONG_OVERVIEW, highlights, source_length=6000)
    assert chips == ["1.500 → 3.500", "2-3 derece", "30 metre", "3-4 kovan"]


def test_numeric_chips_hidden_for_short_documents():
    assert numeric_chips(_LONG_OVERVIEW, [], source_length=1800) == []


def test_numeric_chips_hidden_when_fewer_than_three_values():
    overview = "Bütçe 45 milyon TL'den 58 milyon TL'ye yükseldi."
    assert numeric_chips(overview, [], source_length=6000) == []


def test_error_detail_extracts_backend_message():
    response = Mock()
    response.json.return_value = {"detail": "Özetlenecek metin boş olamaz."}
    error = requests.exceptions.RequestException()
    error.response = response
    assert error_detail(error) == "Özetlenecek metin boş olamaz."


def test_error_detail_falls_back_to_str_without_response():
    error = requests.exceptions.RequestException("bağlantı hatası")
    assert error_detail(error) == "bağlantı hatası"


def test_meeting_notes_includes_summary():
    result = meeting_notes("Kısa özet metni.")
    assert "Kısa özet metni." in result
    assert "Toplantı Notu" in result


def test_email_draft_includes_summary():
    result = email_draft("Kısa özet metni.")
    assert "Kısa özet metni." in result
    assert "Konu: Belge özeti" in result
