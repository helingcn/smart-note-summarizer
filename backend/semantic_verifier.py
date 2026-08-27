from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from google.genai import types

try:
    from .summarizer import GEMINI_MODEL, _client, _passages
except ImportError:  # backend klasöründen doğrudan çalıştırılan testler
    from summarizer import GEMINI_MODEL, _client, _passages


EMBEDDING_MODEL = "gemini-embedding-001"


@dataclass(frozen=True)
class SemanticEvidence:
    page: int
    paragraph: int
    text: str
    similarity: float


def _vector(item: Any) -> list[float]:
    values = getattr(item, "values", None)
    return list(values or [])


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / denominator if denominator else 0.0


def retrieve_semantic_evidence(claim: str, source_text: str, limit: int = 3) -> list[SemanticEvidence]:
    passages = _passages(source_text)
    if not passages:
        return []
    response = _client().models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[claim, *(item[2] for item in passages)],
        config=types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=768,
        ),
    )
    embeddings = list(response.embeddings or [])
    if len(embeddings) != len(passages) + 1:
        return []
    claim_vector = _vector(embeddings[0])
    ranked = sorted(
        (
            SemanticEvidence(page, paragraph, text, _cosine(claim_vector, _vector(embedding)))
            for (page, paragraph, text), embedding in zip(passages, embeddings[1:])
        ),
        key=lambda item: item.similarity,
        reverse=True,
    )
    return ranked[:limit]


def judge_nli(claim: str, evidence: list[SemanticEvidence]) -> dict[str, Any]:
    if not evidence:
        return {"status": "source_not_found", "confidence": 0.0, "reason": "Anlamsal kaynak adayı bulunamadı."}
    context = "\n\n".join(
        f"[Kaynak {index} · Sayfa {item.page} · Paragraf {item.paragraph}]\n{item.text}"
        for index, item in enumerate(evidence, 1)
    )
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["supported", "contradicted", "uncertain"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
            "evidence_index": {"type": "integer", "minimum": 1, "maximum": len(evidence)},
        },
        "required": ["status", "confidence", "reason", "evidence_index"],
    }
    response = _client().models.generate_content(
        model=GEMINI_MODEL,
        contents=f"""Aşağıdaki iddianın yalnızca verilen kaynak parçalarından mantıksal olarak
çıkarılıp çıkarılamayacağını değerlendir. Aynı anlamın farklı kelimelerle ifade edilmesini
destek kabul et. Kaynağın söylemediği ayrıntıları destek kabul etme. Ters yön, ters olumsuzluk,
farklı özne veya farklı sayısal ilişki varsa contradicted seç. Kanıt yetersizse uncertain seç.

İDDİA:
{claim}

KAYNAKLAR:
{context}""",
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    result = json.loads(response.text or "{}")
    index = max(1, min(len(evidence), int(result.get("evidence_index", 1))))
    selected = evidence[index - 1]
    return {
        "status": result.get("status", "uncertain"),
        "confidence": float(result.get("confidence", 0.0)),
        "reason": str(result.get("reason", "Anlamsal karar açıklanmadı.")),
        "evidence": selected,
    }


def verify_claim_semantically(claim: str, source_text: str) -> dict[str, Any]:
    return judge_nli(claim, retrieve_semantic_evidence(claim, source_text))


def verify_evidence_batch(evidence: list[dict], source_text: str) -> list[dict]:
    """BM25 ile bulunan kanıtları tek NLI çağrısında anlamsal olarak değerlendirir.

    API geçici olarak kullanılamazsa mevcut leksik kanıtları korur; özetleme
    sonucunun yalnızca doğrulama servisindeki ikincil bir arıza yüzünden kaybolmasını
    önler. `source_text` imzası, ileride aday parçaları embedding ile genişletmek ve
    testlerde kaynağı açıkça izlemek için korunur.
    """
    if not evidence:
        return []
    items = evidence[:12]
    context = "\n\n".join(
        f"[İddia {index}]\nİddia: {item['claim']}\nKanıt: {item['quote']}"
        for index, item in enumerate(items, 1)
    )
    schema = {
        "type": "object",
        "properties": {
            "judgments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "minimum": 1, "maximum": len(items)},
                        "status": {
                            "type": "string",
                            "enum": ["supported", "contradicted", "uncertain"],
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["index", "status", "confidence"],
                },
            }
        },
        "required": ["judgments"],
    }
    try:
        response = _client().models.generate_content(
            model=GEMINI_MODEL,
            contents=f"""Her iddianın yalnızca yanında verilen kanıt parçasından mantıksal
olarak çıkarılıp çıkarılamayacağını değerlendir. Aynı anlamın farklı kelimelerle
ifadesini destek kabul et. Eksik ayrıntı, farklı özne/sayı/yön veya ters olumsuzluk
varsa contradicted; kanıt yetersizse uncertain seç. Kaynak dışı bilgi kullanma.

{context}""",
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=schema,
                http_options=types.HttpOptions(timeout=35_000),
            ),
        )
        judgments = {
            int(item["index"]): item for item in json.loads(response.text or "{}").get("judgments", [])
        }
    except Exception:
        return evidence

    output = []
    for index, item in enumerate(evidence, 1):
        judgment = judgments.get(index)
        if not judgment:
            output.append(item)
            continue
        semantic_status = judgment.get("status", "uncertain")
        confidence = float(judgment.get("confidence", 0))
        enriched = dict(item)
        enriched["verification"] = "semantic"
        enriched["confidence"] = confidence
        if semantic_status == "supported" and confidence >= 0.65:
            enriched["status"] = "supported"
        elif semantic_status == "contradicted":
            enriched["status"] = "weak"
        else:
            enriched["status"] = "review"
        output.append(enriched)
    return output
