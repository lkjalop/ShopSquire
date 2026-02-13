from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import re
import os
import json

import httpx
from src.app.services.dependency_resilience import call_with_resilience
from src.app.feature_flags import get_flags


@dataclass
class NLPResult:
    reasons: List[str]
    scores: Dict[str, float]
    provenance: Dict[str, Any]


class NLPModelContract:
    """Minimal contract for deterministic test fixtures.

    Implementations should return an `NLPResult` or dict-like equivalent.
    """

    def infer(self, prompt: str, candidates: List[Dict] | None = None) -> NLPResult:
        raise NotImplementedError()


class DeterministicFixture(NLPModelContract):
    def __init__(self, label: str = "deterministic"):
        self.label = label

    def infer(self, prompt: str, candidates: List[Dict] | None = None) -> NLPResult:
        # Simple deterministic mapping: return candidate order unchanged and a trivial score
        ranked = [c.get("sku") for c in (candidates or [])]
        reasons = [f"fixture:{self.label}"]
        scores = {str(k): 1.0 for k in ranked}
        provenance = {"fixture": self.label, "prompt_len": len(prompt or "")}
        return NLPResult(reasons=reasons, scores=scores, provenance=provenance)


@dataclass
class ContractAnalysis:
    clauses: Dict[str, Any]
    risks: List[str]
    score: float
    summary: str


def analyze_contract(text: str) -> ContractAnalysis:
    """Lightweight contract NLP using regex heuristics.

    Extracts common clauses and flags basic risk indicators.
    """
    t = (text or "").lower()
    clauses: Dict[str, Any] = {}
    risks: List[str] = []

    def has(pat: str) -> bool:
        return bool(re.search(pat, t))

    clauses["auto_renew"] = has(r"\bauto(?:matic)?\s+renew")
    clauses["termination_days"] = _extract_days(t, r"termination\s+notice\s+(\d+)\s+days")
    clauses["liability_cap"] = _extract_money(t, r"liability\s+cap\s+\$?([\d,]+)")
    clauses["indemnity"] = has(r"\bindemnif(y|ication)\b")
    clauses["sla_uptime"] = _extract_percent(t, r"uptime\s+(\d{2,3}\.?\d*)\s*%")
    clauses["data_residency"] = has(r"\bdata\s+residency\b|\bdata\s+location\b")
    clauses["audit_rights"] = has(r"\baudit\s+rights\b|\bsecurity\s+audit\b")
    clauses["subprocessors"] = has(r"\bsub-?processor\b|\bthird\s+party\b")
    clauses["ip_ownership"] = has(r"\bintellectual\s+property\b|\bip\s+ownership\b")

    if clauses["auto_renew"]:
        risks.append("auto_renewal")
    if clauses["liability_cap"] is None:
        risks.append("liability_cap_missing")
    if clauses["termination_days"] and clauses["termination_days"] > 60:
        risks.append("long_termination_notice")
    if clauses["subprocessors"]:
        risks.append("third_party_dependency")

    score = 0.5
    score -= 0.1 * len(risks)
    score = max(0.0, min(1.0, score))
    summary = f"Contract clauses: {', '.join([k for k, v in clauses.items() if v]) or 'none detected'}"

    return ContractAnalysis(clauses=clauses, risks=risks, score=score, summary=summary)


def is_contract_like_text(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    markers = [
        "contract",
        "agreement",
        "msa",
        "statement of work",
        "termination",
        "liability",
        "indemnity",
        "auto renew",
        "uptime",
        "subprocessor",
        "data residency",
        "audit rights",
    ]
    return any(m in t for m in markers)


def run_contract_assist(text: str, enable_llm: bool = False) -> Dict[str, Any]:
    base = analyze_contract(text)
    out: Dict[str, Any] = {
        "summary": base.summary,
        "score": base.score,
        "risks": base.risks,
        "clauses": base.clauses,
        "mode": "deterministic",
    }
    if not enable_llm:
        return out
    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    model = os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")
    prompt = (
        "Summarize contract risk in 3 short bullets. "
        "Do not add facts not present in the text.\n"
        f"Text:\n{text}\n"
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 120},
    }
    try:
        def _invoke():
            with httpx.Client(timeout=5.0) as client:
                r = client.post(f"{ollama_url.rstrip('/')}/api/generate", json=payload)
                r.raise_for_status()
                return r.json()

        data = call_with_resilience("ollama.contract_nlp", _invoke, timeout_s=6.0, retries=1)
        llm_summary = (data or {}).get("response")
        if llm_summary:
            out["llm_summary"] = llm_summary
            out["mode"] = "deterministic+llm"
    except Exception:
        out["mode"] = "deterministic"
    return out


def _quality_defaults() -> Dict[str, Any]:
    """Default quality targets and thresholds for contract NLP.

    These act as conservative baselines and can be overridden via feature flags.
    """
    return {
        "min_score": 0.6,           # pass threshold
        "review_below": 0.55,       # trigger human review below
        "abstain_below": 0.4,       # abstain under this score
        "precision_target": 0.85,   # desired precision target
        "recall_target": 0.80,      # desired recall target
        "risk_weights": {
            # Higher weights elevate review/abstain decisions
            "liability_cap_missing": 0.25,
            "long_termination_notice": 0.20,
            "auto_renewal": 0.15,
            "third_party_dependency": 0.10,
        },
    }


def _quality_cfg() -> Dict[str, Any]:
    try:
        flags = get_flags() or {}
    except Exception:
        flags = {}
    cfg = dict(_quality_defaults())
    try:
        overrides = flags.get("CONTRACT_NLP_QUALITY") or {}
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                cfg[k] = v
    except Exception:
        pass
    # Normalize numeric fields
    for k in ("min_score", "review_below", "abstain_below", "precision_target", "recall_target"):
        try:
            cfg[k] = float(cfg[k])
        except Exception:
            pass
    return cfg


def evaluate_quality_gate(text: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Apply calibrated thresholds and risk-aware logic to produce a gate decision.

    Returns a dict with: { decision, reasons, metrics, thresholds }
    decision ∈ { "allow", "review", "abstain" }
    """
    cfg = _quality_cfg()
    score = float(analysis.get("score") or 0.0)
    risks = analysis.get("risks") or []
    mode = analysis.get("mode") or "deterministic"
    # Risk-adjust score
    adj = 0.0
    try:
        weights = cfg.get("risk_weights") or {}
        for r in risks:
            w = float(weights.get(r, 0.0))
            adj += w
    except Exception:
        adj = 0.0
    risk_adjusted = max(0.0, score - adj)

    decision = "allow"
    reasons: List[str] = []
    if risk_adjusted < float(cfg["abstain_below"]):
        decision = "abstain"
        reasons.append("risk_adjusted_below_abstain")
    elif risk_adjusted < float(cfg["review_below"]):
        decision = "review"
        reasons.append("risk_adjusted_below_review")
    elif risk_adjusted < float(cfg["min_score"]):
        decision = "review"
        reasons.append("below_min_score")

    # Escalate if specific high-risk flags present
    critical_flags = {"liability_cap_missing", "long_termination_notice"}
    if any(r in critical_flags for r in risks) and decision == "allow":
        decision = "review"
        reasons.append("critical_risk_present")

    metrics = {
        "raw_score": score,
        "risk_adjusted_score": risk_adjusted,
        "precision_target": cfg.get("precision_target"),
        "recall_target": cfg.get("recall_target"),
        "mode": mode,
    }

    return {
        "decision": decision,
        "reasons": reasons,
        "metrics": metrics,
        "thresholds": {
            "min_score": cfg.get("min_score"),
            "review_below": cfg.get("review_below"),
            "abstain_below": cfg.get("abstain_below"),
        },
    }


def _extract_days(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _extract_money(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except Exception:
        return None


def _extract_percent(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None
