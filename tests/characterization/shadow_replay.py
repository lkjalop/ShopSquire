"""Shadow replay runner: contract/safety characterization plus legacy-difference diagnostics.

Replays every recorded corpus turn through recommendation_core (live model + live DB) and
diffs against the RECORDED legacy characterization (no API needed). Cases
tagged known_wrong score on their expect_v2 assertions; everything else scores on parity via
recommend_parity_full. The output is the promotion scorecard (summarize_run gates) plus a
divergence census — the DIVERGENCES ARE THE DELIVERABLE at this stage: every MAJOR/BLOCKER
is either a v2 gap to fix, or v1 behavior to tag known_wrong. Product-set identity remains a
diagnostic rather than a promotion oracle. Nothing gets to hide.

Like-for-like: the adapter emits the SHAPE the oracle recorded (response_shape of v1) so the
diff measures the core, not the fork emulation.

Limitations recorded, not hidden: multi-turn cases replay STATELESS (core has no session
memory yet — divergences on turn-2 cases are expected and listed); narration prose is not
compared (class-level only, by design).

Usage (repo root, Ollama up): python tests/characterization/shadow_replay.py [--only CASE_ID]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy.orm import sessionmaker

from src.app.contracts.suggest_contract import response_shape
from src.app.models.db import get_engine
from src.app.services.recommend_parity_full import evaluate_case, message_class, summarize_run
from src.app.services.recommendation_core.core import recommend_turn
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.legacy_adapter import SHAPES, to_legacy
from src.app.services.recommendation_core.quality import (
    catalog_authorization,
    evaluate_case_quality,
    load_labels,
    summarize_quality,
)

CORPUS_DIR = REPO_ROOT / "tests" / "golden" / "suggest_corpus"
BATTERY = REPO_ROOT / "tests" / "characterization" / "batteries" / "starter_battery.json"


def _product_expectations(battery: list[dict]) -> dict[tuple[str, int], bool]:
    """Return immutable product expectations keyed by case and turn."""
    return {
        (str(case["id"]), turn_index): bool(turn["expects_products"])
        for case in battery
        for turn_index, turn in enumerate(case.get("turns") or [])
        if "expects_products" in turn
    }


def _decision_slice(core):
    """The routed decision breadcrumbs the metrics need (node + requirements). Returns None when
    the breadcrumbs are ABSENT (degraded response) — callers must treat that differently from a
    present decision whose node is None."""
    try:
        dec = core.extras.get("decision")
        return dec if isinstance(dec, dict) else None
    except Exception:
        return None


def _expects_products(core) -> bool:
    """THE one expects-products decision (R8.1 — was duplicated in _quality_case/_diagnose_case).
    A product-lane, non-refusal turn expects products — EXCEPT a turn the core could not ground
    AT ALL (decision recorded, no routed node AND no resolved requirements): that is off-domain
    ('pizza place near me') and its empty answer is HONESTY, not a failure. Bounded deliberately:
    a NODE-ROUTED empty (accessory_bag → Laptop Sleeves) still counts, and MISSING breadcrumbs
    (degraded response) count too — the exclusion fails CLOSED and can never mask a routing,
    retrieval, or degradation miss; only a query the whole taxonomy has no home for."""
    if core.lane not in ("SEARCH", "FILTER", "COMPARE") or core.off_catalog:
        return False
    # A named comparison proven to cross the settlement-currency boundary must clarify
    # rather than emit a one-card pseudo-comparison. That honest gate is not an empty slate.
    if isinstance(getattr(core, "extras", None), dict) and core.extras.get("compare_currency_conflict"):
        return False
    dec = _decision_slice(core)
    if dec is None:
        return True   # no breadcrumbs = can't prove off-domain = count the empty
    ungroundable = dec.get("node_handle") is None and not (dec.get("requirements") or {})
    return not ungroundable


def _quality_case(case_id: str, req: dict, core) -> dict:
    """Case metadata the intrinsic quality gate needs (P1.2).

    ``expects_products`` is an immutable battery assertion when supplied. Inferring the
    relevance denominator from model output lets a clarification remove its own case from
    coverage, making identical labels report different coverage across sealed runs.
    """
    bmax = req.get("budget_max")
    return {"id": case_id,
            "budget_max": (float(bmax) if bmax not in (None, "") else None),
            "expects_products": (
                bool(req["expects_products"])
                if "expects_products" in req else _expects_products(core)
            )}


def _diagnose_case(case_id: str, turn: int, query: str, core, v2: dict) -> dict:
    """Per-turn fit decomposition (review-7 #2): what the constraint-satisfaction number is MADE
    OF — each shown product's overall verdict + which requirement keys were unknown (missing
    catalog spec) vs failed (genuinely below the requirement). This is the read that says whether
    39% is a DATA gap (unknown-dominated) or a RETRIEVAL/RANKING gap (fails-dominated)."""
    try:
        reqs = (core.extras.get("constraints_used") or {}).get("requirements") or {}
    except Exception:
        reqs = {}
    products = []
    for p in (v2.get("products") or []):
        fit = p.get("workload_fit") or {}
        products.append({"sku": p.get("sku"), "price": p.get("price"),
                         "overall": fit.get("overall"),
                         "per_key": fit.get("per_key") or {},
                         "unknown_keys": fit.get("unknown_keys") or []})
    dec = _decision_slice(core)
    return {"case_id": case_id, "turn": turn, "query": query[:140], "lane": core.lane,
            # node_handle recorded (R8.4 gap: its absence cost a live probe round to recover
            # routing when reading the empties)
            "node_handle": dec.get("node_handle"), "node_path": dec.get("node_path"),
            "requirements": reqs, "products": products, "shown": len(products),
            "empty": _expects_products(core) and not products}


def _aggregate_diagnosis(rows: list) -> dict:
    """Roll the per-case fit detail into the decomposition of constraint-satisfaction. Dominance
    is judged at the PRODUCT-VERDICT level (review-8: key-occurrence totals aren't comparable —
    one product contributes many unknown keys). Also flags likely price-bleed requirements and
    all-unknown products (a wrong-category proxy — e.g. pharmacy in a laptop query)."""
    verdicts = {"meets": 0, "unknown": 0, "fails": 0}
    unknown_keys: dict = {}
    failed_keys: dict = {}
    empties = 0
    all_unknown_products = 0        # every requirement unknown → probably WRONG CATEGORY
    price_bleed_reqs = 0           # requirement copied from an explicit currency amount
    for r in rows:
        if r.get("empty"):
            empties += 1
        import re
        query = str(r.get("query") or "")
        currency_values = {
            float(v.replace(",", ""))
            for v in re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", query)
        }
        for k, spec in (r.get("requirements") or {}).items():
            if k in ("storage_gb", "ram_gb"):
                for op, thr in (spec if isinstance(spec, list) else [spec]):
                    # A 1 TB storage floor is valid. The historical bug copied
                    # "$1800" into storage_gb; flag only a threshold equal to an
                    # explicit currency value in this turn.
                    if float(thr) in currency_values:
                        price_bleed_reqs += 1
        for p in r.get("products", []):
            ov = p.get("overall")
            if ov in verdicts:
                verdicts[ov] += 1
            per_key = p.get("per_key") or {}
            if per_key and all(v is None for v in per_key.values()):
                all_unknown_products += 1
            for k in (p.get("unknown_keys") or []):
                unknown_keys[k] = unknown_keys.get(k, 0) + 1
            for k, v in per_key.items():
                if v is False:
                    failed_keys[k] = failed_keys.get(k, 0) + 1
    tot = sum(verdicts.values())
    # PRODUCT-level dominance — the comparable signal
    read = ("RETRIEVAL/RANKING gap — more products FAIL a requirement than are UNKNOWN "
            "(present but below the requirement)"
            if verdicts["fails"] >= verdicts["unknown"]
            else "DATA gap — more products are UNKNOWN than fail (missing catalog spec)")
    if verdicts["fails"] == 0 and verdicts["unknown"] == 0:
        dominance = "none"
        read = "No fit gap in this run: every measured product met its requirements"
    elif verdicts["fails"] > verdicts["unknown"]:
        dominance = "fails"
    elif verdicts["unknown"] > verdicts["fails"]:
        dominance = "unknown"
    else:
        dominance = "mixed"
        read = "Mixed fit gap: failed and unknown requirement verdicts are equally common"
    if all_unknown_products > tot * 0.25:
        read += " | WRONG-CATEGORY suspected (many all-unknown products — check reroute/retrieval)"
    if price_bleed_reqs:
        read += f" | {price_bleed_reqs} suspected PRICE-BLEED requirement(s)"
    return {"verdicts": verdicts, "verdict_total": tot,
            "constraint_sat": round(verdicts["meets"] / tot, 4) if tot else None,
            "verdict_dominance": dominance,
            "all_unknown_products": all_unknown_products,
            "price_bleed_reqs": price_bleed_reqs,
            "top_unknown_keys": sorted(unknown_keys.items(), key=lambda x: -x[1])[:10],
            "top_failed_keys": sorted(failed_keys.items(), key=lambda x: -x[1])[:10],
            "empty_cases": empties, "cases": len(rows), "read": read}


# the lanes the facade actually serves from the core; everything else is delegated to legacy
# BY DESIGN, so in --facade-mode a non-core lane is scored as 'DELEGATED' (intended), not a
# V2 parity failure (M1.3 — makes the census deployment-path faithful).
_CANARY_LANES = frozenset({"SEARCH", "FILTER", "COMPARE", "EXPLAIN", "OFF_CATALOG"})


def _merge_replay_session(prior: dict, core) -> dict:
    dec = _decision_slice(core) or {}
    used = core.extras.get("constraints_used") or {}
    out = dict(prior or {})
    if dec.get("node_handle"):
        out["prior_node"] = dec["node_handle"]
    shortlist = [card.sku for card in (core.products or [])][:12]
    if shortlist:
        out["shortlist_skus"] = shortlist
    accepted = dict(out.get("accepted_constraints") or {})
    for key, value in {
        "budget_min_cents": used.get("budget_min_cents"),
        "budget_max_cents": used.get("budget_max_cents"),
        "requirements": used.get("requirements") or dec.get("requirements"),
        "quantity": dec.get("quantity"),
        "total_budget_cents": dec.get("total_budget_cents"),
        "budget_scope": dec.get("budget_scope"),
        "exclude_brand": dec.get("exclude_brand"),
        "brand_filter": dec.get("brand_filter"),
        "preferred_brand": dec.get("preferred_brand"),
    }.items():
        if key == "budget_scope" and value in (None, "", "unknown"):
            continue
        if value is not None and value != {} and value != []:
            accepted[key] = value
    out["accepted_constraints"] = accepted
    return out


def _phase_telemetry(core, *, case_id: str, turn: int, total_latency_ms: float,
                     timed_out: bool, fallback_used: bool, model_mode: str) -> dict:
    """Expose non-overlapping attribution where the core can prove it.

    Retrieval is also included as a diagnostic sub-phase of the plan, so callers must not sum
    route + plan + retrieval. V2 narration is not enrolled yet and is reported as such rather
    than stamped with a misleading zero.
    """
    stages = []
    try:
        stages = [s.as_dict() for s in (core.stage_results or [])]
    except Exception:
        stages = []
    route_ms = sum(float(s.get("latency_ms") or 0.0) for s in stages
                   if str(s.get("stage") or "") == "route+intent")
    plan_ms = sum(float(s.get("latency_ms") or 0.0) for s in stages
                  if str(s.get("stage") or "").startswith("plan:"))
    post_ms = sum(float(s.get("latency_ms") or 0.0) for s in stages
                  if not str(s.get("stage") or "").startswith(("route+intent", "plan:")))
    evidence = {}
    narration = {}
    try:
        evidence = core.extras.get("evidence") or {}
        narration = core.extras.get("narration_telemetry") or {}
    except Exception:
        pass
    narration_ms = narration.get("latency_ms")
    narration_mode = str(narration.get("mode") or "not_enrolled")
    try:
        from src.app.services.recommendation_core.turn_router import last_router_call_metrics
        router_model = last_router_call_metrics()
    except Exception:
        router_model = {}
    return {
        "case_id": f"{case_id}:{turn}",
        "total_ms": round(float(total_latency_ms), 1),
        "route_intent_ms": round(route_ms, 1),
        "plan_ms": round(plan_ms, 1),
        "retrieval_ms": round(float(evidence.get("latency_ms") or 0.0), 1),
        "post_stage_ms": round(post_ms, 1),
        "narration_ms": (round(float(narration_ms), 1) if narration_ms is not None else None),
        "narration_mode": narration_mode,
        "timed_out": bool(timed_out),
        "fallback_used": bool(fallback_used),
        "model_mode": str(model_mode or "unknown"),
        "router_model": router_model,
        "stages": stages,
    }


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    return round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 1)


def _summarize_phase_telemetry(rows: list[dict]) -> dict:
    phase_keys = ("total_ms", "route_intent_ms", "plan_ms", "retrieval_ms", "post_stage_ms",
                  "narration_ms")
    narration_rows = [row for row in rows if row.get("narration_ms") is not None]
    return {
        "cases": len(rows),
        "p95_ms": {key: _p95([row[key] for row in rows if row.get(key) is not None])
                   for key in phase_keys},
        "timeouts": sum(1 for row in rows if row.get("timed_out")),
        "fallbacks": sum(1 for row in rows if row.get("fallback_used")),
        "fallback_p95_ms": _p95([row["total_ms"] for row in rows if row.get("fallback_used")]),
        "router_model_p95_ms": {
            key: _p95([float((row.get("router_model") or {}).get(key) or 0.0)
                       for row in rows if (row.get("router_model") or {}).get(key) is not None])
            for key in ("queue_ms", "wall_ms", "load_ms", "prompt_eval_ms", "decode_ms",
                        "provider_overhead_ms",
                        "taxonomy_repair_ms")
        },
        "router_outcomes": {
            outcome: sum(1 for row in rows
                         if str((row.get("router_model") or {}).get("outcome") or "unknown") == outcome)
            for outcome in sorted({str((row.get("router_model") or {}).get("outcome") or "unknown")
                                   for row in rows})
        },
        "model_modes": {
            mode: sum(1 for row in rows if row.get("model_mode") == mode)
            for mode in sorted({str(row.get("model_mode")) for row in rows})
        },
        "narration": {
            "measured": bool(narration_rows),
            "modes": {
                mode: sum(1 for row in rows if row.get("narration_mode") == mode)
                for mode in sorted({str(row.get("narration_mode") or "not_enrolled")
                                    for row in rows})
            },
            "p95_ms": _p95([row["narration_ms"] for row in narration_rows]),
        },
        "note": "retrieval_ms is contained within plan_ms and must not be added to total",
    }


def _research_observation(core, *, case_id: str, turn: int) -> dict:
    """Export governed research decisions without turning them into a quality gate.

    These fields need independently authored labels before precision, recall, calibration,
    or regret can be scored.  The replay therefore records the observation and its authority
    status, but does not infer ground truth from the system's own output.
    """
    extras = core.extras if isinstance(getattr(core, "extras", None), dict) else {}
    belief = extras.get("semantic_belief_state") or {}
    trigger = extras.get("research_trigger_shadow") or {}
    plan = extras.get("research_plan") or {}
    clarification = extras.get("clarification") or {}
    evidence = extras.get("evidence") or {}
    attempts = evidence.get("research_attempts") or []
    accepted = evidence.get("accepted_research_claims") or []
    return {
        "case_id": f"{case_id}:{turn}",
        "authority": "observer_only",
        "hypotheses": belief.get("hypotheses") or [],
        "material_unknowns": belief.get("material_unknowns") or [],
        "research_trigger": trigger,
        "query_bundle": plan.get("query_bundle") or [],
        "prohibited_assumptions": plan.get("prohibited_assumptions") or [],
        "research_attempts": attempts,
        "accepted_claim_count": len(accepted),
        "clarification": {
            "reason": clarification.get("reason"),
            "question_id": clarification.get("question_id"),
            "calibration_status": clarification.get("calibration_status"),
            "bounded_expected_value": clarification.get("bounded_expected_value"),
        },
    }


def _summarize_research_observations(rows: list[dict]) -> dict:
    trigger_states: dict[str, int] = {}
    recommendations: dict[str, int] = {}
    for row in rows:
        trigger = row.get("research_trigger") or {}
        state = str(trigger.get("state") or "not_observed")
        recommendation = str(trigger.get("recommendation") or "not_observed")
        trigger_states[state] = trigger_states.get(state, 0) + 1
        recommendations[recommendation] = recommendations.get(recommendation, 0) + 1
    return {
        "cases": len(rows),
        "authority": "observer_only",
        "trigger_states": trigger_states,
        "recommendations": recommendations,
        "research_attempted": sum(
            1 for row in rows if row.get("research_attempts")
        ),
        "accepted_claim_cases": sum(
            1 for row in rows if int(row.get("accepted_claim_count") or 0) > 0
        ),
        "clarifications": sum(
            1 for row in rows if (row.get("clarification") or {}).get("question_id")
        ),
        "labels_required_for_scoring": [
            "expected_hypotheses",
            "expected_research",
            "material_clarification",
            "accepted_claim_correctness",
            "product_relation",
        ],
    }


def _prewarm_models() -> dict:
    """Load local models before measurement and preserve setup as replay evidence."""
    started = time.monotonic()
    try:
        from types import SimpleNamespace

        from src.app.main import _prewarm_router_models

        app = SimpleNamespace(state=SimpleNamespace())
        result = dict(_prewarm_router_models(app))
    except Exception as exc:
        result = {"ready": False, "status": "failed", "error": str(exc)[:300]}
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000.0, 1)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--facade-mode", action="store_true",
                    help="score non-core lanes as DELEGATED-to-legacy (intended), not V2 fail — "
                         "reflects the real deployment path (facade lane gating)")
    ap.add_argument("--diagnose", action="store_true",
                    help="decompose constraint-satisfaction into meets/unknown/fails + the top "
                         "unknown vs failed requirement keys; write tmp/quality_diagnosis.json")
    ap.add_argument("--label-split", choices=("dev", "test"), default="test",
                    help="sealed relevance-label split used by the promotion gate (default: test)")
    ap.add_argument("--output", type=Path,
                    help="write the complete scorecard and divergence rows as JSON")
    ap.add_argument("--prewarm", action="store_true",
                    help="load router and taxonomy models before the measured sealed replay")
    args = ap.parse_args()

    prewarm = _prewarm_models() if args.prewarm else {"ready": None, "status": "not_requested"}
    if args.prewarm and not prewarm.get("ready"):
        raise SystemExit(f"sealed replay prewarm failed: {prewarm}")

    battery = json.loads(BATTERY.read_text(encoding="utf-8"))
    expects = {c["id"]: (c.get("known_wrong") or {}).get("expect_v2") for c in battery}
    product_expectations = _product_expectations(battery)

    labels = load_labels()   # sealed relevance labels (empty until filled — gate stays honest-red)
    s = sessionmaker(bind=get_engine())()
    results, rows, quality_rows, diag_rows, telemetry_rows, research_rows = [], [], [], [], [], []
    t_start = time.monotonic()
    try:
        for f in sorted(CORPUS_DIR.glob("*.json")):
            case = json.loads(f.read_text(encoding="utf-8"))
            if args.only and case["id"] != args.only:
                continue
            # STATEFUL REPLAY (R9.6 / P1.3): thread the session slice across a case's turns the
            # way postflight→facade does in production — turn 1's 'why is the first one better?'
            # now sees turn 0's shortlist/node/constraints instead of replaying stateless (the
            # gap that made every multi-turn case measure only its fragments).
            session: dict = {}
            for t in case["turns"]:
                req, v1 = t["request"]["params"], t.get("response") or {}
                bmax = req.get("budget_max")
                envelope = TurnEnvelope.from_suggest_params(
                    query=req.get("query", ""), uid=f"shadow-{case['id']}-{t['turn']}",
                    budget_max=(float(bmax) if bmax not in (None, "") else None),
                    session=dict(session))
                t0 = time.monotonic()
                model_call = {"timed_out": False, "error": None}

                def tracked_llm(prompt: str, timeout: float) -> str:
                    from src.app.services.recommendation_core.turn_router import _default_llm_fn
                    try:
                        return _default_llm_fn(prompt, timeout)
                    except Exception as exc:
                        model_call["error"] = type(exc).__name__
                        model_call["timed_out"] = "timeout" in type(exc).__name__.lower()
                        raise

                core = recommend_turn(s, envelope, llm_fn=tracked_llm)
                latency_ms = (time.monotonic() - t0) * 1000.0
                dec = _decision_slice(core) or {}
                used = {}
                try:
                    used = core.extras.get("constraints_used") or {}
                except Exception:
                    pass
                session = _merge_replay_session(session, core)
                shape = response_shape(v1)
                v2 = to_legacy(core, shape=shape if shape in SHAPES else "full_pipeline")
                expect = expects.get(case["id"]) if t["turn"] == 0 else None
                # M1.3: in facade-mode, a non-core lane is DELEGATED to legacy by the real
                # facade — score it as intended (delegated), not as a V2 parity failure.
                if args.facade_mode and core.lane not in _CANARY_LANES:
                    r = {"expected_change": False, "delegated": True, "severity": "DELEGATED",
                         "dimensions": {}, "identical_outcome": True}
                else:
                    r = evaluate_case(v1, v2, known_wrong_expect=expect)
                r["case_id"], r["turn"] = case["id"], t["turn"]
                results.append(r)
                # INTRINSIC QUALITY (P1.2): measure the SERVED turns (skip delegated lanes) so the
                # scorecard carries a real quality block + gates_pass instead of quality:null.
                if not r.get("delegated"):
                    # quality/label rows are keyed case_id:turn (review-7 #3): case-only keys
                    # collide a case's follow-up turns — relevance_labels.json uses these keys.
                    # SERVER-SIDE authorization (review-9 #2 + followup #A1/#A2/#A3): every shown
                    # sku verified against the catalog (exists/active/not-explicitly-unsold), with
                    # a MEASURED flag so a broken read fails the gate, and classification coverage.
                    # SAME evaluator the soak worker uses (one authorization source of truth).
                    shown = [str(p.get("sku")) for p in (v2.get("products") or [])
                             if isinstance(p, dict) and p.get("sku")]
                    authz = catalog_authorization(s, shown, tenant_id="default")
                    decision_source = str(dec.get("source") or "default")
                    fallback_used = (decision_source == "default"
                                     or decision_source.startswith("fallback:"))
                    quality_request = dict(req)
                    expected_products = product_expectations.get((case["id"], t["turn"]))
                    if expected_products is not None:
                        quality_request["expects_products"] = expected_products
                    quality_rows.append(evaluate_case_quality(
                        _quality_case(
                            f"{case['id']}:{t['turn']}", quality_request, core,
                        ), v2, labels,
                        catalog=authz, split=args.label_split, latency_ms=latency_ms,
                        timed_out=bool(model_call["timed_out"]),
                        fallback_used=fallback_used,
                        model_mode=decision_source))
                    telemetry_rows.append(_phase_telemetry(
                        core, case_id=case["id"], turn=t["turn"],
                        total_latency_ms=latency_ms, timed_out=bool(model_call["timed_out"]),
                        fallback_used=fallback_used, model_mode=decision_source))
                    research_rows.append(_research_observation(
                        core, case_id=case["id"], turn=t["turn"]
                    ))
                    if args.diagnose:
                        diag_rows.append(_diagnose_case(case["id"], t["turn"],
                                                        req.get("query", ""), core, v2))
                d = (r.get("diff") or r).get("dimensions", {})
                mismatched = [k for k, v in d.items() if not v.get("match")]
                rows.append((case["id"], t["turn"],
                             "EXPECTED" if r.get("expected_change") else r.get("severity"),
                             ("MET" if r.get("expectation_met") else "MISSED") if r.get("expected_change")
                             else f"{message_class(v1)}->{message_class(v2)}",
                             ",".join(mismatched)[:60], f"{time.monotonic()-t0:.1f}s"))
                print(
                    f"replay progress {len(rows):02d}: {case['id']}:{t['turn']} "
                    f"lane={core.lane} elapsed={time.monotonic()-t0:.1f}s",
                    flush=True,
                )
    finally:
        s.close()

    print(f"{'case':<26}{'t':<2}{'sev':<10}{'outcome':<34}{'mismatched dims':<62}{'sec'}")
    print("-" * 140)
    for r in rows:
        print(f"{r[0]:<26}{r[1]:<2}{r[2]:<10}{r[3]:<34}{r[4]:<62}{r[5]}")
    # the quality block is now REAL (review-6 #1/#9): gates_pass requires it to be measured AND
    # green; below the labeled-coverage floor it fails honestly (never quality:null → pass).
    quality = summarize_quality(quality_rows) if quality_rows else None
    score = summarize_run(results, quality=quality)
    print(f"\nSCORECARD ({time.monotonic()-t_start:.0f}s total): {json.dumps(score, indent=1)}")
    if quality is not None and not quality["gates"]["pass"]:
        print(f"QUALITY GATE: FAIL — {quality['gates']['failures']}")

    if args.diagnose and diag_rows:
        agg = _aggregate_diagnosis(diag_rows)
        # keyed by case_id:turn (review-8 #7) so follow-up turns don't collide with turn 0.
        keyed = {f"{r['case_id']}:{r['turn']}": r for r in diag_rows}
        out = REPO_ROOT / "tmp" / "quality_diagnosis.json"
        out.parent.mkdir(exist_ok=True)
        # WRITE the artifact FIRST (review-8: never lose the JSON to a console-encoding crash).
        out.write_text(json.dumps({"summary": agg, "cases": keyed}, indent=1), encoding="utf-8")
        v = agg["verdicts"]
        # ASCII-only output (review-8: Unicode box chars crashed under Windows CP1252).
        lines = [
            "",
            "-- CONSTRAINT-SATISFACTION DIAGNOSIS -------------------------------",
            f"  shown products with a verdict: {agg['verdict_total']} "
            f"(meets {v['meets']} / unknown {v['unknown']} / fails {v['fails']})",
            f"  constraint_sat = meets/total = {agg['constraint_sat']}  "
            f"[verdict dominance: {agg['verdict_dominance']}]",
            f"  all-unknown products (wrong-category proxy): {agg['all_unknown_products']}",
            f"  suspected price-bleed requirements: {agg['price_bleed_reqs']}",
            f"  empty cases (expected products, got 0): {agg['empty_cases']} / {agg['cases']}",
            f"  top UNKNOWN keys (missing spec / wrong category): {agg['top_unknown_keys']}",
            f"  top FAILED keys (present but below req):          {agg['top_failed_keys']}",
            f"  READ: {agg['read']}",
            f"  full per-product detail -> {out}",
        ]
        try:
            print("\n".join(lines))
        except Exception:
            # last-resort ascii-scrub if the console is even narrower than CP1252
            print("\n".join(s.encode("ascii", "replace").decode("ascii") for s in lines))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "scorecard": score,
            "quality": quality,
            "quality_cases": quality_rows,
            "divergences": results,
            "telemetry": _summarize_phase_telemetry(telemetry_rows),
            "telemetry_cases": telemetry_rows,
            "research_observations": _summarize_research_observations(research_rows),
            "research_cases": research_rows,
            "diagnosis": (_aggregate_diagnosis(diag_rows) if diag_rows else None),
            "prewarm": prewarm,
            "elapsed_seconds": round(time.monotonic() - t_start, 1),
        }, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
