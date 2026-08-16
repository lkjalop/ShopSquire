"""Market digest (agnostic CORE) — the deck's M3 summarization layer, advisory-only.

Turns the analysis engine's ACTIVE findings into an operator brief: severity/type rollups, the top
findings, and a suggested-focus list — ALWAYS computed deterministically. An optional LLM narrative
(flag-gated, local Ollama, default OFF) may REWRITE the deterministic text for readability, and that is
the LLM's entire authority: the deck rule "LLM output must never directly trigger privileged
customer-impacting actions" is enforced structurally — the digest is a read-only projection, nothing
consumes its text as an instruction, and any LLM failure/absence falls back to the deterministic
narrative. Vertical-blind: findings are opaque (type/severity/entity/summary); no product vocabulary.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# finding type → where the operator's attention should go (bounded, explainable — no free text)
_FOCUS = {
    "competitor_undercut": "pricing review (hold margin; favour bundles over blunt discounting)",
    "demand_shift": "secure inventory ahead of demand",
    "demand_forecast": "secure inventory ahead of demand",
    "seasonal_demand": "time reorders to the seasonal peak",
    "inventory_demand_mismatch": "close unmet-demand gaps (stock what buyers ask for)",
    "objection_cluster": "address the recurring buyer objection in support guidance",
    "funnel_dropoff": "investigate the funnel stage losing buyers",
    "channel_performance": "rebalance channel emphasis toward converting channels",
    "conversion_anomaly": "investigate the conversion drop",
    "segment_shift": "review segment targeting",
    "bundle_opportunity": "evaluate the bundle opportunity",
}
_SEV_ORDER = {"critical": 0, "warn": 1, "info": 2}
_MAX_NARRATIVE_CHARS = 1400


def _llm_enabled() -> bool:
    return str(os.getenv("MARKET_DIGEST_LLM_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")


def _default_llm_fn() -> Optional[Callable[[str], str]]:
    """A sync local-Ollama rewrite call, or None when the flag is off. Best-effort: any error returns ''
    so the deterministic narrative always stands (the LLM can only improve wording, never gate output)."""
    if not _llm_enabled():
        return None
    model = (os.getenv("MARKET_DIGEST_LLM_MODEL") or os.getenv("OLLAMA_SUMMARY_MODEL")
             or os.getenv("OLLAMA_DEFAULT_MODEL") or "qwen3:14b")
    timeout = float(os.getenv("MARKET_DIGEST_LLM_TIMEOUT_SEC", "20") or 20)

    def _fn(prompt: str) -> str:
        try:
            from src.app.services.local_model_roles import configured_digest, execute_local_model_role

            return execute_local_model_role(
                prompt, role="market_narrator", purpose="aggregate_market_digest",
                prompt_id="market-digest", model=model,
                digest=configured_digest(
                    "MARKET_DIGEST_LLM_MODEL_DIGEST", "PORTFOLIO_NARRATION_MODEL_DIGEST",
                    "OLLAMA_MEDIUM_MODEL_DIGEST", "OLLAMA_DEFAULT_MODEL_DIGEST",
                ),
                timeout_s=timeout, max_output_tokens=400,
            )
        except Exception as exc:
            logger.debug("digest llm unavailable: %s", exc)
            return ""
    return _fn


def _deterministic_narrative(by_severity: Dict[str, int], focus: List[str],
                             top: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    crit, warn = by_severity.get("critical", 0), by_severity.get("warn", 0)
    parts.append(f"{crit} critical and {warn} warning market finding(s) are active.")
    if focus:
        parts.append("Suggested focus: " + "; ".join(focus[:4]) + ".")
    for f in top[:3]:
        if f.get("summary"):
            parts.append(str(f["summary"]))
    return " ".join(parts)


def build_digest(db, *, llm_fn: Optional[Callable[[str], str]] = None, max_findings: int = 20,
                 tenant_id: str = "default") -> Dict[str, Any]:
    """The operator's market brief from ACTIVE findings. Read-only; never mutates; never raises.
    Returns {mode, finding_count, by_severity, by_type, top_findings, suggested_focus, narrative,
    advisory_only:true}. ``llm_fn`` injectable for tests; default resolves from the flag."""
    out: Dict[str, Any] = {"mode": "deterministic", "finding_count": 0, "by_severity": {}, "by_type": {},
                           "top_findings": [], "suggested_focus": [], "narrative": "",
                           "advisory_only": True}
    try:
        from src.app.services.market_analysis import load_recent_findings
        findings = load_recent_findings(db, limit=max_findings, tenant_id=tenant_id)
    except Exception as exc:
        logger.debug("digest findings load failed: %s", exc)
        out["narrative"] = "Market findings are unavailable."
        return out

    rows: List[Dict[str, Any]] = []
    by_sev: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    for f in findings or []:
        sev = str(getattr(f, "severity", None) or "info").lower()
        ftype = str(getattr(f, "finding_type", None) or "unknown")
        by_sev[sev] = by_sev.get(sev, 0) + 1
        by_type[ftype] = by_type.get(ftype, 0) + 1
        rows.append({"finding_type": ftype, "severity": sev,
                     "entity_ref": getattr(f, "entity_ref", None),
                     "confidence": round(float(getattr(f, "confidence", 0.0) or 0.0), 3),
                     "summary": getattr(f, "summary", None)})
    rows.sort(key=lambda r: (_SEV_ORDER.get(r["severity"], 3), -(r["confidence"] or 0.0)))
    focus: List[str] = []
    for r in rows:   # severity-ordered, dedup by type → the most urgent focus first
        line = _FOCUS.get(r["finding_type"])
        if line and line not in focus:
            focus.append(line)

    out.update({"finding_count": len(rows), "by_severity": by_sev, "by_type": by_type,
                "top_findings": rows[:8], "suggested_focus": focus[:6]})
    det = _deterministic_narrative(by_sev, focus, rows)
    out["narrative"] = det

    fn = llm_fn if llm_fn is not None else _default_llm_fn()
    if fn is not None and rows:
        try:
            prompt = ("Rewrite this market brief for a retail operator in 3-5 plain sentences. State ONLY "
                      "the facts below — do not invent numbers, products, or actions beyond the suggested "
                      "focus. No preamble.\n\nFACTS:\n" + det)
            text = str(fn(prompt) or "").strip()[:_MAX_NARRATIVE_CHARS]
            if text:
                out["narrative"] = text
                out["mode"] = "llm_rewrite"   # the LLM rewrote the WORDING; the facts remain deterministic
        except Exception as exc:
            logger.debug("digest llm rewrite failed (deterministic stands): %s", exc)
    return out
