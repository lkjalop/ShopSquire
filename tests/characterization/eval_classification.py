"""Classification holdout evaluator (V2 Phase 3.5) — the classifier's HONEST scorecard.

Replaces the family-level agreement metric that let a 0.95-confident 'Whitening Tablets'
count as correct (GPT-5.6 finding #6: coverage is not accuracy). Scores the stored
product_classification rows against hand labels (tests/golden/classification_labels.json):

  exact accuracy      — predicted node == labeled node
  lenient accuracy    — exact, OR in the label's acceptable_alt list, OR an ANCESTOR of the
                        label (a defensibly coarser call: aa-1 for a dress is coarse-true;
                        a SIBLING is not)
  macro-F1            — per-label-node F1, unweighted mean (rare categories count equally)
  abstention          — labeled SKUs with no stored classification
  false-sold rate     — classification-derived sold nodes containing NO labeled product
                        (node is neither a label nor an ancestor of one): the sold set
                        claiming categories the store does not actually stock.

Usage: python tests/characterization/eval_classification.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import get_engine
from src.app.services.taxonomy_registry import ancestors, get_node

LABELS_PATH = REPO_ROOT / "tests" / "golden" / "classification_labels.json"


def is_ancestor(candidate: str, of: str) -> bool:
    return candidate in {a.handle for a in ancestors(of)}


def _fresh_predictions(s, labels) -> dict:
    """GPT-5.6 review-2: the persisted-row score is NO LONGER BLIND (it contains human
    corrections → 100%). --fresh RE-RUNS the classifier live on each labeled product and
    scores THAT — the true holdout number. ~114 model calls; slow but honest."""
    from src.app.services.catalog_classifier import classify_text
    from src.app.services.catalog_read_model import get_variant
    out = {}
    for sku in labels:
        v = get_variant(s, sku, mode="legacy")
        if v is None:
            continue
        cat = str((v.specs or {}).get("category") or (v.specs or {}).get("type") or "").replace("_", " ")
        c = classify_text(" ".join(filter(None, [v.title, v.brand, v.product_type, cat])),
                          existing_category=v.category or v.product_type or cat)
        if c is not None:
            out[sku] = {"node": c.node_handle, "source": c.source, "status": "fresh"}
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--fresh", action="store_true",
                    help="re-run the classifier live (true blind holdout) instead of scoring "
                         "persisted rows (which contain human corrections -> not blind)")
    args = ap.parse_args()
    data = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    labels = {sku: d for sku, d in data["labels"].items()}
    for sku, d in labels.items():
        assert get_node(d["node"]) is not None, f"label {sku}->{d['node']} not in pinned release"

    s = sessionmaker(bind=get_engine())()
    try:
        if args.fresh:
            print("--fresh: re-running classifier live (~114 model calls)...")
            preds = _fresh_predictions(s, labels)
        else:
            preds = {str(r[0]): {"node": str(r[1]), "source": str(r[2] or ""), "status": str(r[3] or "")}
                     for r in s.execute(text(
                         "SELECT sku, node_handle, source, status FROM product_classification "
                         "WHERE tenant_id=:t"), {"t": args.tenant}).fetchall()}
        sold = {str(r[0]): str(r[1] or "") for r in s.execute(text(
            "SELECT node_handle, source FROM sold_taxonomy WHERE tenant_id=:t"), {"t": args.tenant}).fetchall()}
    finally:
        s.close()

    exact = lenient = 0
    abstained = []
    misses = []
    tp: Counter = Counter(); fp: Counter = Counter(); fn: Counter = Counter()
    by_source = defaultdict(lambda: [0, 0])  # source -> [exact, wrong]
    for sku, lab in sorted(labels.items()):
        want, alts = lab["node"], set(lab.get("acceptable_alt") or [])
        p = preds.get(sku)
        if p is None:
            abstained.append(sku)
            fn[want] += 1
            continue
        got = p["node"]
        if got == want:
            exact += 1; lenient += 1; tp[want] += 1; by_source[p["source"]][0] += 1
        else:
            fp[got] += 1; fn[want] += 1; by_source[p["source"]][1] += 1
            if got in alts or is_ancestor(got, want):
                lenient += 1
            n_got, n_want = get_node(got), get_node(want)
            misses.append((sku, got, n_got.name if n_got else "?", want,
                           n_want.name if n_want else "?", p["source"]))

    n = len(labels)
    f1s = []
    for node in {lab["node"] for lab in labels.values()}:
        p_den, r_den = tp[node] + fp[node], tp[node] + fn[node]
        prec = tp[node] / p_den if p_den else 0.0
        rec = tp[node] / r_den if r_den else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if (prec + rec) else 0.0)
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0

    label_nodes = {lab["node"] for lab in labels.values()}
    false_sold = sorted(
        h for h, src in sold.items() if src == "classification_approval"
        and h not in label_nodes and not any(is_ancestor(h, ln) for ln in label_nodes))
    cls_sold = [h for h, src in sold.items() if src == "classification_approval"]

    print(f"labeled={n} predicted={n - len(abstained)} abstained={len(abstained)} {abstained}")
    print(f"EXACT accuracy   : {exact}/{n} = {exact / n:.1%}")
    print(f"LENIENT accuracy : {lenient}/{n} = {lenient / n:.1%}  (exact | acceptable_alt | ancestor-of-label)")
    print(f"MACRO-F1 (exact) : {macro_f1:.3f} over {len(f1s)} label nodes")
    print(f"FALSE-SOLD       : {len(false_sold)}/{len(cls_sold)} classification-derived sold nodes "
          f"contain no labeled product: {false_sold}")
    print("by source (exact, wrong):", dict(by_source))
    if misses:
        print(f"\nMISMATCHES ({len(misses)}):")
        for sku, got, gname, want, wname, src in misses:
            print(f"  {sku:<14} got {got:<14} {gname[:26]:<28} want {want:<14} {wname[:26]:<28} [{src}]")


if __name__ == "__main__":
    main()
