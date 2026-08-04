"""Seed synthetic traffic-source demand signals WITH coarse network fingerprints — for the demo.

The marketing-BI panels (/market/network-breakdown, verified-human visits, channel breakdown) are empty
until real clickstream flows through consumer_signals with IP enrichment. This seeds a spread of synthetic
VISITS so those panels show data in a sandbox demo: varied channels, countries, ASNs, risk tiers, and
bot-suspect vs verified-human — all NON-PII (coarse {asn, country, risk_tier}, never a raw IP).

Run from repo root (same venv as the backend):  python scripts/seed_network_signals.py [--visits 120]
It writes to the app's configured DB via db_session. Idempotent-ish (append-only demand signals); safe to
re-run. Uses ONLY traffic_source.capture — the same path the live ingest uses, so the seed is faithful.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.app.models.db import db_session  # noqa: E402
from src.app.services import traffic_source as ts  # noqa: E402

# (channel, country, asn, risk_tier, bot_suspect) — a realistic spread; NO raw IP anywhere.
_MIX = [
    ("google/cpc", "AU", 4764, "low", False),
    ("google/cpc", "AU", 4764, "low", False),
    ("google/organic", "AU", 1221, "low", False),
    ("meta/paid", "US", 7018, "low", False),
    ("meta/paid", "US", 7018, "low", False),
    ("newsletter", "GB", 5089, "low", False),
    ("referral:reddit.com", "US", 14618, "medium", True),   # datacenter → bot-suspect
    ("direct", "IN", 9829, "medium", True),                 # VPN-ish → bot-suspect
    ("google/cpc", "NZ", 4771, "low", False),
    ("direct", "AU", 4764, "low", False),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed synthetic network-fingerprinted visits for the demo.")
    ap.add_argument("--visits", type=int, default=120, help="how many synthetic visits to seed")
    args = ap.parse_args()

    seeded = 0
    with db_session() as db:
        for i in range(int(args.visits)):
            channel, country, asn, risk, bot = _MIX[i % len(_MIX)]
            # deterministic pseudo-timestamp/session (no Date.now — offline-safe); one session per visit
            sh = f"seed-sess-{i:04d}"
            occurred = f"2026-07-02T{(i % 24):02d}:{(i * 7 % 60):02d}:00"
            props = {"utm_source": channel.split("/")[0] if "/" in channel else channel,
                     "utm_medium": channel.split("/")[1] if "/" in channel else None,
                     "referrer": channel.split(":", 1)[1] if channel.startswith("referral:") else None}
            r = ts.capture(db, session_hash=sh, properties=props, action="page_view", bot_suspect=bot,
                           occurred_at=occurred, network={"asn": asn, "country": country, "risk_tier": risk})
            if r.get("emitted"):
                seeded += 1
            # ~1 in 6 sessions converts → non-trivial conversion-rate + attribution
            if i % 6 == 0:
                ts.capture(db, session_hash=sh, properties={}, action="purchase", occurred_at=occurred)

    with db_session() as db:
        nb = ts.network_breakdown(db)
        ch = ts.channel_breakdown(db)
    print(f"seeded {seeded} visits.")
    print("network coverage:", nb.get("coverage"))
    print("by_country:", [(r["country"], r["visits"]) for r in nb.get("by_country", [])][:6])
    print("by_risk_tier:", [(r["risk_tier"], r["visits"]) for r in nb.get("by_risk_tier", [])])
    print("channel summary:", ch.get("summary"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
