from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from redis import Redis


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_ttl(env_key: str, default: int) -> int:
    try:
        return max(60, int(os.getenv(env_key, str(default))))
    except Exception:
        return default


# ── Typed artifact schemas ──────────────────────────────────────────────────

class CustomerCase(BaseModel):
    """
    Core customer context: intent, budget, constraints, NQE deduplication state.
    previously_asked_ids and nqe_answered_fields are first-class fields here so
    NQE never repeats a question it already asked (BUG-1 fix).
    """
    uid: str
    session_id: str = ""
    intent: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    use_case: Optional[str] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)
    previously_asked_ids: List[str] = Field(default_factory=list)
    nqe_answered_fields: Dict[str, Any] = Field(default_factory=dict)
    preferred_brands: List[str] = Field(default_factory=list)
    avoided_brands: List[str] = Field(default_factory=list)
    turn_count: int = 0
    last_query: Optional[str] = None
    chat_history_summary: Optional[str] = None
    updated_at: str = Field(default_factory=_now_iso)


class OrderFacts(BaseModel):
    """Cart state, order history, shortlist — commerce facts for this session."""
    recent_orders: List[Dict[str, Any]] = Field(default_factory=list)
    cart: List[Dict[str, Any]] = Field(default_factory=list)
    shortlist_skus: List[str] = Field(default_factory=list)
    last_valid_shortlist_skus: List[str] = Field(default_factory=list)
    return_history: List[Dict[str, Any]] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_now_iso)


class RiskSignals(BaseModel):
    """Real-time fraud / security signals for this session. Short TTL — rotate fast."""
    fraud_score: float = 0.0
    signals: List[str] = Field(default_factory=list)
    image_flags: List[str] = Field(default_factory=list)
    policy_blocks: List[str] = Field(default_factory=list)
    last_security_event: Optional[str] = None
    threat_level: str = "none"  # none / low / medium / high / critical
    updated_at: str = Field(default_factory=_now_iso)


class ActionPlan(BaseModel):
    """Current recommendation plan + pending action state + verifier result."""
    recommended_skus: List[str] = Field(default_factory=list)
    next_question: Optional[str] = None
    pending_action: Optional[str] = None
    explanation: Optional[str] = None
    verifier_score: Optional[float] = None
    verifier_policy_citations: List[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_now_iso)


class PolicySnapshot(BaseModel):
    """
    GDPR consent + data retention policy for this user.
    Persists across sessions to avoid re-asking consent on every visit.
    Satisfies GDPR Art. 7 (consent) and EU AI Act Art. 13 (transparency).
    """
    applicable_policies: List[str] = Field(default_factory=list)
    gdpr_consent: bool = False
    personalization_opt_in: bool = False
    retention_tier: str = "standard"
    data_residency: Optional[str] = None
    ai_disclosure_ack: bool = False
    locale: Optional[str] = None
    region: Optional[str] = None
    updated_at: str = Field(default_factory=_now_iso)


# ── Redis key templates ─────────────────────────────────────────────────────

_CUSTOMER_CASE_KEY = "session:{uid}:customer_case"
_ORDER_FACTS_KEY = "session:{uid}:order_facts"
_RISK_SIGNALS_KEY = "session:{uid}:risk_signals"
_ACTION_PLAN_KEY = "session:{uid}:action_plan"
_POLICY_SNAPSHOT_KEY = "session:{uid}:policy_snapshot"

# GDPR-compliant TTLs per artifact type.
# Risk signals rotate fast (1h) so stale threat data doesn't persist.
# Policy snapshot long (12h) so consent doesn't need re-confirmation on each visit.
_TTL_CUSTOMER_CASE = _get_ttl("ARTIFACT_CUSTOMER_CASE_TTL", 86400)
_TTL_ORDER_FACTS = _get_ttl("ARTIFACT_ORDER_FACTS_TTL", 86400)
_TTL_RISK_SIGNALS = _get_ttl("ARTIFACT_RISK_SIGNALS_TTL", 3600)
_TTL_ACTION_PLAN = _get_ttl("ARTIFACT_ACTION_PLAN_TTL", 1800)
_TTL_POLICY_SNAPSHOT = _get_ttl("ARTIFACT_POLICY_SNAPSHOT_TTL", 43200)

_TOUCH_KEYS = [
    (_CUSTOMER_CASE_KEY, _TTL_CUSTOMER_CASE),
    (_ORDER_FACTS_KEY, _TTL_ORDER_FACTS),
    (_POLICY_SNAPSHOT_KEY, _TTL_POLICY_SNAPSHOT),
]

_ALL_ARTIFACT_KEYS = [
    _CUSTOMER_CASE_KEY,
    _ORDER_FACTS_KEY,
    _RISK_SIGNALS_KEY,
    _ACTION_PLAN_KEY,
    _POLICY_SNAPSHOT_KEY,
]


class SessionArtifacts:
    """
    NLAH-style typed artifact store for a single user session.

    Design principles:
    - Reads/writes Redis with in-memory fallback (same pattern as memory.py).
    - All keys are already pseudonymized via hash_uid() at call site.
    - Each artifact has its own TTL matching GDPR data minimisation requirements.
    - erase_all() satisfies GDPR Art. 17 right to erasure with a single call.
    - Never stores raw transcript — only structured state artifacts.
    """

    def __init__(self, redis_client: Redis, uid: str) -> None:
        self.redis = redis_client
        self.uid = uid
        self._local: Dict[str, Dict[str, Any]] = {}

    # ── Internal helpers ────────────────────────────────────────────────────

    def _key(self, template: str) -> str:
        return template.format(uid=self.uid)

    def _read(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            raw = self.redis.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        entry = self._local.get(key)
        if entry and float(entry.get("_exp", 0)) > time.time():
            return entry.get("_v")
        if entry:
            self._local.pop(key, None)
        return None

    def _write(self, key: str, value: Dict[str, Any], ttl: int) -> None:
        payload = json.dumps(value, default=str)
        try:
            self.redis.setex(key, ttl, payload)
        except Exception:
            pass
        self._local[key] = {"_v": value, "_exp": time.time() + ttl}

    # ── CustomerCase ────────────────────────────────────────────────────────

    def get_customer_case(self) -> Optional[CustomerCase]:
        raw = self._read(self._key(_CUSTOMER_CASE_KEY))
        if not raw:
            return None
        try:
            return CustomerCase(**raw)
        except Exception:
            return None

    def set_customer_case(self, case: CustomerCase) -> None:
        case.updated_at = _now_iso()
        self._write(self._key(_CUSTOMER_CASE_KEY), case.model_dump(), _TTL_CUSTOMER_CASE)

    def merge_customer_case(self, **updates: Any) -> CustomerCase:
        """Read-modify-write: update only the provided non-None fields."""
        existing = self.get_customer_case() or CustomerCase(uid=self.uid)
        for k, v in updates.items():
            if v is not None and hasattr(existing, k):
                # Merge lists (e.g. previously_asked_ids) rather than overwrite
                current = getattr(existing, k)
                if isinstance(current, list) and isinstance(v, list):
                    merged = list(dict.fromkeys(current + v))  # dedup, preserve order
                    setattr(existing, k, merged)
                elif isinstance(current, dict) and isinstance(v, dict):
                    current.update(v)
                    setattr(existing, k, current)
                else:
                    setattr(existing, k, v)
        self.set_customer_case(existing)
        return existing

    # ── OrderFacts ──────────────────────────────────────────────────────────

    def get_order_facts(self) -> Optional[OrderFacts]:
        raw = self._read(self._key(_ORDER_FACTS_KEY))
        if not raw:
            return None
        try:
            return OrderFacts(**raw)
        except Exception:
            return None

    def set_order_facts(self, facts: OrderFacts) -> None:
        facts.updated_at = _now_iso()
        self._write(self._key(_ORDER_FACTS_KEY), facts.model_dump(), _TTL_ORDER_FACTS)

    def update_shortlist(self, skus: List[str]) -> None:
        """Only update shortlist when new results are non-empty (BUG-4 fix)."""
        if not skus:
            return
        facts = self.get_order_facts() or OrderFacts()
        facts.last_valid_shortlist_skus = list(facts.shortlist_skus) if facts.shortlist_skus else []
        facts.shortlist_skus = skus
        self.set_order_facts(facts)

    # ── RiskSignals ─────────────────────────────────────────────────────────

    def get_risk_signals(self) -> Optional[RiskSignals]:
        raw = self._read(self._key(_RISK_SIGNALS_KEY))
        if not raw:
            return None
        try:
            return RiskSignals(**raw)
        except Exception:
            return None

    def set_risk_signals(self, signals: RiskSignals) -> None:
        signals.updated_at = _now_iso()
        self._write(self._key(_RISK_SIGNALS_KEY), signals.model_dump(), _TTL_RISK_SIGNALS)

    def update_risk_signals(self, **updates: Any) -> RiskSignals:
        existing = self.get_risk_signals() or RiskSignals()
        for k, v in updates.items():
            if hasattr(existing, k) and v is not None:
                current = getattr(existing, k)
                if isinstance(current, list) and isinstance(v, list):
                    setattr(existing, k, list(set(current + v)))
                else:
                    setattr(existing, k, v)
        self.set_risk_signals(existing)
        return existing

    # ── ActionPlan ──────────────────────────────────────────────────────────

    def get_action_plan(self) -> Optional[ActionPlan]:
        raw = self._read(self._key(_ACTION_PLAN_KEY))
        if not raw:
            return None
        try:
            return ActionPlan(**raw)
        except Exception:
            return None

    def set_action_plan(self, plan: ActionPlan) -> None:
        plan.updated_at = _now_iso()
        self._write(self._key(_ACTION_PLAN_KEY), plan.model_dump(), _TTL_ACTION_PLAN)

    # ── PolicySnapshot ──────────────────────────────────────────────────────

    def get_policy_snapshot(self) -> Optional[PolicySnapshot]:
        raw = self._read(self._key(_POLICY_SNAPSHOT_KEY))
        if not raw:
            return None
        try:
            return PolicySnapshot(**raw)
        except Exception:
            return None

    def set_policy_snapshot(self, snapshot: PolicySnapshot) -> None:
        snapshot.updated_at = _now_iso()
        self._write(self._key(_POLICY_SNAPSHOT_KEY), snapshot.model_dump(), _TTL_POLICY_SNAPSHOT)

    # ── GDPR erasure — Art. 17 right to erasure ────────────────────────────

    def erase_all(self) -> int:
        """Delete every artifact for this user from Redis and local cache."""
        deleted = 0
        for template in _ALL_ARTIFACT_KEYS:
            key = self._key(template)
            try:
                deleted += int(self.redis.delete(key) or 0)
            except Exception:
                pass
            self._local.pop(key, None)
        return deleted

    # ── Session activity touch (extend TTLs on each interaction) ───────────

    def touch(self) -> None:
        for template, ttl in _TOUCH_KEYS:
            try:
                self.redis.expire(self._key(template), ttl)
            except Exception:
                pass

    # ── Convenience: build NQEInput kwargs from stored artifacts ───────────

    def nqe_kwargs(self) -> Dict[str, Any]:
        """
        Return kwargs to inject into NQEInput so NQE never repeats a question
        it already asked and knows all answered fields from prior turns.
        """
        case = self.get_customer_case()
        if not case:
            return {"previously_asked_ids": [], "answered_fields": {}}
        return {
            "previously_asked_ids": list(case.previously_asked_ids),
            "answered_fields": dict(case.nqe_answered_fields),
            "chat_history_summary": case.chat_history_summary,
        }

    def after_nqe(self, asked_ids: List[str], answered: Dict[str, Any]) -> None:
        """Persist NQE results back into CustomerCase after each NQE call."""
        self.merge_customer_case(
            previously_asked_ids=asked_ids,
            nqe_answered_fields=answered,
        )
