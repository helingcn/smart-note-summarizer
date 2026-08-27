import json

import semantic_verifier
from semantic_verifier import _cosine, verify_evidence_batch


def test_cosine_similarity():
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_handles_empty_vectors():
    assert _cosine([], [1.0]) == 0.0


def test_batch_verification_promotes_supported_claim(monkeypatch):
    class Models:
        @staticmethod
        def generate_content(**kwargs):
            return type(
                "Response",
                (),
                {
                    "text": json.dumps(
                        {"judgments": [{"index": 1, "status": "supported", "confidence": 0.91}]}
                    )
                },
            )()

    monkeypatch.setattr(
        semantic_verifier, "_client", lambda: type("Client", (), {"models": Models()})()
    )
    evidence = [
        {
            "claim": "Gelir arttı.",
            "page": 1,
            "paragraph": 1,
            "quote": "Şirketin geliri arttı.",
            "support": 40,
            "status": "review",
        }
    ]
    result = verify_evidence_batch(evidence, "kaynak")
    assert result[0]["status"] == "supported"
    assert result[0]["verification"] == "semantic"
    assert result[0]["confidence"] == 0.91
