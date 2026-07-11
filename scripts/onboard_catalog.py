"""One-command catalog onboarding (V2 Phase 3) — classify → review → approve → ground.

The onboarding flow for ANY merchant catalog (vertical-agnostic):
  1. classify — auto-classify every variant the read-model serves onto the pinned Shopify
                taxonomy (crosswalk → lexical top-K → model picks from K → clamp → fallback).
                Writes status='proposed' rows + a human-reviewable approval file.
  2. (human)  — edit the approval file: flip "approve": false on wrong rows, or correct
                "node" to the right handle (re-clamped on consume; an invented handle is
                rejected, never written).
  3. approve  — consume the file: update corrected nodes, mark approved rows, materialize
                sold_taxonomy. ONLY this step changes what the store is grounded to sell.
  4. report   — current classification + sold-set state.

Usage (repo root, API not required — this is DB-direct):
    python scripts/onboard_catalog.py classify [--limit 500] [--out tmp/approvals.json] [--no-model]
    python scripts/onboard_catalog.py approve --file tmp/approvals.json --by merchant@demo
    python scripts/onboard_catalog.py report
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import get_engine


def cmd_classify(args) -> None:
    from src.app.services.catalog_classifier import classify_catalog, warmup
    s = sessionmaker(bind=get_engine())()
    try:
        llm_fn = (lambda p, t: "") if args.no_model else None  # blank → lexical_fallback path
        if not args.no_model:
            print("warming classifier model (cold load can take minutes)...")
            if warmup():
                print("model WARM — classifying with model picks")
            else:
                print("model UNAVAILABLE — proceeding LEXICAL-ONLY (all rows will need review)")
        report = classify_catalog(s, tenant_id=args.tenant, llm_fn=llm_fn, limit=args.limit)
        print(f"classified {report['classified']}/{report['total']} "
              f"by_source={report['by_source']} low_confidence={len(report['low_confidence'])} "
              f"unclassifiable={report['unclassifiable']}")
        # Model confidence is NOT correctness evidence (GPT-5.6 finding #6: a 0.95-confident
        # 'Whitening Tablets' for an antihistamine sailed through the old conf>=0.5 preselect).
        # Default: NOTHING preselected — a human flips approve per row; --preapprove-conf is an
        # explicit merchant policy opt-in, never a default.
        thr = args.preapprove_conf
        approvals = [{"sku": r["sku"], "title": r["title"], "node": r["node"], "path": r["path"],
                      "conf": r["conf"], "source": r["source"],
                      "approve": (thr is not None and r["conf"] >= thr)}
                     for r in report["rows"]]
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(approvals, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"approval file -> {out}  (review, then: onboard_catalog.py approve --file {out} --by <you>)")
    finally:
        s.close()


def cmd_approve(args) -> None:
    from src.app.services.taxonomy_registry import (approve_classification, get_node,
                                                    materialize_sold_taxonomy,
                                                    upsert_classification)
    rows = json.loads(Path(args.file).read_text(encoding="utf-8"))
    s = sessionmaker(bind=get_engine())()
    try:
        approved = skipped = corrected = rejected = 0
        for r in rows:
            if not r.get("approve"):
                skipped += 1
                continue
            node = str(r.get("node") or "")
            if get_node(node) is None:  # human typo'd / invented a handle — clamp holds for people too
                print(f"  REJECTED {r.get('sku')}: '{node}' is not in the pinned release")
                rejected += 1
                continue
            cur = s.execute(text(
                "SELECT node_handle FROM product_classification WHERE tenant_id=:t AND sku=:s"),
                {"t": args.tenant, "s": r["sku"]}).fetchone()
            if cur and str(cur[0]) != node:  # human corrected the node — write the correction
                upsert_classification(s, sku=r["sku"], node_handle=node, source="human_correction",
                                      confidence=1.0, status="proposed", tenant_id=args.tenant)
                corrected += 1
            if approve_classification(s, sku=r["sku"], approved_by=args.by, tenant_id=args.tenant):
                approved += 1
        n = materialize_sold_taxonomy(s, tenant_id=args.tenant, commit=False)
        s.commit()
        print(f"approved={approved} corrected={corrected} skipped={skipped} rejected={rejected} "
              f"sold_nodes_materialized={n}")
    finally:
        s.close()


def cmd_report(args) -> None:
    from src.app.services.taxonomy_registry import sold_summary
    s = sessionmaker(bind=get_engine())()
    try:
        try:
            rows = s.execute(text(
                "SELECT status, source, COUNT(*) FROM product_classification "
                "WHERE tenant_id=:t GROUP BY status, source"), {"t": args.tenant}).fetchall()
        except Exception:
            rows = []
        print("classifications:", Counter({f"{r[0]}/{r[1]}": r[2] for r in rows}) or "none")
        summary = sold_summary(s, tenant_id=args.tenant)
        print(f"sold set: grounded={summary['grounded']} release={summary['release']}")
        for n in summary["nodes"]:
            print(f"  {n['handle']:<14} {n['path']}")
    finally:
        s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", default="default")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify")
    c.add_argument("--limit", type=int, default=500)
    c.add_argument("--out", default="tmp/approvals.json")
    c.add_argument("--no-model", action="store_true", help="lexical-only (no LLM calls)")
    c.add_argument("--preapprove-conf", type=float, default=None,
                   help="EXPLICIT merchant policy: preselect approve for rows at/above this "
                        "confidence. Default: nothing preselected (confidence != correctness).")
    c.set_defaults(fn=cmd_classify)
    a = sub.add_parser("approve")
    a.add_argument("--file", required=True)
    a.add_argument("--by", required=True)
    a.set_defaults(fn=cmd_approve)
    r = sub.add_parser("report")
    r.set_defaults(fn=cmd_report)
    args = ap.parse_args()
    # argparse quirk: --tenant is on the parent parser; ensure default present on subcommands
    if not hasattr(args, "tenant"):
        args.tenant = "default"
    args.fn(args)


if __name__ == "__main__":
    main()
