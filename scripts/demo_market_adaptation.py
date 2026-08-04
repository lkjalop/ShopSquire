"""Demo injector for the Phase-3 storefront-adaptation lever (David M3→M4→M5).

Seeds ONE market demand-shift finding so the sales-response ranking nudge has a real signal to act on — the
deck's "detect a demand signal → re-emphasize the storefront" beat, GOVERNED by the calibrated confidence
gate (MARKET_ADAPTIVE_MIN_CONFIDENCE, default 0.6):

  * a STRONG signal (confidence >= floor) → the gate ALLOWS → the storefront re-ranks (sales_response_nudge);
  * a WEAK signal   (confidence <  floor) → the gate DENIES (low_confidence) → NO adaptation (governed).

Reversible: `--clear` expires the seeded finding (the storefront reverts on the next turn). Nothing here
sends or mutates customer-facing state directly — it only writes a market_finding the live gate then judges.

Usage:
  python -m scripts.demo_market_adaptation --direction spike --confidence 0.8    # strong → adapts
  python -m scripts.demo_market_adaptation --direction spike --confidence 0.3    # weak   → governed deny
  python -m scripts.demo_market_adaptation --clear                               # revert
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.market_analysis import FINDING_DEMAND_SHIFT, MarketFinding, persist_findings


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed/clear a demo market demand-shift finding.")
    ap.add_argument("--direction", choices=["spike", "slowdown"], default="spike",
                    help="spike → demand rising; slowdown → demand falling")
    ap.add_argument("--confidence", type=float, default=0.8, help="signal strength 0..1 (gate floor is 0.6)")
    ap.add_argument("--severity", default="critical", choices=["info", "warn", "critical"])
    ap.add_argument("--clear", action="store_true", help="expire active seeded demand findings (revert)")
    a = ap.parse_args()

    with db_session() as db:
        if a.clear:
            n = db.execute(text(
                "UPDATE market_finding SET status='expired' "
                "WHERE finding_type='demand_shift' AND status='active'")).rowcount
            db.commit()
            print(f"cleared {n} active demand_shift finding(s) — storefront reverts on next turn")
            return
        finding = MarketFinding(
            finding_type=FINDING_DEMAND_SHIFT, entity_ref=None, severity=a.severity,
            confidence=float(a.confidence),
            summary=f"Demo: demand {a.direction} detected (seeded, conf={a.confidence})",
            evidence={"direction": a.direction, "seeded": True}, window="recent")
        n = persist_findings(db, [finding])
        db.commit()
        floor = 0.6
        verdict = "-> gate should ALLOW (adapt)" if a.confidence >= floor else "-> gate should DENY (governed)"
        print(f"seeded demand_shift direction={a.direction} confidence={a.confidence} severity={a.severity} "
              f"(rows={n}) {verdict}")


if __name__ == "__main__":
    main()
