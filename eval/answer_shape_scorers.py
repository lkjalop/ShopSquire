"""Answer-shape scorers (6a) — does the NLP actually ANSWER the question?

Three pure scorers, one per RAGAS/CRAG-aligned dimension:
  * relevancy   — the answer addresses the question TYPE (budget verdict /
                  comparison guidance / knowledge concept).  [RAGAS answer-relevancy]
  * faithfulness— every product/price/spec claim traces to the retrieved results
                  (delegates to the product_claim_guard we already built). [RAGAS/Self-RAG]
  * recovery    — an empty result still yields an upgrade-path, not a dead end. [CRAG]

Pure: string + dict in, bool out (faithfulness delegates to the already-tested
guard). Unit-testable without a server.
"""
from __future__ import annotations

import re
from typing import Any


def score_relevancy(message: str, case: dict[str, Any]) -> bool:
    """True when the answer satisfies the case's shape assertions.

    A case may set any of: must_match (regex on the answer), must_contain_all,
    must_contain_any (case-insensitive substrings).
    """
    m = (message or "").strip()
    if not m:
        return False
    low = m.lower()
    pat = case.get("must_match")
    if pat and not re.search(pat, low, re.IGNORECASE):
        return False
    for tok in case.get("must_contain_all") or []:
        if str(tok).lower() not in low:
            return False
    any_set = case.get("must_contain_any")
    if any_set and not any(str(tok).lower() in low for tok in any_set):
        return False
    return True


def score_recovery(message: str, case: dict[str, Any]) -> bool:
    """Recovery is relevancy against upgrade-path phrasing — the answer must offer a
    path forward (raise budget / other brand / nearest) rather than dead-end."""
    return score_relevancy(message, case)


def score_faithfulness(
    message: str,
    results: list[dict[str, Any]],
    *,
    budget_min: int | None = None,
    budget_max: int | None = None,
) -> tuple[bool, list[str]]:
    """True when the answer invents no product/price/spec and parrots no quarantined
    payload. Delegates to the production claim-guard, run as a MEASUREMENT here
    instead of a gate. Returns (grounded, violations)."""
    from src.app.services.product_claim_guard import verify_product_narration

    gr = verify_product_narration(message or "", results or [],
                                  budget_min=budget_min, budget_max=budget_max)
    return gr.grounded, list(gr.violations)
