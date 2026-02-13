from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional
import hashlib
import json

from src.app.observability.rules_metrics import tier_hit_counter
 
# Try to prefer a centralized RuleEngine when available
try:
    from src.app.rules.engine import RuleEngine as CentralRuleEngine
except Exception:
    CentralRuleEngine = None


@dataclass
class TierDecision:
    tier: int
    reason: str
    tool_budget: int
    model: Optional[str]
    allow_interleaving: bool
    cache_key: Optional[str]


class TierRouter:
    """Simple tier router following Thinking Modes guidance.

    - Tier 0: cache/rules
    - Tier 1: single-pass preserved thinking
    - Tier 2: interleaved, bounded tool budget
    """

    DEFAULT_TIER_2_TRIGGERS = {
        "risk_threshold": 0.5,
        "amount_threshold": 250.0,
        "intent_confidence_low": 0.7,
        "complexity_keywords": [
            "compare",
            "tradeoff",
            "versus",
            "analyze",
            "explain why",
            "best option",
            "recommend",
        ],
    }

    DEFAULT_TOOL_BUDGETS = {0: 0, 1: 1, 2: 4}

    def __init__(self, cache_backend=None, flags: Dict = None):
        self.cache = cache_backend
        self.flags = flags or {}
        # Config-driven triggers (feature flags)
        cfg = {}
        try:
            cfg = (self.flags or {}).get("TIER_ROUTER", {}) if isinstance((self.flags or {}).get("TIER_ROUTER"), dict) else {}
        except Exception:
            cfg = {}
        try:
            self.TIER_2_TRIGGERS = dict(self.DEFAULT_TIER_2_TRIGGERS)
            if isinstance(cfg.get("tier2_triggers"), dict):
                self.TIER_2_TRIGGERS.update(cfg.get("tier2_triggers") or {})
        except Exception:
            self.TIER_2_TRIGGERS = dict(self.DEFAULT_TIER_2_TRIGGERS)
        try:
            tool_budgets_cfg = cfg.get("tool_budgets")
            if isinstance(tool_budgets_cfg, dict):
                # JSON may encode numeric keys as strings
                self.TOOL_BUDGETS = {int(k): int(v) for k, v in tool_budgets_cfg.items()}
            else:
                self.TOOL_BUDGETS = dict(self.DEFAULT_TOOL_BUDGETS)
        except Exception:
            self.TOOL_BUDGETS = dict(self.DEFAULT_TOOL_BUDGETS)
        try:
            if CentralRuleEngine is not None:
                self.rule_engine = CentralRuleEngine()
            else:
                self.rule_engine = None
        except Exception:
            self.rule_engine = None

    def route(self, query: str, context: Dict[str, Any], intent_result: Dict[str, Any], security_analysis: Dict[str, Any]) -> TierDecision:
        cache_key = self._compute_cache_key(query, context)
        # Cache hit -> Tier 0
        try:
            if self.cache and self.cache.get(cache_key) is not None:
                try:
                    tier_hit_counter.labels(tier="0").inc()
                except Exception:
                    pass
                return TierDecision(tier=0, reason="cache_hit", tool_budget=self.TOOL_BUDGETS[0], model=None, allow_interleaving=False, cache_key=cache_key)
        except Exception:
            pass

        # If no intent_result provided, attempt to evaluate via central RuleEngine
        try:
            if (not intent_result or not isinstance(intent_result, dict)) and getattr(self, 'rule_engine', None) is not None:
                intent_result = self.rule_engine.evaluate(query, context)
        except Exception:
            pass

        # Rule-handled intent -> Tier 0
        if isinstance(intent_result, dict) and intent_result.get("handled") and float(intent_result.get("confidence", 0)) >= 0.95:
            try:
                tier_hit_counter.labels(tier="0").inc()
            except Exception:
                pass
            return TierDecision(tier=0, reason="rule_match", tool_budget=self.TOOL_BUDGETS[0], model=None, allow_interleaving=False, cache_key=cache_key)

        # Evaluate Tier 2 triggers
        risk = float((security_analysis or {}).get("risk_adj") or 0)
        amount = float((context or {}).get("amount") or 0)
        intent_conf = float((intent_result or {}).get("confidence") or 1.0)
        q = (query or "").lower()
        reasons = []
        if risk >= self.TIER_2_TRIGGERS["risk_threshold"]:
            reasons.append(f"high_risk:{risk:.2f}")
        if amount >= self.TIER_2_TRIGGERS["amount_threshold"]:
            reasons.append(f"high_amount:{amount:.0f}")
        if intent_conf < self.TIER_2_TRIGGERS["intent_confidence_low"]:
            reasons.append(f"low_confidence:{intent_conf:.2f}")
        for kw in self.TIER_2_TRIGGERS["complexity_keywords"]:
            if kw in q:
                reasons.append(f"keyword:{kw}")
                break
        if (context or {}).get("multi_turn"):
            reasons.append("multi_turn")

        if reasons:
            return TierDecision(tier=2, reason=",".join(reasons), tool_budget=self.TOOL_BUDGETS[2], model=self.flags.get("MODEL_T2"), allow_interleaving=True, cache_key=cache_key)

        # Default Tier 1
        return TierDecision(tier=1, reason="default", tool_budget=self.TOOL_BUDGETS[1], model=self.flags.get("MODEL_T1"), allow_interleaving=False, cache_key=cache_key)

    def _compute_cache_key(self, query: str, context: Dict) -> str:
        normalized = (query or "").lower().strip()
        stable_ctx = {k: context.get(k) for k in sorted(context.keys()) if k in ["sku", "category", "intent", "tenant_id"]}
        data = f"{normalized}|{json.dumps(stable_ctx, sort_keys=True)}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def cache_response(self, key: str, response: Any, ttl: int = 3600):
        try:
            if self.cache:
                self.cache.set(key, json.dumps(response), ex=ttl)
        except Exception:
            pass
