"""Adaptive agent budget computation (agnostic CORE).

Extracted verbatim from Orchestrator._compute_adaptive_agent_budgets so the orchestrator shrinks
and the budget math becomes a pure, unit-testable function. Vertical-blind: it speaks only of
agent NAMES, tiers, risk bands and event signals — no product vocabulary. Pure (args + flags +
a best-effort risk-band lookup); no behaviour change from the original method.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def compute_adaptive_agent_budgets(
    *,
    query: str,
    tier: int,
    base_tool_budget: int,
    risk_adj: float,
    intent_confidence: float,
    multi_turn: bool,
    flags: Dict[str, Any],
    event_signals: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    q = str(query or "").lower()
    complexity_hits = 0
    for tok in ("compare", "tradeoff", "versus", "detailed", "why", "explain", "multi"):
        if tok in q:
            complexity_hits += 1
    factor = 1.0
    if int(tier or 1) >= 2:
        factor += 0.25
    if float(risk_adj or 0.0) >= 40.0:
        factor += 0.25
    if float(intent_confidence or 1.0) < 0.70:
        factor += 0.20
    if bool(multi_turn):
        factor += 0.10
    if complexity_hits >= 2:
        factor += 0.15
    # ── Risk register domain-aware budget boost ──
    # When org risk posture is elevated, boost relevant agents.
    _rr_high_domains: list = []
    try:
        from src.app.routers.admin_grc import get_latest_risk_bands
        _rr_bands = get_latest_risk_bands()
        _rr_high_domains = [d for d, b in _rr_bands.items() if b in ("high", "critical")]
    except Exception:
        pass
    if _rr_high_domains:
        factor += 0.15  # global budget bump
    global_budget = max(1, min(12, int(round(float(base_tool_budget or 1) * factor))))
    agent_weights = {
        "Security_Observer_Agent": 0.20,
        "NLP_Search_Agent": 0.20,
        "Candidate_Retrieval_Agent": 0.16,
        "Product_Ranking_Agent": 0.20,
        "CV_Label_Agent": 0.12,
        "Inventory_Agent": 0.06,
        "Fraud_Scoring_Agent": 0.06,
    }
    # Domain-specific weight boosts from risk register
    if any(d in ("supplier_trust", "inventory_resilience") for d in _rr_high_domains):
        agent_weights["Inventory_Agent"] = 0.18  # +200% budget for inventory checks
        agent_weights["Fraud_Scoring_Agent"] = 0.12
    if any(d in ("insider_threat", "email_deliverability") for d in _rr_high_domains):
        agent_weights["Security_Observer_Agent"] = 0.30  # +50% more security scrutiny
    # ── Event-signal-driven weight boosts ──
    _ev = event_signals or {}
    if _ev.get("cart_abandonment_detected"):
        # Retargeting / merchandising: boost ranking + NLP + candidate retrieval
        agent_weights["Product_Ranking_Agent"] = max(agent_weights.get("Product_Ranking_Agent", 0.20), 0.28)
        agent_weights["NLP_Search_Agent"] = max(agent_weights.get("NLP_Search_Agent", 0.20), 0.24)
        agent_weights["Candidate_Retrieval_Agent"] = max(agent_weights.get("Candidate_Retrieval_Agent", 0.16), 0.20)
        factor += 0.10
    if _ev.get("coupon_abuse_signals"):
        # Fraud defence: boost security + fraud scoring
        agent_weights["Security_Observer_Agent"] = max(agent_weights.get("Security_Observer_Agent", 0.20), 0.30)
        agent_weights["Fraud_Scoring_Agent"] = max(agent_weights.get("Fraud_Scoring_Agent", 0.06), 0.16)
        factor += 0.15
    if _ev.get("high_value_session"):
        # VIP-tier: bump overall budget and ranking agent
        agent_weights["Product_Ranking_Agent"] = max(agent_weights.get("Product_Ranking_Agent", 0.20), 0.26)
        factor += 0.10
    per_agent: Dict[str, int] = {}
    remaining = global_budget
    keys = list(agent_weights.keys())
    for idx, agent in enumerate(keys):
        w = float(agent_weights.get(agent) or 0.0)
        if idx == len(keys) - 1:
            alloc = max(0, remaining)
        else:
            alloc = max(0, int(round(global_budget * w)))
            remaining -= alloc
        per_agent[agent] = alloc
    token_base = int(flags.get("AGENT_TOKEN_BUDGET_DEFAULT", 2200) or 2200)
    per_agent_tokens: Dict[str, int] = {}
    for agent, tb in per_agent.items():
        per_agent_tokens[agent] = int(max(256, token_base * (0.6 + (float(tb) / max(1.0, float(global_budget))))))
    return {
        "global_tool_budget": global_budget,
        "factor": round(float(factor), 4),
        "complexity_hits": complexity_hits,
        "agent_tool_budgets": per_agent,
        "agent_token_budgets": per_agent_tokens,
    }
