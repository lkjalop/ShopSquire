from __future__ import annotations

from typing import Dict, Any, List, Optional

from src.app.services.rule_store import RuleStore
from src.app.observability.rules_metrics import rule_match_counter, rule_miss_counter, rule_latency_hist


class ExpandedRuleEngine:
    """Compatibility wrapper around the central `RuleEngine`.

    Historically the codebase used `ExpandedRuleEngine` from `services/`. The
    roadmap calls for a single central rule engine; use `src.app.rules.engine.RuleEngine`
    as the source of truth and keep this wrapper so older imports keep working.
    """

    def __init__(self, rule_store: Optional[RuleStore] = None):
        from src.app.rules.engine import RuleEngine

        self.rule_store = rule_store or RuleStore()
        self._engine = RuleEngine(rule_store=self.rule_store)

    def evaluate(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = None
        try:
            mem = context.get("memory") if isinstance(context, dict) else {}
            live = context.get("live") if isinstance(context, dict) else {}
            tenant_id = (mem or {}).get("tenant_id") or (live or {}).get("tenant_id")
        except Exception:
            tenant_id = None

        start = __import__('time').perf_counter()
        out: Dict[str, Any] = {}
        try:
            out = self._engine.evaluate(query, context or {})
        except Exception:
            out = {"handled": False, "reason": "rule_engine_error", "confidence": 0.0}

        try:
            if out.get("handled"):
                rule_match_counter.labels(tenant_id=str(tenant_id or "global")).inc()
            else:
                rule_miss_counter.labels(tenant_id=str(tenant_id or "global")).inc()
            rule_latency_hist.observe(__import__("time").perf_counter() - start)
        except Exception:
            pass

        if not out.get("handled"):
            out.setdefault("reason", "no_rule_match")
            if out.get("confidence") in (None, ""):
                out["confidence"] = 0.0
        return out
