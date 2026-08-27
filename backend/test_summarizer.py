from summarizer import (
    _drop_duplicate_highlights,
    _drop_incomplete_highlights,
    _drop_unverified_numbers,
    _numbers_in,
    bullet_limit,
    max_output_tokens,
    split_text,
    word_target,
)


# --- bullet_limit / word_target -------------------------------------------------

def test_bullet_limit_detailed_ignores_text_length():
    assert bullet_limit(500, "detailed") == 8
    assert bullet_limit(50_000, "detailed") == 8


def test_bullet_limit_balanced_scales_with_text_length():
    assert bullet_limit(500, "balanced") == 0
    assert bullet_limit(2_000, "balanced") == 3
    assert bullet_limit(5_000, "balanced") == 5
    assert bullet_limit(10_000, "balanced") == 7


def test_word_target_returns_min_below_max():
    for text_length in (500, 2_000, 5_000, 10_000):
        for length in ("balanced", "detailed"):
            min_words, max_words = word_target(text_length, length)
            assert min_words <= max_words


def test_word_target_detailed_ignores_text_length():
    assert word_target(500, "detailed") == word_target(50_000, "detailed")


# --- max_output_tokens ------------------------------------------------------

def test_max_output_tokens_grows_with_word_target():
    short_budget = max_output_tokens(2_000, "balanced")
    long_budget = max_output_tokens(10_000, "balanced")
    assert short_budget < long_budget


def test_max_output_tokens_has_a_safety_margin_over_word_count():
    _, max_words = word_target(5_000, "balanced")
    assert max_output_tokens(5_000, "balanced") > max_words


# --- _numbers_in / _drop_unverified_numbers ---------------------------------

def test_numbers_in_extracts_decimal_and_integer_numbers():
    assert _numbers_in("Oran yüzde 10,5 iken 2030'da 7 katına çıktı.") == {"10,5", "2030", "7"}


def test_drop_unverified_numbers_keeps_numbers_present_in_source():
    source = "Şirket 2024'te gelirlerini yüzde 17 artırdı."
    overview = "Şirket 2024'te gelirlerini yüzde 17 artırdı."
    highlights = ["[Önemli] Büyüme 2024'te yüzde 17 oldu."]
    clean_overview, clean_highlights = _drop_unverified_numbers(overview, highlights, source)
    assert "17" in clean_overview
    assert clean_highlights == highlights


def test_drop_unverified_numbers_masks_fabricated_number_in_overview():
    source = "Deniz seviyesi 1993'ten bu yana 10,5 santimetre yükseldi."
    overview = "Deniz seviyesi 1993'ten bu yana %4,25 arttı."
    clean_overview, _ = _drop_unverified_numbers(overview, [], source)
    assert "4,25" not in clean_overview
    assert "doğrulanamayan değer" in clean_overview


def test_drop_unverified_numbers_masks_fabricated_number_in_highlight():
    # Madde tamamen silinmez (aksi hâlde birden fazla madde aynı anda
    # şüpheli sayılırsa `highlights` tamamen boşalabilir); yalnızca sayı maskelenir.
    source = "Nestlé 2023'te 200 milyon Euro yatırım yaptı."
    highlights = ["[Detay] Nestlé 2023'te 350 milyon Euro yatırım yaptı."]
    _, clean_highlights = _drop_unverified_numbers("Genel bakış.", highlights, source)
    assert len(clean_highlights) == 1
    assert "350" not in clean_highlights[0]
    assert "doğrulanamayan değer" in clean_highlights[0]


def test_drop_unverified_numbers_ignores_single_digit_labels():
    # Tek haneli sayılar (madde numarası, sıralama vb.) kaynakta aranmaz.
    source = "Şirket üç yeni ürün duyurdu."
    highlights = ["[Detay] 3. çeyrekte satışlar arttı."]
    _, clean_highlights = _drop_unverified_numbers("Genel bakış.", highlights, source)
    assert clean_highlights == highlights


# --- _drop_duplicate_highlights ---------------------------------------------

def test_drop_duplicate_highlights_removes_near_verbatim_repeat():
    overview = "Bitki bazlı ürünler pazarı geleneksel hayvancılığa karşı büyüyor ancak maliyetler yüksek kalıyor."
    highlights = [
        "[Kritik] Bitki bazlı ürünler pazarı geleneksel hayvancılığa karşı büyüyor ancak maliyetler yüksek kalıyor.",
        "[Önemli] Oxford çalışması emisyonların yüzde 49 azalabileceğini gösteriyor.",
    ]
    result = _drop_duplicate_highlights(overview, highlights)
    assert len(result) == 1
    assert "Oxford" in result[0]


def test_drop_duplicate_highlights_keeps_distinct_items():
    overview = "Kısa bir genel bakış cümlesi."
    highlights = [
        "[Önemli] Tamamen farklı ve yeni bir bulgu burada anlatılıyor.",
        "[Detay] Başka bir kurumdan gelen ayrı bir bulgu daha var burada.",
    ]
    assert _drop_duplicate_highlights(overview, highlights) == highlights


# --- _drop_incomplete_highlights --------------------------------------------

def test_drop_incomplete_highlights_removes_unterminated_sentence():
    highlights = [
        "[Önemli] Şirket, işten çıkarma yerine 3.400 çalışanını yeni",
        "[Detay] Şirket yeniden eğitim programı başlattı.",
    ]
    result = _drop_incomplete_highlights(highlights)
    assert result == ["[Detay] Şirket yeniden eğitim programı başlattı."]


def test_drop_incomplete_highlights_keeps_sentences_ending_in_quotes_or_parens():
    highlights = [
        '[Detay] Şirket bunu "yavaşlayan talep" ile açıkladı.',
        "[Önemli] Yatırım planı açıklandı (2040 yılına kadar).",
    ]
    assert _drop_incomplete_highlights(highlights) == highlights


# --- split_text ---------------------------------------------------------------

def test_split_text_respects_chunk_size_boundary():
    text = " ".join(f"Cümle {i}." for i in range(200))
    chunks = split_text(text, chunk_size=200)
    assert all(len(chunk) <= 200 or " " not in chunk for chunk in chunks)


def test_split_text_reconstructs_all_sentences():
    text = "Birinci cümle. İkinci cümle. Üçüncü cümle."
    chunks = split_text(text, chunk_size=1000)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_text_handles_empty_string():
    assert split_text("") == []
