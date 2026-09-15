from evals.metrics import evaluate_case, evaluate_dataset
from evals.schemas import EvaluationCase, EvaluationDataset


def case(candidate_summary: str, direction: str = "down") -> EvaluationCase:
    return EvaluationCase.from_dict(
        {
            "id": "report",
            "source_text": "[Sayfa 1]\nGelir yüzde 20 azalarak 8 milyon TL oldu.\n\n[Sayfa 2]\nEnerji maliyeti temel risktir.",
            "expected": {
                "facts": [{"text": "Gelir yüzde 20 azaldı.", "source_pages": [1]}],
                "numbers": [{"value": "20", "context": "gelir", "direction": direction}],
                "qa": [
                    {"question": "Risk nedir?", "answer": "Enerji maliyeti", "source_pages": [2]}
                ],
            },
            "candidate": {
                "summary": candidate_summary,
                "qa": [
                    {
                        "question": "Risk nedir?",
                        "answer": "Enerji maliyeti",
                        "sources": ["Sayfa 2, paragraf 1"],
                    }
                ],
            },
        }
    )


def test_complete_supported_summary_scores_well():
    result = evaluate_case(case("- Gelir yüzde 20 azaldı."))
    assert result["fact_coverage"] == 1
    assert result["numeric_accuracy"] == 1
    assert result["qa_source_page_hit_rate"] == 1


def test_wrong_direction_fails_numeric_accuracy():
    result = evaluate_case(case("- Gelir yüzde 20 arttı."))
    assert result["numeric_accuracy"] == 0


def test_single_digit_expected_number_is_measured():
    result = evaluate_case(
        EvaluationCase.from_dict(
            {
                "id": "single-digit",
                "source_text": "[Sayfa 1]\nGelir 8 milyon TL oldu.",
                "expected": {
                    "facts": [],
                    "numbers": [{"value": "8", "context": "gelir milyon TL"}],
                },
                "candidate": {"summary": "- Gelir 8 milyon TL oldu."},
            }
        )
    )
    assert result["numeric_accuracy"] == 1


def numeric_case(value: str, context: str, summary: str, direction: str | None = None):
    return EvaluationCase.from_dict(
        {
            "id": "numeric",
            "source_text": "",
            "expected": {
                "facts": [],
                "numbers": [
                    {
                        "value": value,
                        "context": context,
                        "direction": direction,
                    }
                ],
            },
            "candidate": {"summary": summary},
        }
    )


def test_turkish_decimal_comma_matches_decimal_point():
    result = evaluate_case(
        numeric_case("45,5", "faaliyet gideri yüzde", "- Faaliyet gideri yüzde 45.5 oldu.")
    )
    assert result["numeric_accuracy"] == 1


def test_magnitude_word_is_normalized():
    result = evaluate_case(
        numeric_case("12 milyon", "uygulama indirme", "- Uygulama indirme sayısı 12.000.000 oldu.")
    )
    assert result["numeric_accuracy"] == 1


def test_turkish_number_word_matches_digit():
    result = evaluate_case(
        numeric_case(
            "3",
            "stratejik plan temel eksen",
            "- Stratejik plan üç temel eksen üzerine kurulmuştur.",
        )
    )
    assert result["numeric_accuracy"] == 1


def test_same_number_in_wrong_context_does_not_match():
    result = evaluate_case(
        numeric_case(
            "12 milyon",
            "uygulama indirme",
            "- Video 12 milyon kez görüntülendi.\n- Uygulama indirme sayısı 8 milyon oldu.",
        )
    )
    assert result["numeric_accuracy"] == 0


def test_direction_is_checked_in_same_claim_as_number():
    result = evaluate_case(
        numeric_case(
            "20",
            "gelir yüzde",
            "- Gelir yüzde 20 arttı.\n- Maliyet azaldı.",
            direction="down",
        )
    )
    assert result["numeric_accuracy"] == 0


def test_percentage_requires_percentage_unit():
    result = evaluate_case(numeric_case("20", "gelir yüzde", "- Gelir 20 milyon TL oldu."))
    assert result["numeric_accuracy"] == 0


def test_currency_requires_currency_unit():
    result = evaluate_case(numeric_case("8", "gelir milyon TL", "- Gelir 8 kişi arttı."))
    assert result["numeric_accuracy"] == 0


def test_numeric_details_explain_missing_value():
    result = evaluate_case(
        numeric_case(
            "1965",
            "Igor Ansoff Corporate Strategy",
            "- Alfred Chandler 1962 yılında çalışmasını yayımladı.",
        )
    )
    detail = result["numeric_details"][0]
    assert detail["matched"] is False
    assert detail["kind"] == "date"
    assert detail["reason"] == "Beklenen değer özette bulunamadı."


def test_compound_overview_is_split_into_independent_claims():
    result = evaluate_case(
        EvaluationCase.from_dict(
            {
                "id": "sentences",
                "source_text": "[Sayfa 1]\nKurum iki anlama sahiptir.\n\n[Sayfa 2]\nPlanlama 1980'lerde önem kazandı.",
                "expected": {"facts": []},
                "candidate": {
                    "summary": "Kurum iki anlama sahiptir. Planlama 1980'lerde önem kazandı."
                },
            }
        )
    )
    assert len(result["claim_support"]) == 2


def test_second_world_war_is_not_split_after_number():
    result = evaluate_case(
        EvaluationCase.from_dict(
            {
                "id": "war",
                "source_text": "[Sayfa 1]\n2. Dünya Savaşı sonrasında planlama gelişti.",
                "expected": {"facts": []},
                "candidate": {"summary": "2. Dünya Savaşı sonrasında planlama gelişti."},
            }
        )
    )
    assert len(result["claim_support"]) == 1
    assert result["claim_support"][0]["claim"].startswith("2. Dünya Savaşı")


def test_name_containing_tl_is_not_currency():
    result = evaluate_case(
        numeric_case(
            "1962", "Alfred Chandler strateji", "- Alfred Chandler 1962 yılında kitabını yayımladı."
        )
    )
    assert result["numeric_details"][0]["kind"] == "date"


def test_unrelated_source_negation_does_not_create_contradiction():
    result = evaluate_case(
        EvaluationCase.from_dict(
            {
                "id": "negation-scope",
                "source_text": "[Sayfa 1]\nKurum öncü çalışmalar yapan sıradan değil, aranan bir üniversitedir.",
                "expected": {"facts": []},
                "candidate": {"summary": "Kurum öncü çalışmalar yapmayı hedeflemektedir."},
            }
        )
    )
    assert result["contradicted_claim_rate"] == 0


def test_fabricated_claim_is_reported_as_unsupported():
    result = evaluate_case(case("- Şirket Mars'ta yeni bir fabrika açtı."))
    assert result["unsupported_claim_rate"] == 1


def test_opposite_direction_is_classified_as_contradicted():
    result = evaluate_case(case("- Gelir yüzde 20 arttı."))
    assert result["contradicted_claim_rate"] == 1
    assert result["claim_support"][0]["status"] == "contradicted"


def test_low_overlap_related_claim_is_uncertain_not_unsupported():
    result = evaluate_case(
        EvaluationCase.from_dict(
            {
                "id": "uncertain",
                "source_text": "[Sayfa 1]\nKurum dijital altyapısını güçlendirmeyi hedeflemektedir.",
                "expected": {"facts": []},
                "candidate": {
                    "summary": "- Teknolojik kapasitenin geliştirilmesi planlanmaktadır."
                },
            }
        )
    )
    assert result["contradicted_claim_rate"] == 0
    assert result["uncertain_claim_rate"] == 1
    assert result["unsupported_claim_rate"] == 0


def test_number_in_second_source_sentence_does_not_create_false_contradiction():
    result = evaluate_case(
        EvaluationCase.from_dict(
            {
                "id": "compound",
                "source_text": "[Sayfa 1]\nArşiv 12 milyon indirildi. Bilim Genç 45,5 milyon görüntülendi.",
                "expected": {"facts": []},
                "candidate": {
                    "summary": "- Arşiv 12 milyon indirilirken Bilim Genç 45,5 milyon görüntülendi."
                },
            }
        )
    )
    assert result["contradicted_claim_rate"] == 0


def test_page_number_is_not_treated_as_source_fact():
    result = evaluate_case(
        EvaluationCase.from_dict(
            {
                "id": "page-marker",
                "source_text": "[Sayfa 45]\nŞirket yeni bir tesis açtı.",
                "expected": {"facts": []},
                "candidate": {"summary": "- Şirket 45 yeni tesis açtı."},
            }
        )
    )
    assert result["contradicted_claim_rate"] == 1


def test_dataset_aggregates_cases():
    dataset = EvaluationDataset("test", "1", (case("- Gelir yüzde 20 azaldı."),))
    report = evaluate_dataset(dataset)
    assert report["case_count"] == 1
    assert report["aggregate"]["numeric_accuracy"] == 1
