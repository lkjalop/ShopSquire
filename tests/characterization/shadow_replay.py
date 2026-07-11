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

CORPUS_DIR = REPO_ROOT / "tests" / "golden" / "suggest_corpus"
BATTERY = REPO_ROOT / "tests" / "characterization" / "batteries" / "starter_battery.json"


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
    args = ap.parse_args()

    expects = {c["id"]: (c.get("known_wrong") or {}).get("expect_v2")
               for c in json.loads(BATTERY.read_text(encoding="utf-8"))}

    s = sessionmaker(bind=get_engine())()
    results, rows = [], []
    t_start = time.monotonic()
    try:
        for f in sorted(CORPUS_DIR.glob("*.json")):
            case = json.loads(f.read_text(encoding="utf-8"))
            if args.only and case["id"] != args.only:
                continue
            for t in case["turns"]:
                req, v1 = t["request"]["params"], t.get("response") or {}
                envelope = TurnEnvelope.from_suggest_params(
                    query=req.get("query", ""), uid=f"shadow-{case['id']}-{t['turn']}")
                t0 = time.monotonic()
                core = recommend_turn(s, envelope)
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
    score = summarize_run(results)
    print(f"\nSCORECARD ({time.monotonic()-t_start:.0f}s total): {json.dumps(score, indent=1)}")


if __name__ == "__main__":
    main()
