"""Shadow replay runner (Phase 5) — the first full parity picture.

Replays every recorded corpus turn through recommendation_core (live model + live DB) and
diffs against the RECORDED oracle response (no API needed — the oracle is the file). Cases
tagged known_wrong score on their expect_v2 assertions; everything else scores on parity via
recommend_parity_full. The output is the promotion scorecard (summarize_run gates) plus a
divergence census — the DIVERGENCES ARE THE DELIVERABLE at this stage: every MAJOR/BLOCKER
is either a v2 gap to fix, or v1 behavior to tag known_wrong. Nothing gets to hide.

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
    dec = _decision_slice(core)
    if dec is None:
        return True   # no breadcrumbs = can't prove off-domain = count the empty
    ungroundable = dec.get("node_handle") is None and not (dec.get("requirements") or {})
    return not ungroundable


def _quality_case(case_id: str, req: dict, core) -> dict:
    """Case metadata the intrinsic quality gate needs (P1.2). budget_max comes from the request."""
    bmax = req.get("budget_max")
    return {"id": case_id,
            "budget_max": (float(bmax) if bmax not in (None, "") else None),
            "expects_products": _expects_products(core)}


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
    price_bleed_reqs = 0           # storage_gb/ram_gb requirement with a suspiciously price-like value
    for r in rows:
        if r.get("empty"):
            empties += 1
        for k, spec in (r.get("requirements") or {}).items():
            if k in ("storage_gb", "ram_gb"):
                for op, thr in (spec if isinstance(spec, list) else [spec]):
                    if float(thr) >= 1000:      # >=1000 GB RAM / >=1000GB with no unit smells like a price
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
    if all_unknown_products > tot * 0.25:
        read += " | WRONG-CATEGORY suspected (many all-unknown products — check reroute/retrieval)"
    if price_bleed_reqs:
        read += f" | {price_bleed_reqs} suspected PRICE-BLEED requirement(s)"
    return {"verdicts": verdicts, "verdict_total": tot,
            "constraint_sat": round(verdicts["meets"] / tot, 4) if tot else None,
            "verdict_dominance": ("fails" if verdicts["fails"] >= verdicts["unknown"] else "unknown"),
            "all_unknown_products": all_unknown_products,
            "price_bleed_reqs": price_bleed_reqs,
            "top_unknown_keys": sorted(unknown_keys.items(), key=lambda x: -x[1])[:10],
            "top_failed_keys": sorted(failed_keys.items(), key=lambda x: -x[1])[:10],
            "empty_cases": empties, "cases": len(rows), "read": read}


# the lanes the facade actually serves from the core; everything else is delegated to legacy
# BY DESIGN, so in --facade-mode a non-core lane is scored as 'DELEGATED' (intended), not a
# V2 parity failure (M1.3 — makes the census deployment-path faithful).
_CANARY_LANES = frozenset({"SEARCH", "FILTER", "COMPARE", "EXPLAIN", "OFF_CATALOG"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--facade-mode", action="store_true",
                    help="score non-core lanes as DELEGATED-to-legacy (intended), not V2 fail — "
                         "reflects the real deployment path (facade lane gating)")
    ap.add_argument("--diagnose", action="store_true",
                    help="decompose constraint-satisfaction into meets/unknown/fails + the top "
                         "unknown vs failed requirement keys; write tmp/quality_diagnosis.json")
    args = ap.parse_args()

    expects = {c["id"]: (c.get("known_wrong") or {}).get("expect_v2")
               for c in json.loads(BATTERY.read_text(encoding="utf-8"))}

    labels = load_labels()   # sealed relevance labels (empty until filled — gate stays honest-red)
    s = sessionmaker(bind=get_engine())()
    results, rows, quality_rows, diag_rows = [], [], [], []
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
                core = recommend_turn(s, envelope)
                dec = _decision_slice(core) or {}
                used = {}
                try:
                    used = core.extras.get("constraints_used") or {}
                except Exception:
                    pass
                session = {"prior_node": dec.get("node_handle"),
                           "shortlist_skus": [c.sku for c in (core.products or [])][:12],
                           "accepted_constraints": {
                               "budget_min_cents": used.get("budget_min_cents"),
                               "budget_max_cents": used.get("budget_max_cents"),
                               "requirements": used.get("requirements") or {}}}
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
                    quality_rows.append(evaluate_case_quality(
                        _quality_case(f"{case['id']}:{t['turn']}", req, core), v2, labels,
                        catalog=authz))
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


if __name__ == "__main__":
    main()
