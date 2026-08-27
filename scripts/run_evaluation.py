#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.metrics import evaluate_dataset  # noqa: E402
from evals.reporting import write_reports  # noqa: E402
from evals.schemas import EvaluationDataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="SmartDigest altın veri değerlendirmesini çalıştırır.")
    parser.add_argument("dataset", type=Path, help="Değerlendirme JSON dosyası")
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "reports" / "latest")
    parser.add_argument(
        "--semantic", action="store_true",
        help="Kararsız iddialarda Gemini embedding + NLI doğrulamasını etkinleştirir.",
    )
    args = parser.parse_args()
    report = evaluate_dataset(EvaluationDataset.load(args.dataset), semantic=args.semantic)
    json_path, markdown_path = write_reports(report, args.output)
    print(f"{report['case_count']} belge değerlendirildi.")
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
