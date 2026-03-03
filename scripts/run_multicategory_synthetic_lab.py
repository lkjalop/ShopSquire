#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.synthetic_reco_lab import (
    seed_multicategory_catalog,
    seed_synthetic_interactions,
    evaluate_recommendation_behavior,
)
from src.app.services.recommendation_als import train_recommend_als


def main() -> None:
    ap = argparse.ArgumentParser(description="Synthetic recommendation lab for laptops/fashion/homewares.")
    ap.add_argument("--categories", default="laptops,fashion,homewares", help="Comma separated categories.")
    ap.add_argument("--per-category", type=int, default=80)
    ap.add_argument("--users", type=int, default=45)
    ap.add_argument("--interactions-per-user", type=int, default=35)
    ap.add_argument("--days-back", type=int, default=90)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--skip-clear", action="store_true")
    ap.add_argument("--skip-als-train", action="store_true")
    ap.add_argument("--output", default="docs/synthetic_reco_lab_report.json")
    args = ap.parse_args()

    cats = [c.strip().lower() for c in str(args.categories or "").split(",") if c.strip()]
    seed_out = seed_multicategory_catalog(
        include_categories=cats,
        per_category=max(5, int(args.per_category or 80)),
        clear_existing_synthetic=not bool(args.skip_clear),
    )
    inter_out = seed_synthetic_interactions(
        users=max(5, int(args.users or 45)),
        interactions_per_user=max(8, int(args.interactions_per_user or 35)),
        days_back=max(7, int(args.days_back or 90)),
        seed=int(args.seed or 1337),
    )
    als_out = {"status": "skipped"}
    if not args.skip_als_train:
        als_out = train_recommend_als(
            lookback_days=max(30, int(args.days_back or 90)),
            topk_per_user=80,
            factors=12,
            iters=6,
        )
    eval_out = evaluate_recommendation_behavior(top_n=5)

    report = {
        "seed_catalog": seed_out,
        "seed_interactions": inter_out,
        "als_training": als_out,
        "evaluation": eval_out,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "ok", "report": str(out_path), "overall_precision": eval_out.get("overall_precision")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
