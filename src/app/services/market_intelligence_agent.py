"""Market Intelligence Agent (agnostic CORE) — the read-only context gatherer.

Gathers a turn's market context: the hippograph recall (always — cheap, personalized) PLUS recent
PERSISTED market findings WHEN the query intent needs market evidence (gated by
query_decomposer.needs_market_evidence, so a plain lookup doesn't pay the cost). FAST: it reads
persisted findings, never runs the ~1.6s analysis (that's the batch's job). Read-only — it PROPOSES
context for the blackboard / response / agents; a finding that drives a change re-enters the
experiment gate + policy. Never raises. Vertical-blind.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_SEVERITY_RANK = {"critical": 1.0, "warn": 0.7, "info": 0.3}
_USEFUL_INSIGHT_KINDS = ("product", "finding", "brand", "segment")


def _finding_dict(f: Any) -> Dict[str, Any]:
    return {
        "finding_type": getattr(f, "finding_type", None),
        "entity_ref": getattr(f, "entity_ref", None),
        "severity": getattr(f, "severity", None),
        "confidence": round(float(getattr(f, "confidence", 0.0) or 0.0), 3),
        "summary": getattr(f, "summary", None),
    }


def _tokenize(query: Optional[str]) -> List[str]:
    """Agnostic word tokens (>=3 chars, lowercased) — NO domain vocabulary."""
    return re.findall(r"[a-z0-9]{3,}", str(query or "").lower())


def _scope_findings(findings: List[Any], *, query_tokens: List[str], result_skus: List[str]) -> List[Any]:
    """Keep findings RELEVANT to this turn — entity matches a surfaced SKU, or its entity token
    overlaps a query token, or it is a global/market-wide finding (entity_ref empty). Ranked by
    severity×confidence. Vertical-blind: matching is pure token overlap, no product knowledge."""
    skuset = {str(s).strip().lower() for s in (result_skus or []) if s}
    qset = set(query_tokens or [])
    scored = []
    for f in findings:
        ent = str(getattr(f, "entity_ref", None) or "").strip().lower()
        if ent:
            relevant = ent in skuset or any(tok in ent or ent in tok for tok in qset)
        else:
            relevant = True  # global finding — market-wide, always in scope when evidence is needed
        if not relevant:
            continue
        sev = _SEVERITY_RANK.get(str(getattr(f, "severity", None) or "info"), 0.5)
        conf = float(getattr(f, "confidence", 0.0) or 0.0)
        scored.append((sev * conf, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored]


def _structured_evidence(findings: List[Dict[str, Any]], insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A narration-ready, deterministic evidence object (what's salient + what the findings say)."""
    salient = [{"label": i.get("label"), "kind": i.get("kind"), "score": i.get("score")}
               for i in (insights or []) if isinstance(i, dict) and i.get("kind") in _USEFUL_INSIGHT_KINDS][:6]
    return {
        "findings": [{"type": f.get("finding_type"), "severity": f.get("severity"),
                      "summary": f.get("summary"), "entity": f.get("entity_ref")} for f in (findings or [])],
        "salient_entities": salient,
    }


def format_evidence_for_narration(findings: List[Dict[str, Any]], *, max_items: int = 4) -> str:
    """Compact factual evidence block for the narration preamble. Empty string when nothing to say.
    Phrased so the LLM cites it only if it answers the user — it must not invent specifics."""
    lines = []
    for f in (findings or [])[:max_items]:
        summ = f.get("summary") or f"{f.get('finding_type')} ({f.get('severity')})"
        if summ:
            lines.append(f"- {summ}")
    if not lines:
        return ""
    return ("Verified internal market evidence for this query (cite ONLY if it answers the user; never "
            "invent specifics beyond these lines):\n" + "\n".join(lines))


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
        "market_evidence": {},
        "narration_note": "",
    }
    try:
        tokens = _tokenize(query)
        seed_skus = list(result_skus or [])[:5]
        from src.app.services.hippograph_feedback import build_hippograph_insights
        # query-scope recall: seed from products AND query terms so entity-scoped findings surface
        out["hippograph_insights"] = build_hippograph_insights(
            db, uid_hash=uid_hash, seed_skus=seed_skus, seed_terms=tokens, top_k=top_k)
        from src.app.services.query_decomposer import decompose
        plan = decompose(query)
        if getattr(plan, "needs_market_evidence", False):
            out["needs_market_evidence"] = True
            out["evidence_kinds"] = list(getattr(plan, "market_evidence_kinds", []) or [])
            from src.app.services.market_analysis import load_recent_findings
            # over-fetch, then query-scope to the most relevant — not a recency dump
            raw = load_recent_findings(db, limit=max(int(max_findings) * 4, 12))
            scoped = _scope_findings(raw, query_tokens=tokens, result_skus=seed_skus)[:int(max_findings)]
            out["market_findings"] = [_finding_dict(f) for f in scoped]
        # structured + narration-ready evidence (additive; consumers gate on presence)
        out["market_evidence"] = _structured_evidence(out["market_findings"], out["hippograph_insights"])
        out["narration_note"] = format_evidence_for_narration(out["market_findings"])
        return out
    except Exception:
        return out
