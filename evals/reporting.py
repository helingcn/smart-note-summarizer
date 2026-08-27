from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LABELS = {
    "fact_coverage": "Önemli bilgi kapsamı",
    "numeric_accuracy": "Sayısal doğruluk",
    "supported_claim_rate": "Desteklenen iddia oranı",
    "contradicted_claim_rate": "Çelişen iddia oranı",
    "source_not_found_rate": "Kaynak bulunamayan iddia oranı",
    "uncertain_claim_rate": "Kararsız iddia oranı",
    "unsupported_claim_rate": "Desteksiz iddia oranı",
    "qa_answer_coverage": "Soru-cevap kapsamı",
    "qa_source_page_hit_rate": "Kaynak sayfa isabeti",
    "ocr_word_error_rate": "OCR kelime hata oranı",
    "latency_seconds": "Ortalama işlem süresi",
}


def _display(key: str, value: float | None) -> str:
    if value is None:
        return "—"
    if key == "latency_seconds":
        return f"{value:.2f} sn"
    return f"%{value * 100:.1f}"


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# SmartDigest değerlendirme raporu — {report['dataset']}",
        "",
        f"Sürüm: `{report['version']}` · Belge sayısı: **{report['case_count']}**",
        "",
        "## Genel sonuçlar",
        "",
        "| Metrik | Sonuç |",
        "|---|---:|",
    ]
    for key, value in report["aggregate"].items():
        lines.append(f"| {LABELS[key]} | {_display(key, value)} |")
    lines.extend(["", "## Belge sonuçları", ""])
    for case in report["cases"]:
        lines.extend([
            f"### {case['title']} (`{case['id']}`)", "",
            f"- Önemli bilgi kapsamı: {_display('fact_coverage', case['fact_coverage'])}",
            f"- Sayısal doğruluk: {_display('numeric_accuracy', case['numeric_accuracy'])}",
            f"- Desteklenen iddia oranı: {_display('supported_claim_rate', case['supported_claim_rate'])}",
            f"- Çelişen iddia oranı: {_display('contradicted_claim_rate', case['contradicted_claim_rate'])}",
            f"- Kaynak bulunamayan iddia oranı: {_display('source_not_found_rate', case['source_not_found_rate'])}",
            f"- Kararsız iddia oranı: {_display('uncertain_claim_rate', case['uncertain_claim_rate'])}",
            f"- Desteksiz iddia oranı: {_display('unsupported_claim_rate', case['unsupported_claim_rate'])}",
            f"- Soru-cevap kapsamı: {_display('qa_answer_coverage', case['qa_answer_coverage'])}",
            f"- Kaynak sayfa isabeti: {_display('qa_source_page_hit_rate', case['qa_source_page_hit_rate'])}",
            f"- OCR kelime hata oranı: {_display('ocr_word_error_rate', case['ocr_word_error_rate'])}",
            "",
        ])
        if case.get("claim_support"):
            lines.extend(["#### İddia denetimi", ""])
            for item in case["claim_support"]:
                source = f"s. {item['source_page']}" if item.get("source_page") else "kaynak yok"
                lines.append(f"- **{item['status']}** ({source}, %{item.get('lexical_score', 0)}): {item['claim']} — {item['reason']}")
            lines.append("")
        if case.get("numeric_details"):
            lines.extend(["#### Sayısal denetim", ""])
            for item in case["numeric_details"]:
                state = "eşleşti" if item["matched"] else "eksik/eşleşmedi"
                lines.append(
                    f"- **{state}** · `{item['value']}` · {item['kind']} · "
                    f"{item['context']} — {item['reason']}"
                )
            lines.append("")
    lines.extend(["## Yöntem sınırları", ""] + [f"- {item}" for item in report["limitations"]])
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path, markdown_path = target / "report.json", target / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, markdown_path
