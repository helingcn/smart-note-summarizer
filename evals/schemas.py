from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExpectedFact:
    text: str
    source_pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExpectedNumber:
    value: str
    context: str
    direction: str | None = None


@dataclass(frozen=True)
class ExpectedQA:
    question: str
    answer: str
    source_pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class CandidateOutput:
    summary: str
    qa: tuple[dict[str, Any], ...] = ()
    ocr_text: str | None = None
    latency_seconds: float | None = None


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    title: str
    source_text: str
    expected_facts: tuple[ExpectedFact, ...]
    expected_numbers: tuple[ExpectedNumber, ...] = ()
    expected_qa: tuple[ExpectedQA, ...] = ()
    ocr_reference: str | None = None
    candidate: CandidateOutput = field(default_factory=lambda: CandidateOutput(summary=""))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationCase":
        expected = data.get("expected", {})
        candidate = data.get("candidate", {})
        return cls(
            id=data["id"],
            title=data.get("title", data["id"]),
            source_text=data.get("source_text", ""),
            expected_facts=tuple(
                ExpectedFact(item["text"], tuple(item.get("source_pages", [])))
                for item in expected.get("facts", [])
            ),
            expected_numbers=tuple(
                ExpectedNumber(
                    str(item["value"]), item["context"], item.get("direction")
                )
                for item in expected.get("numbers", [])
            ),
            expected_qa=tuple(
                ExpectedQA(
                    item["question"], item["answer"], tuple(item.get("source_pages", []))
                )
                for item in expected.get("qa", [])
            ),
            ocr_reference=expected.get("ocr_reference"),
            candidate=CandidateOutput(
                summary=candidate.get("summary", ""),
                qa=tuple(candidate.get("qa", [])),
                ocr_text=candidate.get("ocr_text"),
                latency_seconds=candidate.get("latency_seconds"),
            ),
        )


@dataclass(frozen=True)
class EvaluationDataset:
    name: str
    version: str
    cases: tuple[EvaluationCase, ...]

    @classmethod
    def load(cls, path: str | Path) -> "EvaluationDataset":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            name=data.get("name", Path(path).stem),
            version=str(data.get("version", "1")),
            cases=tuple(EvaluationCase.from_dict(case) for case in data["cases"]),
        )
