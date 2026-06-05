from __future__ import annotations

"""
Post-action verifier with AgentSpec-style hard rules + corrective RAG.

Design (from harness engineering research):
  1. Hard deterministic rules run first (<1ms, no LLM cost).
     Clear-cut cases are resolved here — never waste tokens on obvious decisions.
  2. LLM soft-verifier for ambiguous cases.
     Uses the smallest capable model (air-gapped qwen2.5:14b or llama3.1:8b).
     NEVER routes customer PII to external APIs — data sovereignty compliance.
  3. Corrective RAG if score < threshold.
     Retrieves policy citations so the human reviewer understands WHY escalation
     was triggered — satisfies EU AI Act Art. 14 (human oversight) and Art. 13
     (transparency).

LLM selection rationale:
  - llama3.1:8b  : fast (~200ms), air-gapped ✅, but weak at structured JSON
                   output for complex multi-signal reasoning.
  - qwen2.5:14b  : 32K context, strong structured output, still air-gapped ✅.
                   Recommended for verifier tasks — better reasoning, still local.
  - Sonnet 4.6   : best quality but NOT air-gapped → sends customer PII to
                   Anthropic API. Unacceptable for session data containing orders,
                   fraud signals, or personal context without explicit DPA +
                   customer consent (GDPR Art. 46; AU Privacy Act APP 8).
                   Use only for internal non-PII tasks (code gen, doc analysis).
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.services.session_artifacts import PolicySnapshot, RiskSignals

logger = logging.getLogger("shopsquire.action_verifier")

_VERIFIER_THRESHOLD = float(os.getenv("VERIFIER_SCORE_THRESHOLD", "0.70"))
_VERIFIER_MODEL_PREF = os.getenv("VERIFIER_LLM_MODEL", "qwen2.5:14b")
_CORRECTIVE_RAG_ENABLED = os.getenv("VERIFIER_CORRECTIVE_RAG_ENABLED", "1") == "1"
_CORRECTIVE_RAG_TOP_K = int(os.getenv("VERIFIER_CORRECTIVE_RAG_TOP_K", "3"))


@dataclass
class VerifierResult:
    score: float
    verdict: str          # "confirmed" | "uncertain" | "disagree"
    reason: str
    policy_citations: List[str] = field(default_factory=list)
    escalate: bool = False
    hard_rule_fired: bool = False

    @property
    def should_escalate(self) -> bool:
        return self.score < _VERIFIER_THRESHOLD


# ── AgentSpec hard rules ────────────────────────────────────────────────────
# These fire deterministically before any LLM call.
# Each rule returns a score or None (= let LLM decide).

def _hard_rules(
    action: str,
    risk: RiskSignals,
    policy: PolicySnapshot,
) -> Optional[float]:
    # Critical threat: block is always justified
    if action == "block" and risk.threat_level == "critical":
        return 1.0

    # High threat with explicit policy block: justified
    if action == "block" and risk.threat_level == "high" and bool(risk.policy_blocks):
        return 0.9

    # No signals at all → blocking is unjustified
    if action == "block" and not risk.signals and not risk.policy_blocks and risk.fraud_score < 0.3:
        return 0.1

    # PII export without GDPR consent → always escalate
    if action in ("pii_export", "data_export") and not policy.gdpr_consent:
        return 0.0

    # High-value return approval without consent confirmation → escalate
    if action == "return_approve" and not policy.gdpr_consent and not policy.personalization_opt_in:
        return 0.0

    # Security block with fraud score well above threshold → justified
    if action == "security_block" and risk.fraud_score >= 0.8:
        return 0.95

    # Escalation with high fraud score → always confirmed
    if action == "escalate_human" and risk.fraud_score >= 0.7:
        return 1.0

    return None  # LLM decides


# ── Corrective RAG ──────────────────────────────────────────────────────────

def _corrective_rag_lookup(action: str, reason: str) -> List[str]:
    """
    Query the policy knowledge base for citations relevant to the action + reason.
    Called only when verifier disagrees — gives human reviewer policy context.
    """
    if not _CORRECTIVE_RAG_ENABLED:
        return []
    try:
        from src.app.rag.retrieve import Retriever  # noqa: PLC0415
        retriever = Retriever()
        query = f"policy action:{action} reason:{reason} compliance requirement"
        results = retriever.retrieve(query, k=_CORRECTIVE_RAG_TOP_K)
        citations = []
        for r in results or []:
            # RetrievedChunk has .text; fall back to dict-style for other shapes
            text = str(getattr(r, "text", None) or r.get("content") or r.get("text") or r.get("chunk") or "")
            if text.strip():
                citations.append(text.strip()[:250])
        return citations
    except Exception as exc:
        logger.debug("Corrective RAG lookup failed: %s", exc)
        return []


# ── LLM soft verifier ───────────────────────────────────────────────────────

def _build_verifier_prompt(
    action: str,
    risk: RiskSignals,
    policy: PolicySnapshot,
    agent_reasoning: Optional[str],
) -> str:
    return f"""You are a compliance verifier. Respond with JSON only — no explanation outside the JSON.

ACTION TAKEN: {action}
FRAUD_SCORE: {round(risk.fraud_score, 3)}
THREAT_LEVEL: {risk.threat_level}
SIGNALS: {json.dumps(risk.signals[:6])}
POLICY_BLOCKS: {json.dumps(risk.policy_blocks[:4])}
GDPR_CONSENT: {policy.gdpr_consent}
AGENT_REASONING: {str(agent_reasoning or '')[:400]}

Task: Was this action justified by the evidence above?
Respond ONLY with: {{"score": <0.0-1.0>, "reason": "<brief_snake_case_reason>"}}
1.0 = fully justified. 0.0 = not justified at all."""


def _call_llm_verifier(
    prompt: str,
    llm_provider: Any,
) -> tuple[float, str]:
    try:
        resp = llm_provider.complete(
            prompt=prompt,
            max_tokens=80,
            temperature=0.0,
            model_override=_VERIFIER_MODEL_PREF,
        )
        text = str(resp or "")
        m = re.search(r'\{[^}]+\}', text)
        if not m:
            return 0.65, "parse_error"
        obj = json.loads(m.group(0))
        score = max(0.0, min(1.0, float(obj.get("score", 0.65))))
        reason = str(obj.get("reason") or "llm_verdict")[:80]
        return score, reason
    except Exception as exc:
        logger.warning("LLM verifier failed: %s", exc)
        return 0.65, "verifier_error"


# ── Public entry point ──────────────────────────────────────────────────────

def verify_action(
    action: str,
    risk_signals: RiskSignals,
    policy_snapshot: PolicySnapshot,
    *,
    agent_reasoning: Optional[str] = None,
    llm_provider: Any = None,
) -> VerifierResult:
    """
    Verify whether `action` was justified.

    Call this AFTER Policy_Gate (pre-action guard) has already passed.
    This is the post-action independent check — catches cases where the LLM
    reasoned itself into an unjustified decision.

    Args:
        action: The action taken (e.g. "block", "return_approve", "escalate_human").
        risk_signals: Current session risk artifact.
        policy_snapshot: Current session policy/consent artifact.
        agent_reasoning: Optional string from the agent that took the action.
        llm_provider: Optional LLM provider for soft verification.
                      Must be air-gapped (Ollama). Never pass an external
                      API provider when risk_signals contains customer data.
    Returns:
        VerifierResult with score, verdict, reason, policy citations.
    """
    # Step 1: Hard rules (AgentSpec pattern — deterministic, no LLM cost)
    hard_score = _hard_rules(action, risk_signals, policy_snapshot)
    if hard_score is not None:
        verdict = _score_to_verdict(hard_score)
        citations = (
            _corrective_rag_lookup(action, "hard_rule_override")
            if hard_score < _VERIFIER_THRESHOLD else []
        )
        return VerifierResult(
            score=hard_score,
            verdict=verdict,
            reason="hard_rule",
            policy_citations=citations,
            escalate=hard_score < _VERIFIER_THRESHOLD,
            hard_rule_fired=True,
        )

    # Step 2: LLM soft verification (only if provider given)
    if llm_provider is not None:
        prompt = _build_verifier_prompt(action, risk_signals, policy_snapshot, agent_reasoning)
        score, reason = _call_llm_verifier(prompt, llm_provider)
    else:
        # No LLM → conservative uncertain score
        score = 0.65
        reason = "no_llm_provider"

    # Step 3: Corrective RAG if disagreement
    citations: List[str] = []
    if score < _VERIFIER_THRESHOLD:
        citations = _corrective_rag_lookup(action, reason)

    verdict = _score_to_verdict(score)
    return VerifierResult(
        score=score,
        verdict=verdict,
        reason=reason,
        policy_citations=citations,
        escalate=score < _VERIFIER_THRESHOLD,
        hard_rule_fired=False,
    )


def _score_to_verdict(score: float) -> str:
    if score >= _VERIFIER_THRESHOLD:
        return "confirmed"
    if score >= 0.5:
        return "uncertain"
    return "disagree"


# ── Convenience wrapper for high-stakes ecommerce actions ──────────────────

def verify_return_approval(
    order_value: float,
    risk_signals: RiskSignals,
    policy_snapshot: PolicySnapshot,
    *,
    llm_provider: Any = None,
) -> VerifierResult:
    """
    Evidence-before-action gate for return approvals (EU AI Act Art. 14).
    Tiered evidence requirements based on order value:
      < $50   : 1 signal sufficient
      $50-500 : 2 signals required
      > $500  : 3 signals + human-in-loop regardless of verifier score
    """
    n_signals = len(risk_signals.signals) + (1 if risk_signals.fraud_score > 0.4 else 0)

    if order_value > 500:
        # Always escalate for high-value returns — no autonomous approval
        return VerifierResult(
            score=0.0,
            verdict="disagree",
            reason="high_value_return_requires_human",
            policy_citations=["EU AI Act Art. 14: human oversight required for high-risk decisions"],
            escalate=True,
            hard_rule_fired=True,
        )

    required_signals = 2 if order_value >= 50 else 1
    if n_signals < required_signals:
        return VerifierResult(
            score=0.3,
            verdict="disagree",
            reason=f"insufficient_evidence_{n_signals}_of_{required_signals}_required",
            policy_citations=_corrective_rag_lookup("return_approve", "insufficient_evidence"),
            escalate=True,
            hard_rule_fired=True,
        )

    return verify_action(
        "return_approve",
        risk_signals,
        policy_snapshot,
        agent_reasoning=f"order_value={order_value} signals={n_signals}",
        llm_provider=llm_provider,
    )
