#!/usr/bin/env python
"""ShopSquire eval harness — real numbers for the capabilities we built.

Measures (deterministic core, no LLM needed):
  * Intent routing + constraint extraction   (query_decomposer)
  * Identity grounding correctness            (grounding_ladder — hallucination guard)
  * Security detection precision/recall/FP    (security observer — does it cry wolf?)
  * Claim grounding correctness               (claim_grounding)
  * Bounded-autonomy KPI: escalation rate + escalation precision

Optional (--live): faithfulness — runs real /suggest and checks the prose never
names a brand the grounding ladder dropped (generation-layer hallucination).

Usage:
    python -m eval.run_eval
    python -m eval.run_eval --live
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

_DATA = Path(__file__).parent / "datasets"


def _load(name: str) -> List[Dict[str, Any]]:
    out = []
    for line in (_DATA / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


# ── 1. Intent routing + constraint extraction ────────────────────────────────
def eval_intent() -> Dict[str, Any]:
    from src.app.services.query_decomposer import decompose
    rows = _load("intent_queries.jsonl")
    intent_ok = cons_ok = cons_total = awp_ok = awp_total = 0
    misses: List[str] = []
    for r in rows:
        p = decompose(r["query"])
        if p.intent == r["expected_intent"]:
            intent_ok += 1
        else:
            misses.append(f"{r['id']}: intent {p.intent}!={r['expected_intent']}")
        for k, v in (r.get("expect_constraints") or {}).items():
            cons_total += 1
            if p.hard_constraints.get(k) == v:
                cons_ok += 1
            else:
                misses.append(f"{r['id']}: constraint {k}={p.hard_constraints.get(k)}!={v}")
        if "expect_answer_without_products" in r:
            awp_total += 1
            if bool(p.answer_without_products) == bool(r["expect_answer_without_products"]):
                awp_ok += 1
    return {
        "n": len(rows), "intent_ok": intent_ok, "intent_acc": intent_ok / len(rows),
        "constraint_ok": cons_ok, "constraint_total": cons_total,
        "awp_ok": awp_ok, "awp_total": awp_total, "misses": misses,
    }


# ── 2. Identity grounding (hallucination guard) ──────────────────────────────
def eval_grounding() -> Dict[str, Any]:
    from src.app.services.grounding_ladder import ground_identity
    rows = _load("grounding_cases.jsonl")
    brand_ok = residual_ok = 0
    escalations = warranted_escalations = 0
    misses: List[str] = []
    for r in rows:
        vis = {"identified": True, "brand": r["vision_brand"], "product_type": "laptop", "confidence": 0.7} if r.get("vision_brand") else None
        txt = {"identified": True, "brand": r["text_brand"], "product_type": "laptop", "confidence": 0.6} if r.get("text_brand") else None
        g = ground_identity(r["query"], vision_identity=vis, text_identity=txt, catalog_brands=set(r.get("catalog_brands") or []))
        if (g.brand or None) == (r["expect_brand"] or None):
            brand_ok += 1
        else:
            misses.append(f"{r['id']}: brand {g.brand}!={r['expect_brand']}")
        fired = g.residual_question is not None
        if fired == bool(r["expect_residual"]):
            residual_ok += 1
        else:
            misses.append(f"{r['id']}: residual {fired}!={r['expect_residual']}")
        if fired:
            escalations += 1
            if r["expect_residual"]:
                warranted_escalations += 1
    return {
        "n": len(rows), "brand_ok": brand_ok, "brand_acc": brand_ok / len(rows),
        "residual_ok": residual_ok, "residual_acc": residual_ok / len(rows),
        "escalations": escalations, "warranted": warranted_escalations, "misses": misses,
    }


# ── 3. Security detection ─────────────────────────────────────────────────────
def eval_security() -> Dict[str, Any]:
    from src.app.security.observer import analyze_payload
    rows = _load("attacks.jsonl")
    tp = fp = tn = fn = 0
    misses: List[str] = []
    for r in rows:
        payload: Dict[str, Any] = {"query": r["text"], "source": "eval"}
        if r.get("cv_signals"):
            payload["cv_signals"] = r["cv_signals"]
        sev = str((analyze_payload(payload) or {}).get("severity") or "info").lower()
        flagged = sev in ("high", "critical")
        mal = r["label"] == "malicious"
        if mal and flagged:
            tp += 1
        elif mal and not flagged:
            fn += 1
            misses.append(f"{r['id']}: MISSED {r['category']} (sev={sev})")
        elif not mal and flagged:
            fp += 1
            misses.append(f"{r['id']}: FALSE-POSITIVE on benign '{r['text'][:40]}' (sev={sev})")
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    fp_rate = fp / (fp + tn) if (fp + tn) else 0.0
    return {
        "n": len(rows), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall, "fp_rate": fp_rate, "misses": misses,
    }


# ── 4. Claim grounding ────────────────────────────────────────────────────────
def eval_claims() -> Dict[str, Any]:
    from src.app.services.claim_grounding import ground_claim
    rows = _load("claims.jsonl")
    ok = escalations = warranted = 0
    misses: List[str] = []
    for r in rows:
        cv = {"damage_type": r["cv_damage"], "confidence": r.get("cv_conf", 0.7)} if r.get("cv_damage") else None
        c = ground_claim(r["claim"], cv_evidence=cv, receipt_evidence={"verified": bool(r.get("receipt"))})
        if c.verdict == r["expect_verdict"]:
            ok += 1
        else:
            misses.append(f"{r['id']}: verdict {c.verdict}!={r['expect_verdict']}")
        if c.verdict in ("needs_evidence", "contradicted"):
            escalations += 1
            # An escalation is warranted whenever the expected verdict is also an escalation.
            if r["expect_verdict"] in ("needs_evidence", "contradicted"):
                warranted += 1
    return {"n": len(rows), "ok": ok, "acc": ok / len(rows), "escalations": escalations, "warranted": warranted, "misses": misses}


# ── 5. Faithfulness (optional, live) ─────────────────────────────────────────
def eval_faithfulness_live() -> Dict[str, Any]:
    import warnings
    warnings.filterwarnings("ignore")
    os.environ.setdefault("GROUNDING_LADDER_ENABLED", "1")
    os.environ.setdefault("OLLAMA_SUMMARY_MODEL", "qwen3:14b")
    from fastapi.testclient import TestClient
    from src.app.main import create_app
    client = TestClient(create_app())
    h = {"x-api-key": "local-merchant-key"}
    # Brands NOT in the seeded catalog → prose must never name them (hallucination).
    cases = [
        {"labels": "razer,blade,laptop", "forbidden": "razer"},
        {"labels": "gigabyte,aorus,laptop", "forbidden": "gigabyte"},
        {"labels": "framework,laptop", "forbidden": "framework"},
    ]
    ok = 0
    misses: List[str] = []
    for i, c in enumerate(cases):
        r = client.get("/api/v1/recommend/suggest",
                       params={"uid": f"faith_{i}", "query": "gaming laptop", "image_labels": c["labels"], "budget_max": 1900},
                       headers=h)
        msg = str((r.json() or {}).get("assistant_message") or "").lower()
        if c["forbidden"] not in msg:
            ok += 1
        else:
            misses.append(f"hallucinated '{c['forbidden']}' in prose")
    return {"n": len(cases), "ok": ok, "acc": ok / len(cases), "misses": misses}


_ANSWER_SHAPE_SEED = [
    ("p-as-msi", "AS-MSI", "MSI Katana 15", 159900, '{"gpu":"rtx 4060","display":"144hz","ram":"16gb"}'),
    ("p-as-dell", "AS-DELL", "Dell G15", 139900, '{"gpu":"rtx 4050","display":"120hz","ram":"16gb"}'),
    ("p-as-asus", "AS-ASUS", "ASUS Vivobook S16", 127800, '{"gpu":"integrated","display":"60hz","ram":"16gb"}'),
    ("p-as-legion", "AS-LEG", "Lenovo Legion 5", 179900, '{"gpu":"rtx 4070","display":"165hz","ram":"32gb"}'),
    ("p-as-creator", "AS-CRE", "ASUS ProArt Studio", 229900, '{"gpu":"rtx 4070","display":"4k","ram":"32gb"}'),
    ("p-as-hp", "AS-HP", "HP Victus 15", 119900, '{"gpu":"rtx 4050","display":"144hz","ram":"16gb"}'),
]


def eval_answer_shape() -> Dict[str, Any]:
    """Live answer-QUALITY: relevancy / faithfulness / recovery via real /suggest.

    Reuses create_app + the production claim-guard; seeds a small deterministic
    catalog so the numbers are reproducible (not demo-data dependent).
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text as _sql
    from src.app.main import create_app
    from src.app.models.db import db_session
    from eval.answer_shape_scorers import score_relevancy, score_recovery, score_faithfulness

    try:
        from tests.utils import default_headers
        _headers = default_headers()
    except Exception:
        _headers = {}

    app = create_app()
    client = TestClient(app, headers=_headers)

    try:
        with db_session() as db:
            # Deterministic catalog: clear any demo-seeded products so the numbers
            # reflect ONLY the known seed (otherwise off-catalog items, e.g. a router,
            # leak in and make the eval non-reproducible).
            try:
                db.execute(_sql("DELETE FROM inventory"))
                db.execute(_sql("DELETE FROM products"))
            except Exception:
                pass
            for pid, sku, name, price, specs in _ANSWER_SHAPE_SEED:
                db.execute(_sql(
                    "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) "
                    "VALUES (:id,:sku,:name,:price,'USD',:specs,1)"),
                    {"id": pid, "sku": sku, "name": name, "price": price, "specs": specs})
                db.execute(_sql(
                    "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) "
                    "VALUES (:iid,:pid,5,'default')"),
                    {"iid": f"inv-{pid}", "pid": pid})
            db.commit()
    except Exception as exc:
        return {"metrics": {}, "misses": [f"seed failed: {exc}"]}

    rows = _load("answer_shape.jsonl")
    metrics = {"relevancy": [0, 0], "faithfulness": [0, 0], "recovery": [0, 0]}
    misses: List[str] = []
    for r in rows:
        metric = r.get("metric", "relevancy")
        params: Dict[str, Any] = {"uid": f"eval-{r['id']}", "query": r["query"]}
        if r.get("budget_min") is not None:
            params["budget_min"] = r["budget_min"]
        if r.get("budget_max") is not None:
            params["budget_max"] = r["budget_max"]
        try:
            resp = client.get("/api/v1/recommend/suggest", params=params)
            body = resp.json() if resp.status_code == 200 else {}
        except Exception as exc:
            body = {}
            misses.append(f"{r['id']}: request failed {exc}")
        msg = str(body.get("assistant_message") or "")
        results = body.get("results") or []
        metrics[metric][1] += 1
        if metric == "faithfulness":
            grounded, viol = score_faithfulness(msg, results,
                                                budget_min=r.get("budget_min"), budget_max=r.get("budget_max"))
            ok = grounded
            if not ok:
                misses.append(f"{r['id']} [faith]: {','.join(viol[:3])}")
        elif metric == "recovery":
            ok = score_recovery(msg, r)
            if not ok:
                misses.append(f"{r['id']} [recovery]: {msg[:90]!r}")
        else:
            ok = score_relevancy(msg, r)
            if not ok:
                misses.append(f"{r['id']} [relevancy]: {msg[:90]!r}")
        if ok:
            metrics[metric][0] += 1
    return {"metrics": metrics, "misses": misses}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also run live faithfulness (needs Ollama)")
    ap.add_argument("--answer-shape", action="store_true", help="run live 3-metric answer-shape eval (needs DB + route)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print individual misses")
    args = ap.parse_args()

    intent = eval_intent()
    grounding = eval_grounding()
    security = eval_security()
    claims = eval_claims()

    # Bounded-autonomy KPI (aggregate across grounding + claims + security).
    total_interactions = grounding["n"] + claims["n"] + security["n"]
    escalations = grounding["escalations"] + claims["escalations"] + (security["tp"] + security["fp"])
    warranted = grounding["warranted"] + claims["warranted"] + security["tp"]
    esc_rate = escalations / total_interactions if total_interactions else 0.0
    esc_precision = warranted / escalations if escalations else 1.0

    print("\n" + "=" * 64)
    print("  ShopSquire Eval Scorecard")
    print("=" * 64)
    print(f"\n  Intent routing           {_pct(intent['intent_ok'], intent['n'])}  ({intent['intent_ok']}/{intent['n']})")
    print(f"  Constraint extraction    {_pct(intent['constraint_ok'], intent['constraint_total'])}  ({intent['constraint_ok']}/{intent['constraint_total']})")
    print(f"  Knowledge-path routing   {_pct(intent['awp_ok'], intent['awp_total'])}  ({intent['awp_ok']}/{intent['awp_total']})")
    print(f"\n  Identity grounding       {_pct(grounding['brand_ok'], grounding['n'])}  brand-decision  ({grounding['brand_ok']}/{grounding['n']})")
    print(f"  Residual-question fire   {_pct(grounding['residual_ok'], grounding['n'])}  ({grounding['residual_ok']}/{grounding['n']})")
    print(f"\n  Security detection")
    print(f"    precision              {security['precision']*100:.1f}%   recall {security['recall']*100:.1f}%")
    print(f"    false-positive rate    {security['fp_rate']*100:.1f}%   (TP={security['tp']} FP={security['fp']} TN={security['tn']} FN={security['fn']})")
    print(f"\n  Claim grounding          {_pct(claims['ok'], claims['n'])}  ({claims['ok']}/{claims['n']})")
    print(f"\n  Bounded-autonomy KPI")
    print(f"    autonomous (no human)  {_pct(total_interactions - escalations, total_interactions)}")
    print(f"    escalation rate        {esc_rate*100:.1f}%   ({escalations}/{total_interactions})")
    print(f"    escalation precision   {esc_precision*100:.1f}%   (warranted when it asked)")

    if args.live:
        faith = eval_faithfulness_live()
        print(f"\n  Faithfulness (live)      {_pct(faith['ok'], faith['n'])}  no dropped-brand hallucination  ({faith['ok']}/{faith['n']})")
        if args.verbose:
            for m in faith["misses"]:
                print(f"      - {m}")

    if args.answer_shape:
        ash = eval_answer_shape()
        mtr = ash.get("metrics") or {}
        print(f"\n  Answer-shape (live, 3-metric)")
        for _label, _key in (("relevancy ", "relevancy"), ("faithfulness", "faithfulness"), ("recovery  ", "recovery")):
            ok, n = (mtr.get(_key) or [0, 0])
            print(f"    {_label}           {_pct(ok, n)}  ({ok}/{n})")
        if args.verbose:
            for m in ash.get("misses", []):
                print(f"      - {m}")

    if args.verbose:
        for label, res in (("INTENT", intent), ("GROUNDING", grounding), ("SECURITY", security), ("CLAIMS", claims)):
            for m in res.get("misses", []):
                print(f"  [{label}] {m}")
    print("=" * 64 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
