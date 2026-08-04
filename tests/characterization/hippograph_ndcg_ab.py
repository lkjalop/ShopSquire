"""Offline Hippograph shadow A/B over the independently judged recommendation slates.

This evaluates the existing legacy score-nudge experiment. V2 uses lexicographic ranking and does
not enroll graph evidence; a non-positive result therefore keeps Hippograph evidence-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.app.services.ranking_nudge import apply_experiment_nudge
from src.app.services.recommendation_core.quality import ndcg_at_k


LABELS = ROOT / "tests" / "golden" / "relevance_labels.json"
CORPUS = ROOT / "tests" / "golden" / "suggest_corpus"


def evaluate() -> Dict[str, Any]:
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    rows = []
    for case_key, entry in labels.get("cases", {}).items():
        case_id, turn_text = case_key.rsplit(":", 1)
        case = json.loads((CORPUS / f"{case_id}.json").read_text(encoding="utf-8"))
        response = case["turns"][int(turn_text)]["response"]
        products = [dict(row) for row in response.get("products") or []]
        recalled = [
            str(item.get("id"))
            for item in response.get("hippograph_insights_shadow") or []
            if item.get("kind") == "product" and item.get("id")
        ]
        baseline = [str(row.get("sku")) for row in products if row.get("sku")]
        treatment_rows = apply_experiment_nudge(
            products, recall_ids=recalled, assignment="treatment", live=True
        )
        treatment = [str(row.get("sku")) for row in treatment_rows if row.get("sku")]
        grades = entry.get("labels") or {}
        before = ndcg_at_k(baseline, grades)
        after = ndcg_at_k(treatment, grades)
        rows.append({
            "case_id": case_key,
            "baseline_ndcg_at_10": before,
            "shadow_on_ndcg_at_10": after,
            "delta": round(after - before, 4),
            "recalled_products_in_slate": len(set(baseline) & set(recalled)),
            "positions_changed": sum(a != b for a, b in zip(baseline, treatment)),
        })
    count = max(1, len(rows))
    baseline_avg = sum(row["baseline_ndcg_at_10"] for row in rows) / count
    treatment_avg = sum(row["shadow_on_ndcg_at_10"] for row in rows) / count
    return {
        "label_review_status": labels.get("review_status"),
        "human_reviewed_by": labels.get("human_reviewed_by"),
        "provisional": labels.get("human_reviewed_by") in (None, ""),
        "cases": rows,
        "summary": {
            "cases": len(rows),
            "baseline_ndcg_at_10": round(baseline_avg, 4),
            "shadow_on_ndcg_at_10": round(treatment_avg, 4),
            "delta": round(treatment_avg - baseline_avg, 4),
            "cases_with_position_changes": sum(bool(row["positions_changed"]) for row in rows),
            "decision": "keep_evidence_only" if treatment_avg <= baseline_avg else "eligible_for_review",
        },
        "scope": "recorded legacy slates; V2 lexicographic ranker remains unenrolled",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate()
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
