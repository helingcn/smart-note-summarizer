from summarizer import _best_source, _bm25_scores, _passages, build_summary_evidence


DOCUMENT = """[Sayfa 1]
Şirketin personel sayısı bu yıl 240 kişiye yükseldi.

[Sayfa 2]
Toplam harcama 3 milyon TL, yıllık bütçe ise 4 milyon TL olarak açıklandı.
"""


def test_bm25_finds_synonym_and_page():
    passages = _passages(DOCUMENT)
    scores = _bm25_scores("maliyet ne kadar", passages)
    assert scores[1] > scores[0]


def test_numeric_claim_without_source_number_has_low_support():
    source = _best_source("Toplam harcama 9 milyon TL oldu.", DOCUMENT)
    assert source is not None
    assert source[0] == 2
    assert source[3] <= 25


def test_build_summary_evidence_returns_page_quote_and_status():
    summary = """### Özet
Kurumun toplam harcaması 7 milyon TL oldu.

### Öne çıkanlar
- [Önemli] Gelir yüzde 20 arttı. _(Kaynak: s. 2 · destek %80)_
"""
    source = """[Sayfa 1]
Kurumun toplam harcaması 7 milyon TL oldu.
[Sayfa 2]
Şirketin geliri yüzde 20 arttı.
"""
    items = build_summary_evidence(summary, source)
    assert len(items) == 2
    assert items[0]["page"] == 1
    assert "7 milyon TL" in items[0]["quote"]
    assert items[1]["page"] == 2
    assert "Kaynak:" not in items[1]["claim"]
    assert items[1]["status"] in {"supported", "review", "weak"}
