"""Market Intelligence Agent (agnostic CORE) — the read-only context gatherer.

Gathers a turn's market context: the hippograph recall (always — cheap, personalized) PLUS recent
PERSISTED market findings WHEN the query intent needs market evidence (gated by
query_decomposer.needs_market_evidence, so a plain lookup doesn't pay the cost). FAST: it reads
persisted findings, never runs the ~1.6s analysis (that's the batch's job). Read-only — it PROPOSES
context for the blackboard / response / agents; a finding that drives a change re-enters the
experiment gate + policy. Never raises. Vertical-blind.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _finding_dict(f: Any) -> Dict[str, Any]:
    return {
        "finding_type": getattr(f, "finding_type", None),
        "entity_ref": getattr(f, "entity_ref", None),
        "severity": getattr(f, "severity", None),
        "confidence": round(float(getattr(f, "confidence", 0.0) or 0.0), 3),
        "summary": getattr(f, "summary", None),
    }


def gather_market_context(
    db,
    *,
    query: Optional[str],
    uid_hash: Optional[str] = None,
    result_skus: Optional[List[str]] = None,
    top_k: int = 8,
    max_findings: int = 5,
) -> Dict[str, Any]:
    """Return {hippograph_insights, needs_market_evidence, evidence_kinds, market_findings}.
    Recall is always gathered (cheap, personalized); findings only when the query needs market evidence."""
    out: Dict[str, Any] = {
        "hippograph_insights": [],
        "needs_market_evidence": False,
        "evidence_kinds": [],
        "market_findings": [],
    }
    try:
        from src.app.services.hippograph_feedback import build_hippograph_insights
        out["hippograph_insights"] = build_hippograph_insights(
            db, uid_hash=uid_hash, seed_skus=list(result_skus or [])[:5], top_k=top_k)
        from src.app.services.query_decomposer import decompose
        plan = decompose(query)
        if getattr(plan, "needs_market_evidence", False):
            out["needs_market_evidence"] = True
            out["evidence_kinds"] = list(getattr(plan, "market_evidence_kinds", []) or [])
            from src.app.services.market_analysis import load_recent_findings
            findings = load_recent_findings(db, limit=int(max_findings))
            out["market_findings"] = [_finding_dict(f) for f in findings]
        return out
    except Exception:
        return out
