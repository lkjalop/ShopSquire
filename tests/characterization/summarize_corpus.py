"""Corpus assessment report (V2 Phase 0) — the 'how does v1 actually behave' table.

Reads tests/golden/suggest_corpus/*.json and prints per-case outcome class, product counts,
contract violations, and narration results, plus aggregates. This is the human review surface
for deciding which recorded behaviors get tagged known_wrong in the battery before V2 targets
the corpus as its oracle.

Usage: python tests/characterization/summarize_corpus.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.app.contracts.suggest_contract import response_shape, validate_response  # noqa: E402
from src.app.services.recommend_parity_full import message_class  # noqa: E402

CORPUS_DIR = REPO_ROOT / "tests" / "golden" / "suggest_corpus"


def main() -> None:
    files = sorted(CORPUS_DIR.glob("*.json"))
    if not files:
        sys.exit(f"no corpus files in {CORPUS_DIR}")
    classes: Counter = Counter()
    violations: Counter = Counter()
    narration: Counter = Counter()
    rows = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for t in d["turns"]:
            resp = t.get("response") or {}
            mc = message_class(resp)
            classes[mc] += 1
            # recompute against the CURRENT contract — the stored contract_violations are a
            # record-time snapshot and go stale when the contract module evolves
            viols = validate_response(resp) if isinstance(resp, dict) else ["non_dict_body"]
            for v in viols:
                violations[v] += 1
            n = t.get("narration")
            narration[(n or {}).get("final_status") or "no_job"] += 1
            rows.append((
                d["id"], t["turn"], f"{d.get('lane', '?')}/{response_shape(resp)}", mc,
                len(resp.get("products") or []),
                str(resp.get("turn_intent") or "-"),
                len(viols),
                (n or {}).get("final_status") or "-",
                (n or {}).get("prose_len") or 0,
                t.get("elapsed_ms", 0),
                "KW" if d.get("known_wrong") else "",
            ))

    hdr = f"{'case':<28}{'t':<2}{'lane':<22}{'class':<20}{'prods':<6}{'intent':<10}{'viol':<5}{'narr':<9}{'plen':<6}{'ms':<7}{'kw'}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r[0]:<28}{r[1]:<2}{r[2]:<22}{r[3]:<20}{r[4]:<6}{r[5]:<10}{r[6]:<5}{r[7]:<9}{r[8]:<6}{r[9]:<7}{r[10]}")

    print(f"\ncases={len(files)} turns={len(rows)}")
    print("outcome classes:", dict(classes))
    print("narration outcomes:", dict(narration))
    if violations:
        print("contract violations:", dict(violations))
    else:
        print("contract violations: none")


if __name__ == "__main__":
    main()
