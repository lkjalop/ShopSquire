from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Dict, List, Tuple, Optional, Union

class RuleResult:
    def __init__(self, ok: bool, score: float = 0.0, reasons: List[str] | None = None, details: Dict[str, Any] | None = None):
        self.ok = ok
        self.score = float(score or 0.0)
        self.reasons = reasons or []
        self.details = details or {}

class Rule:
    def __init__(self, id: str, priority: int, fn: Callable[[Dict[str, Any]], RuleResult]):
        self.id = id
        self.priority = priority
        self.fn = fn


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    title: str
    priority: int
    pattern: str | None = None
    expression: str | None = None
    tenant_id: str | None = None
    domain: str | None = None


class RuleEngine:
    """Central rule engine.

    Prefers DB-backed `rule_definitions` (RuleStore) when available, and supports
    legacy callable rules via `Rule` objects.
    """
    INTERNAL_INTENT_PATTERNS: Dict[str, List[str]] = {
        "product_search": [r"show\s+me", r"find", r"search\s+for", r"looking\s+for", r"i\s+need", r"i\s+want"],
        "price_check": [r"how\s+much", r"price\s+of", r"cost", r"pricing"],
        "comparison": [r"compare", r"vs", r"versus", r"difference\s+between", r"which\s+is\s+better"],
        "order_status": [r"where\s+is\s+my\s+order", r"track", r"order\s+status", r"shipping\s+status"],
        "return_request": [r"return", r"refund", r"exchange", r"send\s+back"],
        "support": [r"help", r"support", r"issue", r"problem", r"not\s+working"],
        "stock_check": [r"in\s+stock", r"available", r"how\s+many\s+left", r"stock\s+level"],
        "restock_alert": [r"notify\s+me", r"alert\s+when", r"back\s+in\s+stock", r"restock"],
        "bulk_inquiry": [r"bulk\s+order", r"wholesale", r"large\s+quantity", r"volume\s+discount"],
        "urgent_need": [r"urgent", r"asap", r"need\s+today", r"rush", r"express"],
        "pre_order": [r"pre-order", r"preorder", r"reserve", r"coming\s+soon"],
    }

    def __init__(self, rules: List[Rule] | None = None, *, rule_store: Any | None = None):
        self.rules = sorted(rules or [], key=lambda r: r.priority)
        self.rule_store = rule_store
        self._compiled: Dict[str, re.Pattern] = {}
        self._db_rules: List[RuleDefinition] = []
        self._active_db_key: Tuple[str | None, str | None] = (None, None)
        self._refresh_db_rules()

    def _refresh_db_rules(self, *, tenant_id: str | None = None, domain: str | None = None) -> None:
        try:
            if self.rule_store is None:
                from src.app.services.rule_store import RuleStore

                self.rule_store = RuleStore()
        except Exception:
            self.rule_store = None
        if self.rule_store is None:
            self._db_rules = []
            return
        key = (tenant_id, domain)
        if key == self._active_db_key and self._db_rules:
            return
        self._active_db_key = key
        try:
            rows = self.rule_store.get_active_rules(tenant_id, domain=domain)
        except Exception:
            rows = []
        out: List[RuleDefinition] = []
        for r in rows or []:
            try:
                out.append(
                    RuleDefinition(
                        id=str(r.get("id")),
                        title=str(r.get("title") or ""),
                        priority=int(r.get("priority") or 100),
                        pattern=(str(r.get("pattern")) if r.get("pattern") else None),
                        expression=(str(r.get("expression")) if r.get("expression") else None),
                        tenant_id=(str(r.get("tenant_id")) if r.get("tenant_id") else None),
                        domain=(str(r.get("domain")) if r.get("domain") else None),
                    )
                )
            except Exception:
                continue
        self._db_rules = sorted(out, key=lambda x: x.priority)
        self._compiled = {}
        for rd in self._db_rules:
            if not rd.pattern:
                continue
            try:
                self._compiled[rd.id] = re.compile(rd.pattern, flags=re.IGNORECASE)
            except re.error:
                continue

    def evaluate(self, query: Union[str, Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Evaluate rules against an input context.

        Callers in the codebase use two common shapes:
        - `evaluate(context_dict)` (legacy)
        - `evaluate(query, context_dict)` (TierRouter/Orchestrator integration)
        """
        if context is None and isinstance(query, dict):
            ctx: Dict[str, Any] = dict(query)
        else:
            ctx = dict(context or {})
            if query is not None and "query" not in ctx:
                ctx["query"] = query

        # Tenant-aware: refresh DB rules when a tenant_id exists in context.
        tenant_id: str | None = None
        domain: str | None = None
        try:
            if isinstance(ctx, dict):
                mem = ctx.get("memory") if isinstance(ctx.get("memory"), dict) else {}
                live = ctx.get("live") if isinstance(ctx.get("live"), dict) else {}
                tenant_id = (mem or {}).get("tenant_id") or (live or {}).get("tenant_id") or ctx.get("tenant_id")
                if tenant_id is not None:
                    tenant_id = str(tenant_id)
                domain = ctx.get("domain") or ctx.get("capability") or (live or {}).get("domain") or (mem or {}).get("domain")
                if domain is not None:
                    domain = str(domain)
        except Exception:
            tenant_id = None
            domain = None
        try:
            if tenant_id or domain:
                self._refresh_db_rules(tenant_id=tenant_id, domain=domain)
        except Exception:
            pass

        q = ""
        try:
            q = str(ctx.get("query") or "")
        except Exception:
            q = ""
        # DB-backed rules: first match wins (priority-ordered).
        try:
            for rd in self._db_rules:
                if not rd.pattern:
                    continue
                pat = self._compiled.get(rd.id)
                if not pat:
                    continue
                if pat.search(q):
                    return {
                        "handled": True,
                        "intent": rd.title,
                        "confidence": 0.95,
                        "rule_id": rd.id,
                        "rule_hits": [{"id": rd.id, "priority": rd.priority, "details": {"intent": rd.title}}],
                        "aggregate_score": 0.0,
                    }
        except Exception:
            pass

        # Internal fallback patterns (helps dev/demo when DB rules are not seeded).
        try:
            import os

            enabled = os.getenv("RULE_ENGINE_INTERNAL_PATTERNS", "1").strip().lower() in ("1", "true", "yes", "on")
            if enabled and q:
                for intent, patterns in self.INTERNAL_INTENT_PATTERNS.items():
                    for pat in patterns:
                        try:
                            if re.search(pat, q, flags=re.IGNORECASE):
                                rid = f"internal:{intent}"
                                return {
                                    "handled": True,
                                    "intent": intent,
                                    "confidence": 0.9,
                                    "rule_id": rid,
                                    "rule_hits": [{"id": rid, "priority": 9999, "details": {"intent": intent}}],
                                    "aggregate_score": 0.0,
                                }
                        except re.error:
                            continue
        except Exception:
            pass
        hits: List[Dict[str, Any]] = []
        score = 0.0
        for r in self.rules:
            try:
                res = r.fn(ctx)
                if res and not res.ok:
                    hits.append({"id": r.id, "priority": r.priority, "reasons": res.reasons, "details": res.details})
                try:
                    score += float(res.score or 0.0)
                except Exception:
                    pass
            except Exception:
                hits.append({"id": r.id, "priority": r.priority, "reasons": ["rule_error"]})
        # Keep a TierRouter-friendly shape (it looks for handled/confidence).
        # When no rules are configured this returns unhandled with confidence unset
        # so routers fall back to their default behavior.
        out: Dict[str, Any] = {"rule_hits": hits, "aggregate_score": score, "handled": False, "confidence": None}
        # If any rule explicitly emitted an intent, surface it as a convenience.
        try:
            for h in hits:
                det = h.get("details") or {}
                if isinstance(det, dict) and det.get("intent"):
                    out["intent"] = det.get("intent")
                    break
        except Exception:
            pass
        return out
