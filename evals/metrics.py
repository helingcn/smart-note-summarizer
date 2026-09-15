from __future__ import annotations

import re
from difflib import SequenceMatcher
from statistics import mean
from typing import Any

from backend.summarizer import _best_source, _tokens

from .schemas import EvaluationCase, EvaluationDataset

_UP = {"arttı", "artış", "artarak", "yükseldi", "yükseliş", "büyüdü"}
_DOWN = {"azaldı", "azalış", "azalarak", "düştü", "düşüş", "geriledi"}
_NEGATIONS = {"değil", "yok", "olmadı", "bulunmuyor", "gerçekleşmedi"}
_SEMANTIC_ROOT_GROUPS = (
    ("dijital", "teknoloj"),
    ("altyap", "kapasit"),
    ("güçlen", "geliş"),
    ("hedef", "plan"),
)
_MAGNITUDES = {
    "bin": 1_000,
    "milyon": 1_000_000,
    "milyar": 1_000_000_000,
}
_NUMBER_WORDS = {
    "sıfır": 0,
    "bir": 1,
    "iki": 2,
    "üç": 3,
    "dört": 4,
    "beş": 5,
    "altı": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
}
_NUMBER_RE = re.compile(
    r"(?<![\w])(?P<number>\d{1,3}(?:[. ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(?P<magnitude>bin|milyon|milyar)?",
    flags=re.IGNORECASE,
)
_PERCENT_TERMS = ("%", "yüzde", "oran")
_CURRENCY_TERMS = ("tl", "try", "₺", "dolar", "usd", "$", "euro", "eur", "€")
_DATE_TERMS = ("yıl", "yılı", "yılında", "tarih", "dönem")


def _numeric_values(text: str) -> set[str]:
    """Tek haneli değerler dahil, karşılaştırılabilir sayıları döndürür."""
    return {value.replace(",", ".") for value in re.findall(r"\d+(?:[.,]\d+)?", text)}


def _parse_number(raw: str, magnitude: str | None = None) -> float:
    compact = raw.replace(" ", "")
    if "," in compact:
        compact = compact.replace(".", "").replace(",", ".")
    elif compact.count(".") > 1 or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", compact):
        compact = compact.replace(".", "")
    value = float(compact)
    return value * _MAGNITUDES.get((magnitude or "").lower(), 1)


def _number_mentions(text: str) -> list[tuple[float, str, str | None]]:
    mentions = [
        (
            _parse_number(match.group("number"), match.group("magnitude")),
            match.group(0),
            match.group("magnitude"),
        )
        for match in _NUMBER_RE.finditer(text)
    ]
    for word, value in _NUMBER_WORDS.items():
        mentions.extend(
            (float(value), match.group(0), None)
            for match in re.finditer(rf"\b{word}\b", text.lower())
        )
    mentions.extend(
        (2.0, match.group(0), None)
        for match in re.finditer(r"\bII\.?\s+Dünya\s+Savaşı", text, flags=re.IGNORECASE)
    )
    return mentions


def _expected_numeric_value(value: str, context: str = "") -> float:
    match = _NUMBER_RE.search(value)
    if match is None:
        raise ValueError(f"Sayısal değer çözümlenemedi: {value!r}")
    magnitude = match.group("magnitude")
    if magnitude is None:
        magnitude_match = re.search(r"\b(bin|milyon|milyar)\b", context, flags=re.IGNORECASE)
        magnitude = magnitude_match.group(1) if magnitude_match else None
    return _parse_number(match.group("number"), magnitude)


def _same_number(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-9, abs(left) * 1e-9)


def _number_kind(value: float, value_text: str, context: str) -> str:
    combined = f"{value_text} {context}".lower()
    if "%" in combined or re.search(r"\b(?:yüzde|oran)\b", combined):
        return "percentage"
    if any(symbol in combined for symbol in ("₺", "$", "€")) or re.search(
        r"\b(?:tl|try|dolar|usd|euro|eur)\b", combined
    ):
        return "currency"
    if any(term in combined for term in _DATE_TERMS) or 1900 <= value <= 2100:
        return "date"
    return "number"


def _claim_has_kind(claim: str, kind: str) -> bool:
    lowered = claim.lower()
    if kind == "percentage":
        return "%" in lowered or bool(re.search(r"\b(?:yüzde|oran)\b", lowered))
    if kind == "currency":
        return any(symbol in lowered for symbol in ("₺", "$", "€")) or bool(
            re.search(r"\b(?:tl|try|dolar|usd|euro|eur)\b", lowered)
        )
    return True


def _numeric_claim_result(
    summary: str, value: str, context: str, direction: str | None
) -> dict[str, Any]:
    """Sayıyı değer, tür, bağlam ve yönüyle denetleyip açıklanabilir sonuç döndürür."""
    expected = _expected_numeric_value(value, context)
    kind = _number_kind(expected, value, context)
    value_claims: list[str] = []
    for claim in _summary_claims(summary):
        if not any(_same_number(found, expected) for found, _, _ in _number_mentions(claim)):
            continue
        value_claims.append(claim)
        if not _claim_has_kind(claim, kind):
            continue
        if _ratio(context, claim) < 0.45:
            continue
        if not _direction_present(claim.lower(), direction):
            continue
        return {
            "matched": True,
            "value": value,
            "normalized_value": expected,
            "kind": kind,
            "context": context,
            "direction": direction,
            "matched_claim": claim,
            "reason": "Değer, tür, bağlam ve yön aynı iddiada eşleşti.",
        }
    reason = (
        "Beklenen değer özette bulunamadı."
        if not value_claims
        else "Değer bulundu ancak tür, bağlam veya yön aynı iddiada eşleşmedi."
    )
    return {
        "matched": False,
        "value": value,
        "normalized_value": expected,
        "kind": kind,
        "context": context,
        "direction": direction,
        "candidate_claims": value_claims,
        "reason": reason,
    }


def _numeric_claim_matches(summary: str, value: str, context: str, direction: str | None) -> bool:
    return bool(_numeric_claim_result(summary, value, context, direction)["matched"])


def _ratio(expected: str, actual: str) -> float:
    left, right = set(_tokens(expected)), set(_tokens(actual))
    if not left:
        return 1.0 if expected.strip() == actual.strip() else 0.0
    return len(left & right) / len(left)


def _direction_present(text: str, direction: str | None) -> bool:
    if not direction:
        return True
    tokens = set(_tokens(text))
    expected = _UP if direction == "up" else _DOWN
    opposite = _DOWN if direction == "up" else _UP
    return bool(tokens & expected) and not bool(tokens & opposite)


def _direction(text: str) -> str | None:
    tokens = set(_tokens(text))
    has_up, has_down = bool(tokens & _UP), bool(tokens & _DOWN)
    if has_up == has_down:
        return None
    return "up" if has_up else "down"


def _local_negation_mismatch(claim: str, evidence: str) -> bool:
    """Yalnızca olumsuzluk ortak bir kavramın hemen yanındaysa çelişki sayar."""
    claim_tokens = _tokens(claim)
    evidence_tokens = _tokens(evidence)
    shared = set(claim_tokens) & set(evidence_tokens)
    if not shared:
        return False

    def negated_shared(tokens: list[str]) -> set[str]:
        result: set[str] = set()
        for index, token in enumerate(tokens):
            if token not in _NEGATIONS:
                continue
            result.update(item for item in tokens[max(0, index - 2) : index + 3] if item in shared)
        return result

    return bool(negated_shared(claim_tokens) ^ negated_shared(evidence_tokens))


def _semantic_tokens(text: str) -> set[str]:
    tokens = set(_tokens(text))
    expanded = set(tokens)
    for index, roots in enumerate(_SEMANTIC_ROOT_GROUPS):
        if any(any(token.startswith(root) for root in roots) for token in tokens):
            expanded.add(f"semantic_{index}")
    return expanded


def _fallback_source(claim: str, source_text: str) -> tuple[int | None, int, str, float] | None:
    """BM25 hiç aday bulamadığında sınırlı eş anlam/kök örtüşmesiyle belirsiz aday üretir."""
    claim_tokens = _semantic_tokens(claim)
    best: tuple[int | None, int, str, float] | None = None
    page: int | None = None
    paragraph_index = 0
    for raw_line in source_text.splitlines():
        marker = re.fullmatch(r"\s*\[Sayfa\s+(\d+)\]\s*", raw_line, flags=re.IGNORECASE)
        if marker:
            page = int(marker.group(1))
            continue
        evidence = raw_line.strip()
        if not evidence:
            continue
        paragraph_index += 1
        overlap = claim_tokens & _semantic_tokens(evidence)
        semantic_overlap = sum(token.startswith("semantic_") for token in overlap)
        if semantic_overlap < 2:
            continue
        score = 100 * len(overlap) / max(1, len(claim_tokens))
        if best is None or score > best[3]:
            best = (page, paragraph_index, evidence, score)
    return best


def _claim_support(claim: str, source_text: str, semantic: bool = False) -> dict[str, Any]:
    """Bir iddiayı kaynak adayıyla destek, çelişki ve belirsizlik açısından sınıflandırır."""
    source = _best_source(claim, source_text)
    used_fallback = False
    if source is None:
        source = _fallback_source(claim, source_text)
        used_fallback = source is not None
    if source is None:
        return {
            "claim": claim,
            "status": "source_not_found",
            "reason": "İlgili kaynak parçası bulunamadı.",
        }

    page, paragraph, evidence, lexical_score = source
    claim_numbers = {value for value, _, _ in _number_mentions(claim)}
    source_without_page_markers = re.sub(r"\[Sayfa\s+\d+\]", "", source_text, flags=re.IGNORECASE)
    document_numbers = {value for value, _, _ in _number_mentions(source_without_page_markers)}
    missing_numbers = sorted(
        value
        for value in claim_numbers
        if not any(_same_number(value, item) for item in document_numbers)
    )
    claim_direction, evidence_direction = _direction(claim), _direction(evidence)

    status, reason = "supported", "Kaynakla yeterli sözcük ve olgu eşleşmesi var."
    if missing_numbers:
        status, reason = "contradicted", f"İddiadaki sayı kaynak adayında yok: {missing_numbers}."
    elif claim_direction and evidence_direction and claim_direction != evidence_direction:
        status, reason = "contradicted", "Artış/azalış yönü kaynakla ters."
    elif lexical_score >= 35 and _local_negation_mismatch(claim, evidence):
        status, reason = "contradicted", "Olumlu/olumsuz anlam kaynakla ters."
    elif used_fallback or lexical_score < 35:
        status, reason = (
            "uncertain",
            "Kaynak adayı ilgili ancak destek düzeyi karar vermek için düşük.",
        )

    result = {
        "claim": claim,
        "status": status,
        "reason": reason,
        "source_page": page,
        "source_paragraph": paragraph,
        "lexical_score": lexical_score,
        "evidence": evidence,
    }
    if semantic and status in {"uncertain", "source_not_found"}:
        try:
            from backend.semantic_verifier import verify_claim_semantically

            semantic_result = verify_claim_semantically(claim, source_text)
            semantic_status = semantic_result.get("status", "uncertain")
            confidence = float(semantic_result.get("confidence", 0.0))
            # Düşük güvenli model kararları kararsız kalır. Deterministik çelişki
            # kararları bu katmana hiç gönderilmediği için model onları ezemez.
            result["semantic_status"] = semantic_status
            result["semantic_confidence"] = confidence
            result["semantic_reason"] = semantic_result.get("reason", "")
            if confidence >= 0.72 and semantic_status in {"supported", "contradicted"}:
                result["status"] = semantic_status
                result["reason"] = f"Anlamsal doğrulama: {semantic_result.get('reason', '')}"
                selected = semantic_result.get("evidence")
                if selected is not None:
                    result["source_page"] = selected.page
                    result["source_paragraph"] = selected.paragraph
                    result["evidence"] = selected.text
        except Exception as exc:  # API/bağlantı hatası değerlendirmeyi durdurmamalı.
            result["semantic_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _summary_claims(summary: str) -> list[str]:
    claims: list[str] = []
    for raw_line in summary.splitlines():
        line = re.sub(r"_\(Kaynak:.*?\)_", "", raw_line).strip(" -*\t")
        if len(line) < 12 or line.startswith("#"):
            continue
        # "2. Dünya Savaşı" ve benzeri sıra/yıl ifadelerini cümle sınırı sanma.
        parts = re.split(r"(?<!\d\.)(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ\[])", line)
        claims.extend(part.strip() for part in parts if len(part.strip()) >= 12)
    return claims


def _page_from_source(source: str) -> int | None:
    match = re.search(r"Sayfa\s+(\d+)", source, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = _tokens(reference), _tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    matcher = SequenceMatcher(a=ref, b=hyp)
    matches = sum(block.size for block in matcher.get_matching_blocks())
    return min(1.0, (max(len(ref), len(hyp)) - matches) / len(ref))


def evaluate_case(
    case: EvaluationCase, fact_threshold: float = 0.55, semantic: bool = False
) -> dict[str, Any]:
    summary = case.candidate.summary
    fact_scores = [
        max((_ratio(fact.text, claim) for claim in _summary_claims(summary)), default=0.0)
        for fact in case.expected_facts
    ]
    fact_coverage = mean(score >= fact_threshold for score in fact_scores) if fact_scores else None

    numeric_details = [
        _numeric_claim_result(summary, item.value, item.context, item.direction)
        for item in case.expected_numbers
    ]
    number_results = [item["matched"] for item in numeric_details]

    claims = _summary_claims(summary)
    claim_support = [_claim_support(claim, case.source_text, semantic=semantic) for claim in claims]
    status_counts = {
        status: sum(item["status"] == status for item in claim_support)
        for status in ("supported", "contradicted", "source_not_found", "uncertain")
    }
    claim_count = len(claim_support)

    qa_by_question = {item.get("question", ""): item for item in case.candidate.qa}
    qa_answer_scores, qa_source_hits = [], []
    for expected in case.expected_qa:
        actual = qa_by_question.get(expected.question, {})
        qa_answer_scores.append(_ratio(expected.answer, actual.get("answer", "")))
        if expected.source_pages:
            pages = {
                page
                for source in actual.get("sources", [])
                if (page := _page_from_source(str(source))) is not None
            }
            qa_source_hits.append(bool(pages & set(expected.source_pages)))

    ocr_wer = None
    if case.ocr_reference is not None and case.candidate.ocr_text is not None:
        ocr_wer = _word_error_rate(case.ocr_reference, case.candidate.ocr_text)

    return {
        "id": case.id,
        "title": case.title,
        "fact_coverage": fact_coverage,
        "fact_scores": [round(score, 4) for score in fact_scores],
        "numeric_accuracy": mean(number_results) if number_results else None,
        "numeric_details": numeric_details,
        "supported_claim_rate": status_counts["supported"] / claim_count if claim_count else None,
        "contradicted_claim_rate": status_counts["contradicted"] / claim_count
        if claim_count
        else None,
        "source_not_found_rate": status_counts["source_not_found"] / claim_count
        if claim_count
        else None,
        "uncertain_claim_rate": status_counts["uncertain"] / claim_count if claim_count else None,
        "unsupported_claim_rate": (
            status_counts["contradicted"] + status_counts["source_not_found"]
        )
        / claim_count
        if claim_count
        else None,
        "claim_support": claim_support,
        "qa_answer_coverage": mean(score >= fact_threshold for score in qa_answer_scores)
        if qa_answer_scores
        else None,
        "qa_source_page_hit_rate": mean(qa_source_hits) if qa_source_hits else None,
        "ocr_word_error_rate": ocr_wer,
        "latency_seconds": case.candidate.latency_seconds,
    }


def _average(results: list[dict[str, Any]], key: str) -> float | None:
    values = [result[key] for result in results if result[key] is not None]
    return mean(values) if values else None


def evaluate_dataset(dataset: EvaluationDataset, semantic: bool = False) -> dict[str, Any]:
    cases = [evaluate_case(case, semantic=semantic) for case in dataset.cases]
    keys = (
        "fact_coverage",
        "numeric_accuracy",
        "supported_claim_rate",
        "contradicted_claim_rate",
        "source_not_found_rate",
        "uncertain_claim_rate",
        "unsupported_claim_rate",
        "qa_answer_coverage",
        "qa_source_page_hit_rate",
        "ocr_word_error_rate",
        "latency_seconds",
    )
    return {
        "dataset": dataset.name,
        "version": dataset.version,
        "case_count": len(cases),
        "semantic_verification": semantic,
        "aggregate": {key: _average(cases, key) for key in keys},
        "cases": cases,
        "limitations": [
            "Kapsam ölçümü sözcük örtüşmesine dayanır; anlamsal doğruluğun kanıtı değildir.",
            "Destek sınıflandırması BM25, sayı, yön ve olumsuzluk kontrollerini birleştirir; anlamsal model veya insan değerlendirmesinin yerini tutmaz.",
        ],
    }
