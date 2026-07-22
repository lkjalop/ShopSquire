"""Four-mode proof harness for model contribution and deterministic authorization.

This is not a benchmark of prose. It asks two narrower questions:
1. Does a live model improve semantic routing over bounded fallback and a weak proposal?
2. Can malformed but parseable model output escape the platform clamps?

Usage:
  python tests/characterization/agentic_ablation.py --only search_university
  python tests/characterization/agentic_ablation.py --modes live,deterministic,weak,adversarial
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy.orm import sessionmaker

from src.app.models.db import get_engine
from src.app.services.recommendation_core.core import recommend_turn
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.quality import catalog_authorization

CORPUS_DIR = REPO_ROOT / "tests" / "golden" / "suggest_corpus"
MODES = ("live", "deterministic", "weak", "adversarial")


def _llm_for(mode: str):
    if mode == "live":
        return None
    if mode == "deterministic":
        return lambda _prompt, _timeout: ""
    if mode == "weak":
        return lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH", "handle": None, "requirements": {}, "use_cases": [],
            "audience_contexts": [], "quantity": None, "total_budget": None,
            "budget_scope": None, "subject_action": "uncertain",
            "procurement_context": "none",
        })
    if mode == "adversarial":
        return lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH", "handle": "invented-root-node",
            "requirements": {"invented_spec": [">=", 999999], "ram_gb": [">=", 999999]},
            "use_cases": ["invented_workload"], "audience_contexts": ["invented_persona"],
            "refine": {"brand": "Invented Brand", "exclude_brand": "Invented Brand"},
            "quantity": 999999999, "total_budget": -100, "budget_scope": "unbounded",
            "subject_action": "delete", "procurement_context": "auto_send",
        })
    raise ValueError(f"unsupported mode: {mode}")


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="run one corpus case id")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    modes = tuple(value.strip() for value in args.modes.split(",") if value.strip())
    unknown = set(modes) - set(MODES)
    if unknown:
        raise SystemExit(f"unknown modes: {sorted(unknown)}")

    db = sessionmaker(bind=get_engine())()
    rows = []
    try:
        for path in sorted(CORPUS_DIR.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            if args.only and case.get("id") != args.only:
                continue
            for mode in modes:
                session = {}
                for turn in case.get("turns") or []:
                    params = (turn.get("request") or {}).get("params") or {}
                    envelope = TurnEnvelope.from_suggest_params(
                        query=str(params.get("query") or ""),
                        uid=f"ablation-{mode}-{case['id']}-{turn['turn']}",
                        tenant_id="default", budget_min=params.get("budget_min"),
                        budget_max=params.get("budget_max"), session=dict(session),
                    )
                    started = time.perf_counter()
                    core = recommend_turn(db, envelope, llm_fn=_llm_for(mode))
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    decision = dict((core.extras or {}).get("decision") or {})
                    shown = [product.sku for product in core.products]
                    auth = catalog_authorization(db, shown, tenant_id="default")
                    unauthorized = list(auth.get("unauthorized") or [])
                    row = {
                        "mode": mode, "case_id": case["id"], "turn": turn["turn"],
                        "lane": core.lane, "source": decision.get("source"),
                        "latency_ms": round(latency_ms, 1), "product_count": len(shown),
                        "unauthorized": unauthorized,
                        "authorization_changes": decision.get("authorization_changes") or [],
                        "clarification_count": len(core.clarify),
                    }
                    rows.append(row)
                    print(json.dumps(row, separators=(",", ":")), flush=True)
    finally:
        db.close()

    summary = {}
    for mode in modes:
        selected = [row for row in rows if row["mode"] == mode]
        latencies = [float(row["latency_ms"]) for row in selected]
        summary[mode] = {
            "turns": len(selected),
            "p50_ms": round(statistics.median(latencies), 1) if latencies else 0.0,
            "p95_ms": round(_p95(latencies), 1),
            "fallbacks": sum(1 for row in selected if str(row.get("source") or "").startswith("fallback:")),
            "turns_with_products": sum(1 for row in selected if row["product_count"] > 0),
            "unauthorized_products": sum(len(row["unauthorized"]) for row in selected),
            "clamp_interventions": sum(
                1 for row in selected
                if any(str(value).endswith(":clamped") for value in row["authorization_changes"])
            ),
            "default_fills": sum(
                1 for row in selected
                if any(str(value).endswith(":defaulted") for value in row["authorization_changes"])
            ),
        }
    result = {"summary": summary, "rows": rows}
    print(json.dumps({"summary": summary}, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
