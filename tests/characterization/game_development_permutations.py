"""Model-backed game-development workload diagnostics.

This is a classification/capability harness, not relevance ground truth. It verifies that
audience context does not weaken workload requirements, primary products satisfy the resolved
floor, and explicit budgets remain authoritative. Product quality still belongs to sealed labels.

Run serially because all cases share the local Ollama deployment::

    python tests/characterization/game_development_permutations.py --output tmp/game_dev.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker

from src.app.models.db import get_engine
from src.app.services.recommendation_core.core import recommend_turn
from src.app.services.recommendation_core.envelope import TurnEnvelope


@dataclass(frozen=True)
class Case:
    key: str
    query: str
    workload: str = "game_development"
    context: Optional[str] = None
    budget_max: float = 3000
    expects_dedicated_floor: bool = True
    also_use_cases: Tuple[str, ...] = ()
    expected_variant: Optional[str] = None


CASES = (
    Case("professional", "I build commercial games in Unreal Engine 5 and Blender for paid client work; laptop under $3500", expected_variant="unreal_realtime"),
    Case("university", "I'm at university studying game development using Unreal and Blender; laptop under $2500", context="university", expected_variant="unreal_realtime"),
    Case("short_course", "I am taking a short game-development course using Unity for small 3D projects; laptop under $1800", expected_variant="unity_course"),
    Case("two_d", "I develop lightweight 2D games in Godot, no 3D rendering; laptop under $1200", expects_dedicated_floor=False, expected_variant="two_d_light"),
    Case("unreal", "Laptop for complex Unreal Engine 5 game development and shader compilation under $3200", expected_variant="unreal_realtime"),
    Case("rendering", "I build games and render Blender scenes on the same laptop, budget $3000", expected_variant="offline_rendering"),
    Case("vr", "I develop and test VR games in Unity and Unreal; laptop budget $3500", expected_variant="vr_development"),
    Case("local_ai", "Laptop for developing games and running local AI tools for textures and NPC prototypes, budget $3500", expected_variant="local_ai_tools"),
)


def run() -> dict:
    db = sessionmaker(bind=get_engine())()
    rows = []
    try:
        for case in CASES:
            env = TurnEnvelope.from_suggest_params(
                query=case.query,
                uid=f"game-dev-{case.key}",
                tenant_id="default",
                budget_max=case.budget_max,
            )
            started = time.perf_counter()
            response = recommend_turn(db, env)
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            intent = dict(response.extras.get("intent") or {})
            decision = dict(response.extras.get("decision") or {})
            requirements = dict((response.extras.get("constraints_used") or {}).get("requirements") or {})
            product_rows = [product.as_dict() for product in response.products]
            shelf = dict(response.extras.get("shelf") or {})
            bands = list(shelf.get("bands") or [])
            primary_skus = {
                str(sku) for band in bands if band.get("id") == "best_fit"
                for sku in (band.get("skus") or [])
            }
            primary_rows = [row for row in product_rows if str(row.get("sku")) in primary_skus]
            workload_cases = list(intent.get("workload_use_cases") or [])
            context_cases = list(intent.get("context_use_cases") or [])
            variants = dict(intent.get("use_case_variants") or {})
            product_failures = [
                row["sku"] for row in primary_rows
                if ((row.get("workload_fit") or {}).get("overall") not in (None, "meets"))
            ]
            over_budget = [
                row["sku"] for row in primary_rows
                if row.get("price_cents") is not None
                and int(row["price_cents"]) > int(case.budget_max * 100)
            ]
            gpu_predicates = requirements.get("gpu_vram_gb") or []
            has_gpu_floor = any(str(op) in (">", ">=") and float(value) > 0
                                for op, value in gpu_predicates)
            errors = []
            if case.workload not in workload_cases:
                errors.append("workload_not_resolved")
            for expected in case.also_use_cases:
                if expected not in workload_cases:
                    errors.append(f"secondary_workload_not_resolved:{expected}")
            if case.context and case.context not in context_cases:
                errors.append(f"context_not_resolved:{case.context}")
            if case.expected_variant and variants.get(case.workload) != case.expected_variant:
                errors.append(f"specialization_not_resolved:{case.expected_variant}")
            if case.expects_dedicated_floor and not has_gpu_floor:
                errors.append("dedicated_graphics_floor_missing")
            if not case.expects_dedicated_floor and has_gpu_floor:
                errors.append("unexpected_dedicated_graphics_floor")
            if product_failures:
                errors.append("primary_contains_capability_failure")
            if over_budget:
                errors.append("primary_contains_over_budget_product")
            rows.append({
                "key": case.key,
                "query": case.query,
                "lane": response.lane,
                "node_handle": decision.get("node_handle"),
                "routing_source": decision.get("source"),
                "latency_ms": elapsed,
                "workload_use_cases": workload_cases,
                "context_use_cases": context_cases,
                "use_case_variants": variants,
                "requirements": requirements,
                "has_dedicated_graphics_floor": has_gpu_floor,
                "products": product_rows,
                "shelf_bands": [{"id": band.get("id"), "skus": band.get("skus") or []}
                                for band in bands],
                "recommendation_outcome": ("best_fit" if primary_skus else
                                           (str(bands[0].get("id")) if bands else "delegated")),
                "evidence": response.extras.get("evidence") or {},
                "errors": errors,
                "specialization_resolution": variants.get(case.workload) or "unresolved",
            })
            print(f"{case.key}: {response.lane} {elapsed:.0f}ms errors={errors}", flush=True)
    finally:
        db.close()
    return {
        "meta": {
            "purpose": "classification and capability diagnostics, not relevance labels",
            "cases": len(rows),
            "specialization_contract": "model selects a registry value; router and resolver clamp it",
        },
        "summary": {
            "passed": sum(not row["errors"] for row in rows),
            "failed": sum(bool(row["errors"]) for row in rows),
            "error_counts": {
                error: sum(error in row["errors"] for row in rows)
                for error in sorted({item for row in rows for item in row["errors"]})
            },
        },
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="tmp/game_development_permutations.json")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()
    report = run()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(output), **report["summary"]}), flush=True)
    return 1 if args.fail_on_error and report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
