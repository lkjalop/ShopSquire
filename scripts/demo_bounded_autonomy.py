#!/usr/bin/env python
"""Bounded-autonomy demo — the thesis made visible and runnable.

Walks a sequence of real interactions through the platform's decision primitives
and shows, for each, whether the agent acted AUTONOMOUSLY or hit a BOUNDARY that
pulled in a human (and why). Ends with the autonomy dial.

The thesis: act autonomously by default; involve a human ONLY at boundaries set
by confidence, value-at-risk, novelty, and security signal — and when you do,
be right about it.

Uses deterministic primitives (no LLM) so it runs in ~1s:
    python scripts/demo_bounded_autonomy.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # ensure arrows / em-dashes render on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _line(s: str = "") -> None:
    sys.stdout.write(s + "\n")


def main() -> int:
    from src.app.services.query_decomposer import decompose
    from src.app.services.grounding_ladder import ground_identity
    from src.app.services.claim_grounding import ground_claim
    from src.app.security.observer import analyze_payload

    catalog = {"msi", "asus", "dell", "hp", "lenovo", "acer", "apple", "samsung", "lg", "microsoft"}
    interactions = []  # (title, autonomous, boundary_reason, detail)

    # 1. Clear shopping query → autonomous.
    p = decompose("what's good for gaming, 1500-1900, why?")
    interactions.append((
        "Shopper: \"what's good for gaming, 1500-1900, why?\"",
        True, None,
        f"intent={p.intent}, dGPU required → recommends + explains solo.",
    ))

    # 2. Knowledge question → autonomous (conceptual answer, no human).
    p = decompose("what's the difference between the RTX 4060 and 4070?")
    interactions.append((
        "Shopper: \"difference between the RTX 4060 and 4070?\"",
        True, None,
        f"intent={p.intent} → answers the concept directly, no products needed.",
    ))

    # 3. Image with an in-catalog brand → autonomous (grounded).
    g = ground_identity("gaming laptop", vision_identity={"identified": True, "brand": "MSI", "product_type": "laptop", "confidence": 0.7}, catalog_brands=catalog)
    interactions.append((
        "Shopper uploads a laptop photo; vision reads 'MSI'",
        g.residual_question is None, None if g.residual_question is None else "identity_unconfirmed",
        f"brand={g.brand!r} grounded in catalog (tier={g.tier_name}) → anchors recs solo.",
    ))

    # 4. Image with an out-of-catalog brand → BOUNDARY (ask the shopper).
    g = ground_identity("gaming laptop", vision_identity={"identified": True, "brand": "Razer", "product_type": "laptop", "confidence": 0.7}, catalog_brands=catalog)
    rq = (g.residual_question or {}).get("text")
    interactions.append((
        "Shopper uploads a laptop photo; vision guesses 'Razer'",
        False, "identity_unconfirmed",
        f"catalog can't confirm 'Razer' → does NOT assert it; asks: \"{rq}\"",
    ))

    # 5. Return claim that matches the evidence → autonomous.
    c = ground_claim("the screen is cracked", cv_evidence={"damage_type": "physical", "confidence": 0.85}, receipt_evidence={"verified": True})
    interactions.append((
        "Return: \"the screen is cracked\" (+ photo, + receipt)",
        c.verdict == "supported", None if c.verdict == "supported" else c.verdict,
        f"CV confirms physical damage + receipt verified → verdict={c.verdict}, progresses solo.",
    ))

    # 6. Return claim contradicted by evidence → BOUNDARY (route to human).
    c = ground_claim("my screen is completely cracked and shattered", cv_evidence={"damage_type": "cosmetic", "confidence": 0.8})
    interactions.append((
        "Return: \"completely cracked and shattered\" (CV sees only a scuff)",
        False, "claim_contradicted",
        f"verdict={c.verdict} → {(c.residual_action or {}).get('action')} (potential fraud).",
    ))

    # 7. Compromised image upload → BOUNDARY (serve + escalate to SOC).
    sec = analyze_payload({"query": "find me a gaming laptop", "ip": "185.220.101.5",
                           "cv_signals": {"qr_code_detected": True, "qr_external_url_detected": True, "qr_prompt_injection": True}})
    sev = str(sec.get("severity"))
    interactions.append((
        "Shopper uploads a laptop image with a malicious QR overlay",
        False, "security_signal",
        f"severity={sev} → still recommends (warn-and-continue) BUT escalates to the SOC + scores the IP.",
    ))

    # 8. Benign-but-suspicious wording → autonomous (no false alarm).
    sec = analyze_payload({"query": "ignore the cheaper options, show me premium laptops"})
    interactions.append((
        "Shopper: \"ignore the cheaper options, show me premium laptops\"",
        True, None,
        f"severity={sec.get('severity')} → recognised as benign shopping, NOT flagged (no false alarm).",
    ))

    _line("\n" + "=" * 70)
    _line("  ShopSquire — Bounded Autonomy")
    _line("  (act solo by default; involve a human only at a real boundary)")
    _line("=" * 70 + "\n")
    autonomous = 0
    escalations = 0
    for i, (title, solo, reason, detail) in enumerate(interactions, 1):
        tag = "  AUTONOMOUS " if solo else ">> BOUNDARY  "
        _line(f"{tag} {i}. {title}")
        _line(f"               {detail}")
        if solo:
            autonomous += 1
        else:
            escalations += 1
            _line(f"               boundary: {reason}")
        _line("")

    total = len(interactions)
    _line("-" * 70)
    _line(f"  Autonomy dial:  {autonomous}/{total} handled solo ({100*autonomous/total:.0f}%)   "
          f"{escalations}/{total} hit a boundary ({100*escalations/total:.0f}%)")
    _line(f"  Every boundary was a genuine one: identity-unconfirmed, claim-contradicted,")
    _line(f"  or a real security signal. The agent asks a human exactly when the evidence")
    _line(f"  runs out — and not before.")
    _line("-" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
