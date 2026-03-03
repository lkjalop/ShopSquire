import base64
import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Tuple, List
import asyncio

from src.app.models.db import db_session
from src.app.repositories.catalog import CatalogRepository
from src.app.services.memory import Memory
from src.app.security.firewall import TransactionFirewall
import random
import time
from sqlalchemy import text
from src.app.observability.metrics import chaos_injected_total
from src.app.observability.metrics import record_cv_auto_decision, record_cv_escalation, record_security_event
from src.app.observability.health import dependency_health_snapshot
from src.app.deps import security_sanitize, hash_uid
from src.app.security.observer import analyze_payload
 
from src.app.services.ticketing import TicketingAgent
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.services.tier_router import TierRouter
try:
    from src.app.services.tier_router_learned import LearnedTierRouter, LearnedTierDecision
except Exception:
    LearnedTierRouter = None
    LearnedTierDecision = None
from src.app.rules.engine import RuleEngine
from src.app.services.llm import LLMOrchestrator
from src.app.services.semantic_cache import SemanticCache
from src.app.services.policy_gate import PolicyGate
from src.app.services.recommendations import RecommendationService
from src.app.services.interleaving_controller import InterleavingController, run_interleaved
from src.app.services.agent_types import AgentType, agent_type_for_name
from src.app.observability.metrics import (
    record_agent_invocation,
    record_agent_escalation,
    record_parallel_cache_event,
)
from src.app.services.confidence_calibration import calibrate_confidence
from src.app.services.agent_bus import AgentBus
from src.app.services.agent_handoff import request_handoff_best_effort
from src.app.services.agent_workflow import (
    apply_synthesis_to_policy,
    deterministic_conflict_resolution,
    validate_phase_agents,
)
from src.app.services.playbook_engine import (
    append_playbook_step,
    complete_playbook_run,
    execute_typed_actions,
    start_playbook_run,
)
from src.app.policy.gate import evaluate_policy_gate
from src.app.security.tool_intent_gate import evaluate_tool_intent
from src.app.security.agent_guardrails import assess_agent_interaction

# analytics.ragas is optional; provide no-op fallbacks when missing
try:
    from src.app.analytics.ragas import evaluate_decision_stub, persist_ragas_stub
except Exception:
    def evaluate_decision_stub(*_, **__):
        return None

    def persist_ragas_stub(*_, **__):
        return None

# Layer 2 / 3 / 4 memory integrations (optional)
try:
    from src.app.services.episodic_memory import EpisodicMemory
except Exception:
    EpisodicMemory = None
try:
    from src.app.services.observation_engine import Observer, Reflector
except Exception:
    Observer = None
    Reflector = None
try:
    from src.app.services.citation_memory import store_claim, get_agent_trust_score
except Exception:
    store_claim = None
    get_agent_trust_score = None


@dataclass
class OrchestratorResult:
    proposal: Dict[str, Any]
    firewall: Dict[str, Any]
    executed: bool
    timings: Dict[str, float] | None = None


class Orchestrator:
    def __init__(self, memory: Memory, firewall: TransactionFirewall, flags: Dict):
        self.memory = memory
        self.firewall = firewall
        self.flags = flags
        self.catalog = CatalogRepository()
        # Tier routing
        try:
            # Instantiate semantic cache (uses REDIS_URL if set)
            try:
                redis_url = flags.get("REDIS_URL") or __import__('os').environ.get('REDIS_URL')
            except Exception:
                redis_url = None
            cache = SemanticCache(redis_url=redis_url)
            self.tier_router = TierRouter(cache_backend=cache, flags=flags)
            try:
                # Optional learned router layered on top of TierRouter
                learned_enabled = str(flags.get("LEARNED_TIER_ROUTER_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
                self.learned_router = LearnedTierRouter(flags=flags) if (learned_enabled and LearnedTierRouter is not None) else None
            except Exception:
                self.learned_router = None
        except Exception:
            self.tier_router = None
        # LLM orchestrator client used for rerank/other text model calls
        try:
            self.llm = LLMOrchestrator()
        except Exception:
            self.llm = None
        # Central rule engine (DB-backed rules + internal patterns fallback).
        try:
            self.rule_engine = RuleEngine()
        except Exception:
            self.rule_engine = None
        # Policy gate (LLM or rules-based policy evaluator)
        try:
            self.policy_gate = PolicyGate(flags=flags)
        except Exception:
            self.policy_gate = None

        # Incident ticket idempotency (redis-backed best-effort)
        try:
            self._incident_idem_ttl = int(flags.get("INCIDENT_IDEMPOTENCY_TTL", 3600) or 3600)
        except Exception:
            self._incident_idem_ttl = 3600
        # Per-trace runtime flags (best-effort), used for SLO-triggered degrade paths.
        self._trace_runtime_flags: Dict[str, Dict[str, Any]] = {}

    def _init_trace_runtime(self, trace_id: str | None) -> None:
        if not trace_id:
            return
        try:
            self._trace_runtime_flags[str(trace_id)] = {
                "degraded": False,
                "degrade_reasons": [],
                "adaptive_budget": {},
            }
        except Exception:
            pass

    def _mark_trace_degraded(self, trace_id: str | None, reason: str) -> None:
        if not trace_id:
            return
        try:
            key = str(trace_id)
            st = self._trace_runtime_flags.get(key) or {"degraded": False, "degrade_reasons": [], "adaptive_budget": {}}
            st["degraded"] = True
            reasons = st.get("degrade_reasons")
            if not isinstance(reasons, list):
                reasons = []
            if reason and reason not in reasons:
                reasons.append(reason)
            st["degrade_reasons"] = reasons
            self._trace_runtime_flags[key] = st
        except Exception:
            pass

    def _trace_is_degraded(self, trace_id: str | None) -> bool:
        if not trace_id:
            return False
        try:
            return bool((self._trace_runtime_flags.get(str(trace_id)) or {}).get("degraded"))
        except Exception:
            return False

    def _trace_degrade_reasons(self, trace_id: str | None) -> List[str]:
        if not trace_id:
            return []
        try:
            rs = (self._trace_runtime_flags.get(str(trace_id)) or {}).get("degrade_reasons")
            return list(rs or []) if isinstance(rs, list) else []
        except Exception:
            return []

    def _clear_trace_runtime(self, trace_id: str | None) -> None:
        if not trace_id:
            return
        try:
            self._trace_runtime_flags.pop(str(trace_id), None)
        except Exception:
            pass

    def _agent_step_slo_ms(self, agent_name: str) -> int:
        default_ms = int(self.flags.get("AGENT_STEP_SLO_MS_DEFAULT", 1800) or 1800)
        env_map = str(self.flags.get("AGENT_STEP_SLO_MS_MAP", "") or "").strip()
        if env_map:
            try:
                if env_map.startswith("{"):
                    import json as _json

                    raw = _json.loads(env_map)
                    if isinstance(raw, dict):
                        v = raw.get(agent_name)
                        if v is not None:
                            return int(v)
                else:
                    for part in env_map.split(","):
                        if ":" not in part:
                            continue
                        k, v = part.split(":", 1)
                        if str(k).strip() == agent_name:
                            return int(v)
            except Exception:
                pass
        return default_ms

    def _compute_adaptive_agent_budgets(
        self,
        *,
        query: str,
        tier: int,
        base_tool_budget: int,
        risk_adj: float,
        intent_confidence: float,
        multi_turn: bool,
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
        token_base = int(self.flags.get("AGENT_TOKEN_BUDGET_DEFAULT", 2200) or 2200)
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

    def _ensure_trace_id(self, payload: Dict[str, Any]) -> str:
        trace_id = payload.get("trace_id") if isinstance(payload, dict) else None
        if not trace_id:
            trace_id = str(uuid.uuid4())
            try:
                payload["trace_id"] = trace_id
                payload["decision_id"] = trace_id
            except Exception:
                pass
        return trace_id

    def _trace_phase(self, trace_id: str | None, phase: str, status: str, agents_planned: List[str] | None = None, meta: Dict[str, Any] | None = None) -> None:
        """Emit a phase_started/phase_completed trace with planned agent names and metadata."""
        if not trace_id:
            return
        try:
            payload = {"phase": phase, "status": status}
            if agents_planned:
                payload["agents_planned"] = agents_planned
                payload["agent_types"] = [agent_type_for_name(a).value for a in agents_planned]
                ok, violations = validate_phase_agents(phase, agents_planned)
                payload["phase_contract_ok"] = ok
                if violations:
                    payload["phase_contract_violations"] = violations[:8]
            if isinstance(meta, dict):
                payload.update(meta)
            log_trace_event(
                trace_id=trace_id,
                event_type=f"phase_{status}",
                source_type="orchestrator",
                source_id=f"phase:{phase}",
                target_type=None,
                target_id=None,
                payload=payload,
            )
        except Exception:
            pass

        try:
            print(f"[orch.run] after auto-decision block; proposal_keys={list(proposal.keys())[:8] if isinstance(proposal, dict) else None}")
        except Exception:
            pass

    def _trace_agent_invocation(self, trace_id: str | None, *, phase: str, agent_name: str, start_ms: float, end_ms: float, tags: List[str] | None = None, tool_budget_remaining: int | None = None) -> None:
        """Emit an agent_invocation trace with latency and evidence tags."""
        if not trace_id:
            return
        try:
            latency_ms = max(0, int((end_ms - start_ms) * 1000.0))
            payload = {
                "phase": phase,
                "agent": agent_name,
                "agent_type": agent_type_for_name(agent_name).value,
                "latency_ms": latency_ms,
                "tool_budget_remaining": tool_budget_remaining,
            }
            if tags:
                payload["tags"] = tags[:12]
            log_trace_event(
                trace_id=trace_id,
                event_type="agent_invocation",
                source_type="orchestrator",
                source_id="agent_runner",
                target_type="agent",
                target_id=agent_name,
                payload=payload,
            )
            try:
                slo_ms = int(self._agent_step_slo_ms(agent_name))
            except Exception:
                slo_ms = 0
            if slo_ms > 0 and latency_ms > slo_ms:
                self._mark_trace_degraded(trace_id, "step_slo_breach")
                log_trace_event(
                    trace_id=trace_id,
                    event_type="step_slo_breach",
                    source_type="orchestrator",
                    source_id="slo_guard",
                    target_type="agent",
                    target_id=agent_name,
                    payload={
                        "agent": agent_name,
                        "phase": phase,
                        "latency_ms": latency_ms,
                        "slo_ms": slo_ms,
                        "breach_ratio": round(float(latency_ms) / float(max(1, slo_ms)), 4),
                        "auto_degrade": True,
                    },
                )
        except Exception:
            pass

    def _emit_agent_handoff(
        self,
        *,
        from_agent: str,
        to_agent: str,
        reason: str,
        context: Dict[str, Any],
        trace_id: str,
    ) -> None:
        try:
            redis_client = getattr(self.memory, "redis", None)
            if redis_client is None:
                return
            request_handoff_best_effort(
                bus=AgentBus(redis_client),
                from_agent=from_agent,
                to_agent=to_agent,
                reason=reason,
                context=context,
                trace_id=trace_id,
            )
        except Exception:
            pass

    def _incident_keys(
        self,
        *,
        trace_id: str | None,
        idempotency_key: str | None,
        tenant_id: str | None,
    ) -> List[str]:
        keys: List[str] = []
        tenant = str(tenant_id or "default")
        if trace_id:
            keys.append(f"incident_ticketed:trace:{tenant}:{trace_id}")
        if idempotency_key:
            keys.append(f"incident_ticketed:idem:{tenant}:{idempotency_key}")
        return keys

    def _incident_already_ticketed(
        self,
        trace_id: str | None,
        idempotency_key: str | None = None,
        tenant_id: str | None = None,
    ) -> bool:
        keys = self._incident_keys(trace_id=trace_id, idempotency_key=idempotency_key, tenant_id=tenant_id)
        if not keys:
            return False
        try:
            redis_client = getattr(self.memory, "redis", None)
            if redis_client is None:
                return False
            for key in keys:
                raw = redis_client.get(key)
                if raw:
                    return True
            return False
        except Exception:
            return False

    def _mark_incident_ticketed(
        self,
        trace_id: str | None,
        idempotency_key: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        keys = self._incident_keys(trace_id=trace_id, idempotency_key=idempotency_key, tenant_id=tenant_id)
        if not keys:
            return
        try:
            redis_client = getattr(self.memory, "redis", None)
            if redis_client is None:
                return
            for key in keys:
                redis_client.setex(key, self._incident_idem_ttl, "1")
        except Exception:
            pass

    def _agent_guardrail(
        self,
        *,
        trace_id: str | None,
        agent_name: str,
        stage: str,
        payload: Dict[str, Any] | None,
        tenant_id: str | None,
    ) -> Dict[str, Any]:
        decision = assess_agent_interaction(
            agent_name=agent_name,
            stage=stage,
            payload=payload or {},
            tenant_id=tenant_id,
            trace_id=trace_id,
        )
        try:
            if trace_id:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="agent_guardrail",
                    source_type="security",
                    source_id=agent_name,
                    target_type="agent",
                    target_id=agent_name,
                    payload=decision,
                )
        except Exception:
            pass
        return decision

    def _create_incident_ticket(
        self,
        *,
        title: str,
        description: str,
        severity: str,
        tenant_id: str | None,
        trace_id: str | None,
    ):
        t = TicketingAgent()
        try:
            return t.create_ticket(
                title=title,
                description=description,
                severity=severity,
                tenant_id=tenant_id,
                trace_id=trace_id,
            )
        except TypeError:
            # Backward-compatible signature used by tests/mocks.
            return t.create_ticket(title=title, description=description, severity=severity, tenant_id=tenant_id)

    def _assign_ab_variant(self, trace_id: str) -> Dict[str, Any]:
        """Assign AB test variant and compute per-variant overrides.

        Flags:
          - AB_TEST_ENABLED: bool
          - AB_VARIANT_B_FORCE_PARALLEL: bool
          - AB_VARIANT_B_ENABLE_CV_INTERLEAVING: bool

        Returns: {"variant": "A"|"B", "overrides": {...}}
        """
        try:
            enabled = bool(self.flags.get("AB_TEST_ENABLED", False))
        except Exception:
            enabled = False
        if not enabled:
            return {"variant": "A", "overrides": {}}
        try:
            h = __import__("hashlib").sha1((trace_id or "").encode("utf-8")).hexdigest()
            bucket = int(h[:2], 16) % 2
        except Exception:
            bucket = 0
        variant = "B" if bucket == 1 else "A"
        overrides: Dict[str, Any] = {}
        if variant == "B":
            if bool(self.flags.get("AB_VARIANT_B_FORCE_PARALLEL", True)):
                overrides["force_parallel"] = True
            if bool(self.flags.get("AB_VARIANT_B_ENABLE_CV_INTERLEAVING", False)):
                overrides["cv_interleaving_enabled"] = True
        return {"variant": variant, "overrides": overrides}

    def _decode_images(self, images: Any) -> List[bytes]:
        if not images:
            return []
        if isinstance(images, (str, bytes)):
            images = [images]
        out: List[bytes] = []
        for item in images or []:
            if not item:
                continue
            if isinstance(item, bytes):
                out.append(item)
                continue
            if not isinstance(item, str):
                continue
            b64 = item
            if item.startswith("data:") and "," in item:
                b64 = item.split(",", 1)[1]
            try:
                out.append(base64.b64decode(b64))
            except Exception:
                continue
        return out

    def detect_complaint_intent(self, query: str, ctx: Dict[str, Any] | None = None) -> bool:
        if not query:
            return False
        try:
            if getattr(self, "rule_engine", None) is None:
                return False
            res = self.rule_engine.evaluate(query, ctx or {})
            intent = str(res.get("intent") or "").lower()
            return intent in (
                "return_request",
                "support",
                "order_issue_report",
                "order_status",
            )
        except Exception:
            return False

    def validate(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        # Ensure insider-context anomalies still raise a ticket even if earlier
        # fast-path logic is bypassed by different test/middleware conditions.
        try:
            trace_id = self._ensure_trace_id(payload if isinstance(payload, dict) else {})
            if isinstance(payload, dict) and payload.get("unusual_hours") and not payload.get("_insider_ticketed"):
                try:
                    t = TicketingAgent()
                    title = "Security alert: insider context anomaly"
                    desc = json.dumps({"payload": payload, "reason": "unusual_hours"}, ensure_ascii=False)
                    ticket = self._create_incident_ticket(
                        title=title,
                        description=desc,
                        severity="high",
                        tenant_id=payload.get("tenant_id") or None,
                        trace_id=trace_id,
                    )
                    try:
                        payload["_insider_ticketed"] = True
                    except Exception:
                        pass
                    try:
                        log_decision(
                            agent_name="orchestrator.incident",
                            input_data={"payload": payload, "reason": "unusual_hours"},
                            retrieved_context={},
                            proposed_action={"ticket_id": getattr(ticket, "id", None)},
                            agent_reasoning="auto incident route (actor context validate)",
                            policy_version=self.flags.get("POLICY_VERSION", "v1"),
                            approval_required=False,
                            execution_status="executed",
                            tenant_id=payload.get("tenant_id") or None,
                            actor_id=payload.get("actor_id") or None,
                            actor_role=payload.get("actor_role") or None,
                            event_type="IncidentRoute",
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        if "cart_total_cents" not in payload:
            return False, "Missing cart_total_cents"
        return True, "OK"

    def retrieve(self, uid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Forced retrieval for volatile facts (price/stock)
        context = self.memory.get_context(uid)
        # Backward compatibility for memory test doubles that only implement get_context().
        get_structured = getattr(self.memory, "get_structured_state", None)
        get_bank = getattr(self.memory, "get_product_memory_bank", None)
        structured_state = get_structured(uid) if callable(get_structured) else {}
        product_memory_bank = get_bank(uid) if callable(get_bank) else {}
        chaos = self.flags.get("CHAOS", {"enabled": False, "latency_ms": 0, "probability": 0})
        if chaos.get("enabled") and random.random() < float(chaos.get("probability", 0)):
            lat_ms = float(chaos.get("latency_ms", 0))
            time.sleep(lat_ms / 1000.0)
            chaos_injected_total.labels(latency_ms=str(int(lat_ms))).inc()
        total = payload.get("cart_total_cents", 0)
        sku = payload.get("sku")
        stock_ok = True
        product = None
        # Prefer draft_cart_id from KV state if present
        kv = context.get("kv") or {}
        draft_id = None
        try:
            draft_id = kv.get("draft_cart_id") if isinstance(kv, dict) else None
        except Exception:
            draft_id = None
        draft_order = None
        if draft_id:
            # Treat draft order as the canonical cart state
            draft_order = self.catalog.get_draft_order(draft_id)
            if draft_order:
                computed = self.catalog.compute_cart_total(draft_id)
                if computed is not None:
                    total = computed
        if sku:
            product = self.catalog.get_product_by_sku(sku)
            stock = self.catalog.get_stock_by_product_id(product.id) if product else None
            stock_ok = (stock or 0) > 0
            # if product present, prefer its price for calculations
            total = product.price_cents if product else total
        live = {
            "stock_ok": stock_ok,
            "cart_total_cents": total,
            "sku": sku,
            "product": (product.sku if product else None),
            "draft_cart_id": draft_id,
            "draft_order": (draft_order.line_items if draft_order else None),
        }
        # store full retrieved context (memory + live + dependency health) for observability
        retrieved_context = {
            "memory": context,
            "structured_state": structured_state,
            "product_memory_bank": product_memory_bank,
            "live": live,
            "dependency_health": dependency_health_snapshot(),
        }
        # --- Layer 2/3/4 RECALL ---
        episodic_profile = {}
        observation_summary = {}
        agent_trust_scores = {}
        try:
            if EpisodicMemory is not None:
                ep = EpisodicMemory(self.memory, uid)
                episodic_profile = ep.build_behavioral_model() or {}
                retrieved_context["episodic_profile"] = episodic_profile
        except Exception:
            pass
        try:
            obs_raw = self.memory.get_observation_summary(uid)
            if obs_raw:
                observation_summary = obs_raw
                retrieved_context["observation_summary"] = observation_summary
        except Exception:
            pass
        try:
            if callable(get_agent_trust_score):
                for agent_name in ("fraud_scorer", "recommendation", "tier_router"):
                    ts = get_agent_trust_score(agent_name)
                    if ts is not None:
                        agent_trust_scores[agent_name] = ts
                retrieved_context["agent_trust_scores"] = agent_trust_scores
        except Exception:
            pass
        self.memory.set_recent_retrieval(uid, live)
        return {
            "memory": context,
            "structured_state": structured_state,
            "product_memory_bank": product_memory_bank,
            "live": live,
            "retrieved_context": retrieved_context,
            "dependency_health": retrieved_context["dependency_health"],
            "episodic_profile": episodic_profile,
            "observation_summary": observation_summary,
            "agent_trust_scores": agent_trust_scores,
        }

    def reason(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # MVP: naive pricing policy based on cart total
        total = ctx["live"]["cart_total_cents"]
        if total < 10000:
            discount = 5
        elif total < 25000:
            discount = 10
        else:
            discount = 15
        return {
            "proposal_id": str(uuid.uuid4()),
            "cart_total_cents": total,
            "discount_percent": discount,
            "reason": "Tiered discount based on cart total",
        }

    def rule_based_reason(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # Conservative fallback: minimize risk during degradation.
        total = ctx["live"]["cart_total_cents"]
        if total < 10000:
            discount = 10
        elif total < 25000:
            discount = 5
        else:
            discount = 0
        return {
            "proposal_id": str(uuid.uuid4()),
            "cart_total_cents": total,
            "discount_percent": discount,
            "reason": "Rule-based fallback (degraded mode)",
        }

    def policy(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        fw = self.firewall.check_pricing(
            cart_total_cents=proposal["cart_total_cents"],
            proposed_discount_percent=proposal["discount_percent"],
        )
        return {
            "allowed": fw.allowed,
            "approval_required": fw.approval_required,
            "reason": fw.reason,
            "escalation_role": fw.escalation_role,
            "policy_version": fw.policy_version,
        }

    def run_nlp_cv(self, uid: str, payload: Dict[str, Any], simulate_only: bool = False, use_rules: bool = False) -> OrchestratorResult:
        timings: dict[str, float] = {}
        t0 = time.time()
        trace_id = self._ensure_trace_id(payload)
        trace_id = self._ensure_trace_id(payload)
        query = (payload.get("query") or payload.get("input") or "").strip()
        # Guardrails first
        try:
            g = apply_guardrails(payload, metadata={"memory": {}, "retrieved": {}})
            if isinstance(g, dict) and g.get("sanitized_payload"):
                payload = g.get("sanitized_payload")
        except Exception:
            pass

        # Security observer on input
        try:
            sec = analyze_payload(payload)
        except Exception:
            sec = {"severity": "info", "risk_adj": 0.0}
        orchestrator_guard = self._agent_guardrail(
            trace_id=trace_id,
            agent_name="Orchestrator_Agent",
            stage="ingress",
            payload=payload,
            tenant_id=tenant_id,
        )
        if str(orchestrator_guard.get("action") or "") == "isolate":
            blocked = {
                "decision_mode": "blocked",
                "trace_id": trace_id,
                "reason": "agent_guardrail_isolation",
                "agent_guardrail": orchestrator_guard,
                "ranked_skus": [],
                "results": [],
                "needs_human_review": True,
            }
            policy = {
                "allowed": False,
                "approval_required": True,
                "reason": "agent_guardrail_isolation",
                "escalation_role": "security",
            }
            return OrchestratorResult(proposal=blocked, firewall=policy, executed=False, timings=timings)
        try:
            sec_details = {}
            try:
                sec_details = sec.get("details") if isinstance(sec, dict) else {}
            except Exception:
                sec_details = {}
            log_trace_event(
                trace_id=trace_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="input",
                target_id=None,
                payload={
                    "severity": sec.get("severity"),
                    "risk_adj": sec.get("risk_adj"),
                    "details": sec_details,
                    "signals": (sec_details.get("signals") if isinstance(sec_details, dict) else None),
                    "owasp_llm_top10": (sec_details.get("owasp_llm_top10") if isinstance(sec_details, dict) else None),
                    "owasp_agentic_top10": (sec_details.get("owasp_agentic_top10") if isinstance(sec_details, dict) else None),
                    "owasp_api_top10": (sec_details.get("owasp_api_top10") if isinstance(sec_details, dict) else None),
                    "mitre_atlas": (sec_details.get("mitre_atlas") if isinstance(sec_details, dict) else None),
                    "stride_categories": (sec_details.get("stride_categories") if isinstance(sec_details, dict) else None),
                    "dread_avg": (sec_details.get("dread_avg") if isinstance(sec_details, dict) else None),
                },
            )
        except Exception:
            pass

        t1 = time.time()
        timings["security"] = t1 - t0

        # AB test assignment and trace
        ab = self._assign_ab_variant(trace_id)
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="ab_assignment",
                source_type="orchestrator",
                source_id="ab_router",
                target_type=None,
                target_id=None,
                payload=ab,
            )
        except Exception:
            pass
        try:
            from src.app.observability.metrics import record_ab_assignment
            record_ab_assignment(ab.get("variant") or "A")
        except Exception:
            pass

        # Phase 1: Parallel Exploration intent + security + CV label extraction (if images)
        self._trace_phase(trace_id, phase="phase1", status="started", agents_planned=["NLP Explore", "CV Explore", "Security Explore"], meta={"complexity_hint": (sec.get("risk_adj") if isinstance(sec, dict) else None)})
        # Intent rules (if available) + optional XGBoost classifier
        intent_result: Dict[str, Any] = {}
        try:
            if getattr(self, "rule_engine", None) is not None and query:
                intent_result = self.rule_engine.evaluate(query, {"memory": {}, "live": {}})
        except Exception:
            intent_result = {}
        try:
            if query:
                from src.app.analytics.xgb_intent import infer_intent
                xgb = infer_intent(query)
                if isinstance(xgb, dict) and xgb.get("intent"):
                    intent_result = {**intent_result, "xgb_intent": xgb.get("intent"), "xgb_proba": xgb.get("proba")}
        except Exception:
            pass

        # NLP candidate retrieval + rerank
        service = RecommendationService()
        constraints: Dict[str, Any] = {}
        if query:
            try:
                constraints = service.parse_constraints(query)
                constraints["query"] = query
                if intent_result.get("intent"):
                    constraints["intent"] = intent_result.get("intent")
            except Exception:
                constraints = {"query": query}
        candidates: List[Dict[str, Any]] = []
        try:
            if query:
                rec_guard = self._agent_guardrail(
                    trace_id=trace_id,
                    agent_name="Recommendation_Agent",
                    stage="phase1.retrieval",
                    payload={"query": query, "constraints": constraints},
                    tenant_id=tenant_id,
                )
                if str(rec_guard.get("action") or "") == "isolate":
                    raise RuntimeError("recommendation_agent_isolated")
                candidates = service.retrieve_candidates(query, limit=10)
        except Exception:
            candidates = []

        retrieved_context = {
            "candidates": candidates,
            "constraints": constraints,
            "intent": intent_result,
            "security": sec,
        }

        scored: List[Dict[str, Any]] = []
        try:
            if candidates:
                scored = service.rerank_candidates_with_factors(candidates, constraints)
        except Exception:
            scored = []

        results: List[Dict[str, Any]] = []
        for item in scored:
            cand = item.get("candidate") or {}
            results.append({
                "sku": cand.get("sku"),
                "name": cand.get("name"),
                "price_cents": cand.get("price_cents"),
                "currency": cand.get("currency"),
                "image_url": cand.get("image_url"),
                "stock": cand.get("stock"),
                "specs": cand.get("specs") or {},
                "score": item.get("score"),
                "confidence": item.get("confidence"),
                "factors": item.get("factors"),
            })

        t2 = time.time()
        timings["recommend"] = t2 - t1

        # Phase 2: Parallel Evaluation (recommendation, fraud score, inventory check)
        self._trace_phase(trace_id, phase="phase2", status="started", agents_planned=["Recommend", "Fraud Score", "Inventory Check"], meta={"results_planned": min(len(results), 10)})
        # Inventory checks + fraud scoring concurrently (latency-aware)
        tool_budget_remaining: int | None = None
        cv_analysis: Dict[str, Any] | None = None
        inv_evals: List[Dict[str, Any]] = []
        fraud_summary: Dict[str, Any] | None = None
        try:
            from src.app.services.inventory_agent import InventoryAgent
            from src.app.services.fraud_scorer import FraudScorer

            async def _inv_task(r: Dict[str, Any]) -> Dict[str, Any]:
                inv = InventoryAgent()
                stock = int(r.get("stock") or 0)
                sku_val = r.get("sku") or ""
                t_agent_start = time.time()
                inv_guard = self._agent_guardrail(
                    trace_id=trace_id,
                    agent_name="Inventory_Agent",
                    stage="phase2.inventory",
                    payload={"sku": sku_val, "stock": stock, "query": query},
                    tenant_id=tenant_id,
                )
                if str(inv_guard.get("action") or "") == "isolate":
                    self._trace_agent_invocation(
                        trace_id,
                        phase="phase2",
                        agent_name="Inventory_Agent",
                        start_ms=t_agent_start,
                        end_ms=time.time(),
                        tags=["isolated"],
                        tool_budget_remaining=tool_budget_remaining,
                    )
                    return {"sku": sku_val, "isolated": True, "can_fulfill": False, "escalate": True, "guardrail": inv_guard}
                # Budget enforcement: skip heavy inventory check when budget exhausted
                if tool_budget_remaining is not None and int(tool_budget_remaining) <= 0:
                    try:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="tool_budget_denied",
                            source_type="orchestrator",
                            source_id="Inventory_Agent",
                            target_type="agent",
                            target_id="Inventory_Agent",
                            payload={"remaining": int(tool_budget_remaining)},
                        )
                    except Exception:
                        pass
                    return {"sku": sku_val, "skipped_due_budget": True}
                res = await asyncio.to_thread(inv.evaluate_stock_rule, sku_val, {"stock": stock})
                res["available_qty"] = stock
                item = {"sku": sku_val, **res}
                self._trace_agent_invocation(trace_id, phase="phase2", agent_name="Inventory_Agent", start_ms=t_agent_start, end_ms=time.time(), tags=["stock_rule"], tool_budget_remaining=tool_budget_remaining)
                return item

            async def _fraud_task() -> Dict[str, Any]:
                # reuse base_signals from earlier CV analysis
                base_signals = {}
                if cv_analysis:
                    if cv_analysis.get("damage_type") == "unknown":
                        base_signals["damage_not_visible"] = True
                    if cv_analysis.get("needs_human_review"):
                        base_signals["image_hash_match_fraud_db"] = False
                f = FraudScorer()
                t_agent_start = time.time()
                fraud_guard = self._agent_guardrail(
                    trace_id=trace_id,
                    agent_name="Fraud_Scoring_Agent",
                    stage="phase2.fraud",
                    payload={"query": query, "base_signals": base_signals},
                    tenant_id=tenant_id,
                )
                if str(fraud_guard.get("action") or "") == "isolate":
                    self._trace_agent_invocation(
                        trace_id,
                        phase="phase2",
                        agent_name="Fraud_Scoring_Agent",
                        start_ms=t_agent_start,
                        end_ms=time.time(),
                        tags=["isolated"],
                        tool_budget_remaining=tool_budget_remaining,
                    )
                    return {"score": 1.0, "level": "isolated", "signals": {"guardrail_isolated": True}, "guardrail": fraud_guard}
                # Budget enforcement: skip fraud scoring when budget exhausted
                if tool_budget_remaining is not None and int(tool_budget_remaining) <= 0:
                    try:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="tool_budget_denied",
                            source_type="orchestrator",
                            source_id="Fraud_Scoring_Agent",
                            target_type="agent",
                            target_id="Fraud_Scoring_Agent",
                            payload={"remaining": int(tool_budget_remaining)},
                        )
                    except Exception:
                        pass
                    return {"score": 0.0, "level": "skipped", "signals": {}, "skipped_due_budget": True}
                score, level, signals = await asyncio.to_thread(
                    f.score_with_enrichment,
                    base_signals,
                    None,
                    (cv_analysis.get("serial_number") if cv_analysis else None),
                    None,
                    (payload.get("session") if isinstance(payload, dict) else None),
                    (payload.get("case_id") if isinstance(payload, dict) else None),
                )
                out = {"score": score, "level": level, "signals": signals}
                self._trace_agent_invocation(trace_id, phase="phase2", agent_name="Fraud_Scoring_Agent", start_ms=t_agent_start, end_ms=time.time(), tags=["isolation_forest"], tool_budget_remaining=tool_budget_remaining)
                return out

            async def _run_phase2():
                tasks = []
                for r in results[:8]:
                    tasks.append(_inv_task(r))
                tasks.append(_fraud_task())
                done = await asyncio.gather(*tasks, return_exceptions=True)
                return done

            done = asyncio.run(_run_phase2())
            for item in done:
                try:
                    if isinstance(item, dict) and "score" in item and "level" in item:
                        fraud_summary = item
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="fraud_score",
                            source_type="agent",
                            source_id="Fraud_Scoring_Agent",
                            target_type="system",
                            target_id=None,
                            payload=item,
                        )
                    elif isinstance(item, dict):
                        inv_evals.append(item)
                except Exception:
                    pass

            if inv_evals:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="inventory_check",
                    source_type="agent",
                    source_id="Inventory_Agent",
                    target_type="system",
                    target_id=None,
                    payload={"evaluations": inv_evals[:8]},
                )
        except Exception:
            pass

        # CV analysis (if images present)
        try:
            images = self._decode_images(payload.get("images") or payload.get("image_b64s") or payload.get("image_data"))
            if images:
                cv_guard = self._agent_guardrail(
                    trace_id=trace_id,
                    agent_name="CV_Label_Agent",
                    stage="phase2.cv",
                    payload={"query": query, "has_images": True, "ocr_text": payload.get("ocr_text")},
                    tenant_id=tenant_id,
                )
                if str(cv_guard.get("action") or "") == "isolate":
                    cv_analysis = {"needs_human_review": True, "verdict": "isolated", "guardrail": cv_guard}
                    raise RuntimeError("cv_agent_isolated")
                from src.app.services.cv_provider import ManagedCVProvider
                from src.app.services.cv_triage_basic import BasicCVTriage
                import asyncio as _asyncio
                t_agent_start = time.time()
                labels, text = _asyncio.run(ManagedCVProvider().get_labels_and_text(images[0]))
                cv_analysis = _asyncio.run(BasicCVTriage().analyze(labels, text))
                log_trace_event(
                    trace_id=trace_id,
                    event_type="cv_analysis",
                    source_type="agent",
                    source_id="CV_Label_Agent",
                    target_type="system",
                    target_id=None,
                    payload=cv_analysis or {},
                )
                self._trace_agent_invocation(trace_id, phase="phase1", agent_name="CV_Label_Agent", start_ms=t_agent_start, end_ms=time.time(), tags=["labels", "ocr"], tool_budget_remaining=tool_budget_remaining)
        except Exception:
            cv_analysis = cv_analysis or None

        # Fraud scoring (best-effort, relevant for complaints/CV)
        fraud_summary: Dict[str, Any] | None = None
        try:
            from src.app.services.fraud_scorer import FraudScorer
            base_signals = {}
            if cv_analysis:
                if cv_analysis.get("damage_type") == "unknown":
                    base_signals["damage_not_visible"] = True
                if cv_analysis.get("needs_human_review"):
                    base_signals["image_hash_match_fraud_db"] = False
            fraud = FraudScorer()
            t_agent_start = time.time()
            fraud_score, fraud_level, fraud_signals = fraud.score_with_enrichment(
                base_signals=base_signals,
                expected_serial=None,
                observed_serial=cv_analysis.get("serial_number") if cv_analysis else None,
                image_phash=None,
                session_data=payload.get("session") if isinstance(payload, dict) else None,
                case_id=payload.get("case_id") if isinstance(payload, dict) else None,
            )
            fraud_summary = {"score": fraud_score, "level": fraud_level, "signals": fraud_signals}
            log_trace_event(
                trace_id=trace_id,
                event_type="fraud_score",
                source_type="agent",
                source_id="Fraud_Scoring_Agent",
                target_type="system",
                target_id=None,
                payload=fraud_summary,
            )
            self._trace_agent_invocation(trace_id, phase="phase2", agent_name="Fraud_Scoring_Agent", start_ms=t_agent_start, end_ms=time.time(), tags=["isolation_forest"], tool_budget_remaining=tool_budget_remaining)
        except Exception:
            fraud_summary = fraud_summary or None

        # Tier decision and parallel checks (K2-style speculative execution)
        parallel_outputs: Dict[str, Any] | None = None
        tier_decision = None
        tool_budget_remaining = None
        try:
            if getattr(self, "tier_router", None) is not None:
                router_ctx = {
                    "amount": (payload.get("cart_total_cents", 0) or 0) / 100.0,
                    "multi_turn": bool(payload.get("multi_turn", False)),
                    "tenant_id": payload.get("tenant_id") or payload.get("tenant") or None,
                }
                tier_decision = self.tier_router.route(query=query, context=router_ctx, intent_result=intent_result, security_analysis=sec)
                try:
                    tool_budget_remaining = int(getattr(tier_decision, "tool_budget", 0) or 0)
                except Exception:
                    tool_budget_remaining = None
                # Parallel cache hit/miss metric and optional reuse
                try:
                    if tier_decision and getattr(tier_decision, "reason", "") == "cache_hit":
                        cached = None
                        try:
                            cache = getattr(self.tier_router, "cache", None)
                            if cache and getattr(tier_decision, "cache_key", None):
                                raw = cache.get(tier_decision.cache_key)
                                if raw:
                                    if isinstance(raw, bytes):
                                        raw = raw.decode("utf-8", errors="ignore")
                                    import json as _json
                                    cached = _json.loads(raw)
                        except Exception:
                            cached = None
                        try:
                            record_parallel_cache_event("hit")
                            log_trace_event(
                                trace_id=trace_id,
                                event_type="parallel_cache_hit",
                                source_type="orchestrator",
                                source_id="tier_router",
                                target_type=None,
                                target_id=None,
                                payload={"cache_key": getattr(tier_decision, "cache_key", None), "hit": bool(cached is not None)},
                            )
                        except Exception:
                            pass
                        if isinstance(cached, dict):
                            parallel_outputs = cached
                            try:
                                if parallel_outputs.get("cv"):
                                    cv_analysis = parallel_outputs.get("cv")
                                if parallel_outputs.get("inventory"):
                                    inv_evals = parallel_outputs.get("inventory") or inv_evals
                                if parallel_outputs.get("fraud"):
                                    fraud_summary = parallel_outputs.get("fraud") or fraud_summary
                            except Exception:
                                pass
                        else:
                            try:
                                record_parallel_cache_event("miss")
                                log_trace_event(
                                    trace_id=trace_id,
                                    event_type="parallel_cache_miss",
                                    source_type="orchestrator",
                                    source_id="tier_router",
                                    target_type=None,
                                    target_id=None,
                                    payload={"cache_key": getattr(tier_decision, "cache_key", None)},
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
            # Decide if parallel block should run
            use_parallel = False
            try:
                use_parallel = bool(tier_decision and int(getattr(tier_decision, "tier", 1)) >= 2)
            except Exception:
                use_parallel = False
            if not use_parallel:
                use_parallel = bool(payload.get("images") or payload.get("image_urls") or payload.get("complaint_intent"))
            # AB override: force parallel on variant B when configured
            try:
                if ab.get("overrides", {}).get("force_parallel"):
                    use_parallel = True
            except Exception:
                pass
            if use_parallel and parallel_outputs is None:
                try:
                    if bool(self.flags.get("ASYNC_AGENT_DAG_ENABLED", False)):
                        from src.app.services.agent_dag_runtime import run_exploration_dag
                        tenant_id = payload.get("tenant_id") if isinstance(payload, dict) else None
                        try:
                            dag = asyncio.run(
                                run_exploration_dag(
                                    payload=payload,
                                    run_security=lambda: sec,
                                    run_cv=lambda: cv_analysis or {},
                                    run_fraud=lambda: fraud_summary or {},
                                    run_inventory=lambda: inv_evals,
                                    tenant_id=str(tenant_id) if tenant_id else None,
                                    budget=controller.state.tool_budget_remaining if hasattr(controller, "state") else None,
                                )
                            )
                        except Exception:
                            dag = None
                        parallel_outputs = {
                            "security": (dag.get("phase1") or {}).get("security"),
                            "cv": (dag.get("phase1") or {}).get("cv"),
                            "fraud": (dag.get("phase2") or {}).get("fraud"),
                            "inventory": (dag.get("phase2") or {}).get("inventory"),
                            "dag_meta": dag.get("meta"),
                        }
                except Exception:
                    parallel_outputs = None
                if parallel_outputs is None:
                    from src.app.services.parallel_agent_executor import run_parallel_checks
                    parallel_outputs = run_parallel_checks(payload, ranked_results=results, base_signals={})
                # Tool budget: parallel block consumes 1 unit at most for orchestration envelope
                try:
                    if tool_budget_remaining is not None:
                        tool_budget_remaining = max(0, int(tool_budget_remaining) - 1)
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="tool_budget",
                            source_type="orchestrator",
                            source_id="parallel_block",
                            target_type=None,
                            target_id=None,
                            payload={"remaining": tool_budget_remaining},
                        )
                except Exception:
                    pass
                # Cache speculative outputs for T0/T1 hits
                try:
                    if tier_decision and getattr(tier_decision, "cache_key", None):
                        self.tier_router.cache_response(tier_decision.cache_key, parallel_outputs, ttl=int(self.flags.get("PARALLEL_CACHE_TTL", 600) or 600))
                        try:
                            record_parallel_cache_event("store")
                            log_trace_event(
                                trace_id=trace_id,
                                event_type="parallel_cache_store",
                                source_type="orchestrator",
                                source_id="tier_router",
                                target_type=None,
                                target_id=None,
                                payload={"cache_key": getattr(tier_decision, "cache_key", None)},
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
                # Merge parallel outputs into local summaries if present
                try:
                    if isinstance(parallel_outputs, dict):
                        if parallel_outputs.get("cv"):
                            cv_analysis = parallel_outputs.get("cv")
                        if parallel_outputs.get("inventory"):
                            inv_evals = parallel_outputs.get("inventory") or inv_evals
                        if parallel_outputs.get("fraud"):
                            fraud_summary = parallel_outputs.get("fraud") or fraud_summary
                except Exception:
                    pass
        except Exception:
            parallel_outputs = None

        # Phase completion markers for dashboard
        self._trace_phase(trace_id, phase="phase2", status="completed", agents_planned=None, meta={"eval_count": len(inv_evals) + (1 if fraud_summary else 0)})

        # Persist minimal agent state for resume (best-effort via Redis)
        self._save_agent_state(
            trace_id,
            {
                "phase": "phase2",
                "results_len": len(results),
                "inv_evals_len": len(inv_evals),
                "fraud": bool(fraud_summary),
                "cv": bool(cv_analysis),
                "ts": int(time.time()),
            },
        )

        # Build proposal + policy gate
        proposal = {
            "proposal_id": trace_id,
            "decision_mode": "nlp_cv",
            "query": query,
            "ranked_skus": [r.get("sku") for r in results if r.get("sku")],
            "results": results,
            "intent": intent_result,
            "constraints": constraints,
            "security": sec,
            "cv": cv_analysis,
            "fraud": fraud_summary,
            "inventory": inv_evals[:8],
            "trace_id": trace_id,
        }
        try:
            proposal["ab_variant"] = ab.get("variant")
        except Exception:
            pass
        # Attach preserved thinking metadata
        try:
            if tier_decision is not None:
                proposal["tiers_chosen"] = {"tier": tier_decision.tier, "tool_budget": tier_decision.tool_budget}
            if isinstance(cv_analysis, dict) and cv_analysis.get("evidence_tags"):
                proposal["evidence_tags"] = list(cv_analysis.get("evidence_tags") or [])
        except Exception:
            pass
        policy: Dict[str, Any] = {"policy_version": self.flags.get("POLICY_VERSION", "v1")}
        try:
            if getattr(self, "policy_gate", None) is not None:
                pg = self.policy_gate.evaluate({"proposal": proposal}, context=retrieved_context)
                policy["policy_gate"] = pg
                log_trace_event(
                    trace_id=trace_id,
                    event_type="policy_gate",
                    source_type="policy_gate",
                    source_id="policy_gate",
                    target_type=None,
                    target_id=None,
                    payload=pg,
                )
                log_trace_event(
                    trace_id=trace_id,
                    event_type="policy_verdict",
                    source_type="policy_gate",
                    source_id="policy_gate",
                    target_type=None,
                    target_id=None,
                    payload=pg,
                )
        except Exception:
            pass

        # Isolation Forest fraud anomaly (advanced) — augment fraud_summary
        try:
            from src.app.analytics.isolation_forest import score_fraud
            fraud_feats = {}
            try:
                sess = payload.get("session") if isinstance(payload, dict) else {}
                fraud_feats["velocity"] = float(sess.get("purchases_last_hour", 0) or 0)
                fraud_feats["geo_mismatch"] = 1.0 if sess.get("ip_country") and sess.get("shipping_country") and sess.get("ip_country") != sess.get("shipping_country") else 0.0
                fraud_feats["device_change"] = 1.0 if sess.get("device_changed_mid_session") else 0.0
                # Device fingerprint drift and serial mismatch frequency (if provided)
                fraud_feats["device_fp_drift"] = float(sess.get("device_fp_drift", 0.0) or 0.0)
                fraud_feats["serial_mismatch_freq"] = float(sess.get("serial_mismatch_count", 0) or 0.0)
            except Exception:
                pass
            try:
                if isinstance(cv_analysis, dict):
                    fraud_feats["cv_blur"] = float(cv_analysis.get("blur_score") or 0.0)
                    fraud_feats["phash_dup"] = 1.0 if cv_analysis.get("phash_match") else 0.0
                    if cv_analysis.get("serial_match") is False:
                        proposal.setdefault("evidence_tags", []).append("serial_mismatch")
            except Exception:
                pass
            try:
                verdict = policy.get("policy_gate", {})
                fraud_feats["approval_required"] = 1.0 if isinstance(verdict, dict) and (verdict.get("verdict") == "escalate") else 0.0
            except Exception:
                pass
            isf = score_fraud(fraud_feats)
            if isinstance(isf, dict):
                proposal.setdefault("fraud_isolation_forest", isf)
                try:
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="fraud_isolation_forest",
                        source_type="agent",
                        source_id="Fraud_IsolationForest",
                        target_type=None,
                        target_id=None,
                        payload=isf,
                    )
                except Exception:
                    pass
                # Tagging to drive PB-FRAUD playbooks
                try:
                    if (isf.get("label") or "") in ("medium", "high"):
                        proposal.setdefault("evidence_tags", []).append("fraud_isf_" + str(isf.get("label")))
                    if fraud_feats.get("device_fp_drift", 0.0) > 0.5:
                        proposal.setdefault("evidence_tags", []).append("device_fp_drift")
                    if fraud_feats.get("serial_mismatch_freq", 0.0) >= 1.0:
                        proposal.setdefault("evidence_tags", []).append("serial_mismatch_freq")
                except Exception:
                    pass
        except Exception:
            pass

        # Log decision (bitemporal) with shared trace_id
        try:
            self._trace_phase(
                trace_id,
                phase="phase3",
                status="started",
                agents_planned=["InterleavingController"],
                meta={"discipline": "always_on"},
            )
            synthesis = deterministic_conflict_resolution(
                proposal=proposal,
                policy=policy,
                security=(sec if isinstance(sec, dict) else {}),
                fraud=(fraud_summary if isinstance(fraud_summary, dict) else {}),
            )
            proposal["synthesis_reasoning"] = synthesis
            policy = apply_synthesis_to_policy(policy, synthesis)
            self._emit_synthesis_reasoning(trace_id=trace_id, synthesis=synthesis, proposal=proposal)
            self._trace_phase(
                trace_id,
                phase="phase3",
                status="completed",
                agents_planned=None,
                meta={"synthesis": "deterministic_conflict_v1"},
            )
        except Exception:
            pass

        # Default completion path for NLP/CV orchestration when no early branch returned.
        try:
            timings["total"] = max(0.0, time.time() - t0)
        except Exception:
            pass
        executed = (not simulate_only) and (not bool(policy.get("approval_required", False)))
        return OrchestratorResult(
            proposal=proposal,
            firewall=policy,
            executed=executed,
            timings=timings,
        )

    def _save_agent_state(self, trace_id: str | None, state: Dict[str, Any]) -> None:
        if not trace_id or not isinstance(state, dict):
            return
        try:
            redis_client = getattr(self.memory, "redis", None)
            if redis_client is None:
                return
            redis_client.setex(
                f"agent_state:{trace_id}",
                int(self.flags.get("AGENT_STATE_TTL", 900) or 900),
                json.dumps(state, ensure_ascii=False),
            )
        except Exception:
            pass

    def _load_agent_state(self, trace_id: str | None) -> Dict[str, Any] | None:
        if not trace_id:
            return None
        try:
            redis_client = getattr(self.memory, "redis", None)
            if redis_client is None:
                return None
            raw = redis_client.get(f"agent_state:{trace_id}")
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    # ------------------ New: model tiering & safe wrappers ------------------
    def choose_model_tier(self, payload: Dict[str, Any], retrieved: Dict[str, Any], security_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Decide which model tier to use based on simple heuristics.

        Returns a dict: {"text_tier": "T1"|"T2"|"T3", "vision_tier": "V0"|"V1"|"V2", "model": <str>}
        """
        # Inputs
        image_present = bool(payload.get("images") or payload.get("image_urls"))
        intent_conf = float(payload.get("intent_confidence", 1.0))
        multi_turn = bool(payload.get("multi_turn", False))
        amount = float(payload.get("amount", 0.0))
        risk_adj = float(security_analysis.get("risk_adj", 0.0)) if isinstance(security_analysis, dict) else 0.0

        # Default tiers
        text_tier = "T1"
        vision_tier = "V0" if image_present else "N/A"
        model = None

        # Text ladder
        if intent_conf < 0.85 or multi_turn:
            text_tier = "T2"
        if risk_adj >= 50 or amount >= 250:
            text_tier = "T3"

        # Vision ladder
        if image_present:
            vision_tier = "V1"
            # if security risk high, escalate to stronger vision
            if risk_adj >= 40:
                vision_tier = "V2"

        # Try learned router when available for improved tiering
        try:
            learned_enabled = str(self.flags.get("LEARNED_TIER_ROUTER_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
            if learned_enabled and getattr(self, "learned_router", None) is not None:
                query = (payload.get("query") or payload.get("input") or "").strip()
                context = {
                    "amount": float(payload.get("cart_total_cents", 0) or 0) / 100.0,
                    "multi_turn": bool(payload.get("multi_turn", False)),
                    "image_present": bool(payload.get("images") or payload.get("image_urls")),
                }
                intent_result = {"confidence": float(payload.get("intent_confidence", 1.0) or 1.0)}
                decision = self.learned_router.route(query=query, context=context, intent_result=intent_result, security_analysis=security_analysis)
                text_tier = f"T{int(decision.tier)}"
                vision_tier = "V1" if context["image_present"] else "N/A"
                model = decision.model
        except Exception:
            pass

        # Map to model names (best-effort; real names configured via flags/settings)
        if text_tier == "T1":
            model = self.flags.get("MODEL_T1", "qwen2-small")
        elif text_tier == "T2":
            model = self.flags.get("MODEL_T2", "qwen2-medium")
        else:
            model = self.flags.get("MODEL_T3", "qwen2-large")

        return {"text_tier": text_tier, "vision_tier": vision_tier, "model": model, "intent_confidence": intent_conf, "risk_adj": risk_adj}

    def apply_token_budget(self, uid: str, spec: Dict[str, Any]) -> bool:
        """Placeholder token budget enforcement. Returns True if allowed."""
        # For now delegate to existing LLMOrchestrator budget checks when available.
        try:
            if self.llm is None:
                return True
            # estimate small token usage for tier selection
            # use a lightweight estimate to avoid expensive calls here
            return True
        except Exception:
            return True

    def call_text_model(self, uid: str, spec: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """Call a text model safely. Returns {result, confidence, usage}.

        This is conservative: if LLM client unavailable or budget denied, return a rule-based stub.
        """
        if not self.apply_token_budget(uid, spec):
            return {"result": None, "confidence": 0.0, "usage": {}}
        try:
            if self.llm is not None:
                # Use the LLMOrchestrator client via rerank as a compact demo call when appropriate
                # Here we treat `prompt` as a constraints-like JSON for the rerank stub.
                # This keeps calls local to the existing LLM client implementation.
                try:
                    import json as _json
                    obj = _json.loads(prompt) if isinstance(prompt, str) and prompt.strip().startswith("{") else {"prompt": prompt}
                except Exception:
                    obj = {"prompt": prompt}
                # If a candidates list is present, call rerank_with_budget; else fall back to client.rerank
                candidates = obj.get("candidates") if isinstance(obj, dict) else None
                if candidates and hasattr(self.llm, "rerank_with_budget"):
                    ranked = self.llm.rerank_with_budget(uid, candidates, obj.get("constraints") or {})
                    return {"result": ranked, "confidence": 0.8, "usage": {"method": "rerank"}}
                # Fall back to direct client call
                client = getattr(self.llm, "client", None)
                if client is not None:
                    out = client._call_ollama_cli(client.model, prompt)
                    if out:
                        return {"result": out, "confidence": 0.6, "usage": {"method": "ollama_cli"}}
        except Exception:
            pass
        # Deterministic fallback (no model)
        return {"result": None, "confidence": 0.0, "usage": {"method": "fallback"}}

    def call_vision_model(self, uid: str, spec: Dict[str, Any], image_blob: bytes) -> Dict[str, Any]:
        """Placeholder vision model call. Returns {labels, confidence}.

        Currently VLM calls are not implemented here; callers should use existing CV providers.
        """
        # Minimal stub: return empty analysis with low confidence
        return {"labels": [], "confidence": 0.0, "usage": {}}

    def _run_interleaving(
        self,
        uid: str,
        payload: Dict[str, Any],
        ctx: Dict[str, Any],
        tier_decision: Any,
        sec: Dict[str, Any],
        trace_id: str | None,
    ) -> Dict[str, Any] | None:
        if not tier_decision or int(getattr(tier_decision, "tier", 0) or 0) < 2:
            return None

        query = (payload.get("query") or payload.get("input") or "").strip()
        tools_plan: List[str] = []
        tools_plan.append("retrieve_context")
        if query:
            tools_plan.append("get_recommendations")
        tools_plan.append("check_policy")

        controller = InterleavingController(
            agent_type="orchestrator",
            max_iterations=int(self.flags.get("INTERLEAVING_MAX_ITERS", 3) or 3),
            tool_budget=int(getattr(tier_decision, "tool_budget", 4) or 4),
            confidence_threshold=float(self.flags.get("INTERLEAVING_CONF_THRESHOLD", 0.9) or 0.9),
            timeout_ms=int(self.flags.get("INTERLEAVING_TIMEOUT_MS", 5000) or 5000),
        )

        def think_fn(state):
            # Enable LLM think only when risk is low and budget allows
            llm_enabled_flag = bool(self.flags.get("INTERLEAVING_LLM_THINK", False))
            risk_adj = float(sec.get("risk_adj", 0.0) if isinstance(sec, dict) else 0.0)
            budget_ok = True
            try:
                budget_ok = controller.state.tool_budget_remaining is None or int(controller.state.tool_budget_remaining) > 0
            except Exception:
                budget_ok = True
            llm_enabled = llm_enabled_flag and (risk_adj < float(self.flags.get("INTERLEAVING_LLM_RISK_MAX", 40.0) or 40.0)) and budget_ok and getattr(self, "llm", None) is not None
            if llm_enabled and getattr(self, "llm", None) is not None:
                try:
                    tool_specs = [
                        {
                            "name": "retrieve_context",
                            "description": "Fetch live pricing/stock and memory context.",
                            "args_schema": {"force": "bool (optional)"},
                        },
                        {
                            "name": "get_recommendations",
                            "description": "Retrieve candidate products for the query.",
                            "args_schema": {"query": "string (optional, defaults to user query)", "limit": "int (optional)"},
                        },
                        {
                            "name": "check_policy",
                            "description": "Evaluate proposal against policy rules.",
                            "args_schema": {"use_rules": "bool (optional)"},
                        },
                    ]
                    allowed = [t for t in tool_specs if t["name"] in controller.allowed_tools]
                    recent_calls = [
                        {
                            "tool": tc.tool_name,
                            "success": tc.success,
                            "latency_ms": tc.latency_ms,
                        }
                        for tc in state.tool_calls[-3:]
                    ]
                    prompt_obj = {
                        "instruction": "Choose the next tool to call or stop. Return strict JSON.",
                        "allowed_tools": allowed,
                        "state": {
                            "iteration": state.iteration,
                            "tool_budget_remaining": state.tool_budget_remaining,
                            "confidence": state.confidence,
                            "observations": state.observations[-5:],
                            "recent_calls": recent_calls,
                        },
                        "user_query": query,
                    }
                    system_msg = (
                        "You are a tool planner. Only select from allowed_tools. "
                        "Return JSON: {\"next_tool\": <name or null>, \"arguments\": {}, "
                        "\"stop\": false, \"confidence\": 0-1, \"reason\": \"...\"}."
                    )
                    decision = self.llm.interleaving_decide_tool(uid, prompt_obj, system=system_msg)
                    if isinstance(decision, dict):
                        nxt = decision.get("next_tool") or decision.get("tool") or decision.get("tool_name")
                        args = decision.get("arguments") or decision.get("args") or {}
                        if nxt in controller.allowed_tools:
                            return {
                                "tool_name": nxt,
                                "arguments": args if isinstance(args, dict) else {},
                                "stop": bool(decision.get("stop")) if "stop" in decision else False,
                                "reason": decision.get("reason"),
                                "confidence": decision.get("confidence"),
                            }
                        if decision.get("stop") is True:
                            return {"stop": True}
                except Exception:
                    pass
            # Deterministic fallback plan
            called = {tc.tool_name for tc in state.tool_calls}
            for nxt in list(tools_plan):
                if nxt in called:
                    continue
                if controller.can_call_tool(nxt):
                    return {"tool_name": nxt, "arguments": {}}
            return {"stop": True}

        def tool_fn(tool_name: str, _args: Dict) -> Any:
            if tool_name == "retrieve_context":
                updated = self.retrieve(uid, payload)
                try:
                    if isinstance(updated, dict) and isinstance(ctx, dict):
                        ctx.update(updated)
                except Exception:
                    pass
                return updated
            if tool_name == "get_recommendations":
                service = RecommendationService()
                q = _args.get("query") if isinstance(_args, dict) else None
                q = q or query
                limit = _args.get("limit") if isinstance(_args, dict) else None
                try:
                    limit = int(limit) if limit is not None else 6
                except Exception:
                    limit = 6
                candidates = service.retrieve_candidates(q, limit=limit) if q else []
                return {"query": query, "candidates": candidates}
            if tool_name == "check_policy":
                try:
                    use_rules = bool(_args.get("use_rules")) if isinstance(_args, dict) else False
                    tmp = self.rule_based_reason(ctx) if use_rules else self.reason(ctx)
                except Exception:
                    tmp = self.rule_based_reason(ctx)
                return {"proposal": tmp, "policy": self.policy(tmp)}
            return {"status": "unknown_tool"}

        def observe_fn(result: Any, state) -> float:
            if isinstance(result, dict) and "policy" in result:
                allowed = bool(result["policy"].get("allowed"))
                approval = bool(result["policy"].get("approval_required"))
                if allowed and not approval:
                    return 0.95
                return 0.65 if allowed else 0.5
            if isinstance(result, dict) and result.get("candidates"):
                return 0.75
            return 0.55

        def calibrate_fn(raw: float, _state) -> float:
            return calibrate_confidence(raw, agent_type="orchestrator")

        def tool_policy_fn(tool_name: str, args: Dict[str, Any], _state) -> Dict[str, Any]:
            try:
                denylist = {
                    str(x).strip()
                    for x in str(self.flags.get("INTERLEAVING_TOOL_DENYLIST", "") or "").split(",")
                    if str(x).strip()
                }
            except Exception:
                denylist = set()
            if tool_name in denylist:
                return {"allow": False, "reason": "tool_denylisted", "action": "security_review", "rule_hits": {"denylist": 1.0}}
            sec_local = {}
            try:
                sec_local = analyze_payload(
                    {
                        "tool_name": tool_name,
                        "tool_args": args or {},
                        "user_query": query,
                    }
                ) or {}
            except Exception:
                sec_local = {}
            sev = str(sec_local.get("severity") or "").lower()
            details = sec_local.get("details") if isinstance(sec_local.get("details"), dict) else {}
            signals = details.get("signals") if isinstance(details.get("signals"), dict) else {}
            if sev in ("high", "critical") or bool(
                signals.get("prompt_injection")
                or signals.get("jailbreak")
                or signals.get("agentic_tool_abuse")
                or signals.get("unexpected_code_exec")
                or signals.get("data_exfiltration")
            ):
                return {
                    "allow": False,
                    "reason": "security_observer_high_risk",
                    "action": "security_review",
                    "rule_hits": {"observer_high_risk": 1.0},
                }
            gate = evaluate_policy_gate(
                {
                    "tool": tool_name,
                    "params": args or {},
                    "risk_score": float(sec_local.get("risk_adj") or 0.0) / 100.0,
                    "signals": signals,
                    "severity": sev or "info",
                    "ai_assisted": True,
                }
            )
            if gate.decision == "deny":
                return {
                    "allow": False,
                    "reason": "policy_gate_deny",
                    "action": gate.action or "security_review",
                    "rule_hits": gate.rule_hits,
                }
            return {"allow": True}

        def event_fn(event_type: str, data: Dict[str, Any], _state) -> None:
            if not trace_id:
                return
            try:
                tb = None
                try:
                    tb = getattr(_state, "tool_budget_remaining", None)
                except Exception:
                    tb = None
                payload = {"event": event_type, **(data or {})}
                if tb is not None:
                    payload["tool_budget_remaining"] = int(tb)
                log_trace_event(
                    trace_id=trace_id,
                    event_type="interleaving_event",
                    source_type="orchestrator",
                    source_id="InterleavingController",
                    target_type=None,
                    target_id=None,
                    payload=payload,
                )
                if event_type == "tool_rejected" and str((data or {}).get("reason") or "") == "budget_exhausted":
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="tool_budget_denied",
                        source_type="orchestrator",
                        source_id="InterleavingController",
                        target_type="agent",
                        target_id=str((data or {}).get("tool_name") or "unknown"),
                        payload={
                            "remaining": int(tb or 0),
                            "reason": "budget_exhausted",
                            "phase": "interleaving",
                        },
                    )
                if event_type == "tool_rejected" and str((data or {}).get("reason") or "") == "policy_denied":
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="tool_policy_denied",
                        source_type="orchestrator",
                        source_id="InterleavingController",
                        target_type="agent",
                        target_id=str((data or {}).get("tool_name") or "unknown"),
                        payload={
                            "policy_reason": str((data or {}).get("policy_reason") or "policy_denied"),
                            "policy_action": (data or {}).get("policy_action"),
                            "policy_rule_hits": (data or {}).get("policy_rule_hits") or {},
                            "phase": "interleaving",
                        },
                    )
            except Exception:
                pass

        summary = run_interleaved(
            controller,
            think_fn,
            tool_fn,
            observe_fn,
            event_fn=event_fn,
            calibrate_fn=calibrate_fn,
            tool_policy_fn=tool_policy_fn,
        )
        try:
            if isinstance(summary, dict) and isinstance(ctx, dict):
                ctx.setdefault("interleaving", {}).update(summary)
        except Exception:
            pass
        try:
            if trace_id:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="interleaving_summary",
                    source_type="orchestrator",
                    source_id="InterleavingController",
                    target_type=None,
                    target_id=None,
                    payload={
                        "tier": getattr(tier_decision, "tier", None),
                        "reason": getattr(tier_decision, "reason", None),
                        "tool_budget": getattr(tier_decision, "tool_budget", None),
                        "summary": summary,
                        "risk_adj": sec.get("risk_adj") if isinstance(sec, dict) else None,
                    },
                )
        except Exception:
            pass
        return summary

    # ------------------ End model tiering helpers ------------------

    def _emit_cv_trace_tags(self, trace_id: str | None, source: str, result: Dict[str, Any]) -> None:
        if not trace_id or not isinstance(result, dict):
            return
        payload = {
            "damage_type": result.get("damage_type"),
            "damage_severity": result.get("severity") or result.get("damage_severity"),
            "serial_number": result.get("serial_number"),
            "serial_match": result.get("serial_match"),
            "phash": result.get("phash"),
            "phash_match": result.get("phash_match"),
            "forensics_flags": result.get("forensics_flags"),
            "evidence_tags": result.get("evidence_tags"),
        }
        # Drop empty values to keep trace payload small
        payload = {k: v for k, v in payload.items() if v not in (None, "", [], {})}
        if not payload:
            return
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="cv_tags",
                source_type="cv_interleaving",
                source_id=source,
                target_type=None,
                target_id=None,
                payload=payload,
            )
        except Exception:
            pass

    def _run_cv_interleaving(
        self,
        uid: str,
        payload: Dict[str, Any],
        ctx: Dict[str, Any],
        trace_id: str | None,
    ) -> Dict[str, Any] | None:
        images = self._decode_images(payload.get("images") or payload.get("image_b64s") or payload.get("image_data"))
        if not images:
            return None
        img = images[0]
        controller = InterleavingController(
            agent_type="cv",
            max_iterations=int(self.flags.get("INTERLEAVING_CV_MAX_ITERS", 4) or 4),
            tool_budget=int(self.flags.get("INTERLEAVING_CV_BUDGET", 5) or 5),
            confidence_threshold=float(self.flags.get("INTERLEAVING_CV_CONF_THRESHOLD", 0.85) or 0.85),
            timeout_ms=int(self.flags.get("INTERLEAVING_CV_TIMEOUT_MS", 7000) or 7000),
        )

        def think_fn(state):
            # Deterministic default path for CV until LLM think is enabled
            plan = [
                "cv_quality_score",
                "cv_analyze",
                "cv_ocr_extract",
                "cv_verify_serial",
                "cv_check_phash",
                "cv_image_forensics",
                "cv_evidence_tags",
            ]
            called = {tc.tool_name for tc in state.tool_calls}
            for nxt in plan:
                if nxt in called:
                    continue
                if controller.can_call_tool(nxt):
                    return {"tool_name": nxt, "arguments": {}}
            return {"stop": True}

        def tool_fn(tool_name: str, _args: Dict) -> Any:
            def _tag(res: Any) -> None:
                try:
                    if isinstance(res, dict):
                        self._emit_cv_trace_tags(trace_id, tool_name, res)
                except Exception:
                    pass
            if tool_name == "cv_analyze":
                try:
                    from src.app.services.cv_provider import ManagedCVProvider
                    from src.app.services.cv_triage_basic import BasicCVTriage
                    import asyncio as _asyncio
                    labels, text = _asyncio.run(ManagedCVProvider().get_labels_and_text(img))
                    analysis = _asyncio.run(BasicCVTriage().analyze(labels, text))
                    out = dict(analysis or {})
                    out["labels"] = labels
                    out["extracted_text"] = text
                    _tag(out)
                    return out
                except Exception:
                    return {}
            if tool_name == "cv_tier_route":
                try:
                    from src.app.services.cv_tiered import TieredCVProvider
                    import asyncio as _asyncio
                    cvt = TieredCVProvider(flags=self.flags)
                    res = _asyncio.run(cvt.process(img, meta={"trace_id": trace_id}))
                    _tag(res)
                    return res
                except Exception:
                    return {}
            if tool_name == "cv_object_detect":
                try:
                    # Guard: run object detection only when image quality is good or risk warrants escalation
                    from src.app.services.cv_quality import score_quality
                    q = score_quality(img, labels=["sharp", "blurry", "dark", "glare"]) or {}
                    sharp = float((q.get("scores") or {}).get("sharp", 0.0) or 0.0)
                    blurry = float((q.get("scores") or {}).get("blurry", 0.0) or 0.0)
                    dark = float((q.get("scores") or {}).get("dark", 0.0) or 0.0)
                    import os as _os
                    risk_min = float(_os.environ.get("CV_DETECT_RISK_MIN", "40.0") or 40.0)
                    # If quality is poor and risk low, skip heavy detection
                    risk_adj = 0.0
                    try:
                        risk_adj = float((_args or {}).get("risk_adj") or 0.0)
                    except Exception:
                        risk_adj = 0.0
                    if (blurry > 0.6 or dark > 0.6) and risk_adj < risk_min:
                        res = {"detections": [], "skipped_due_quality": True}
                        _tag(res)
                        return res
                    from src.app.services.cv_object_detector import CVObjectDetector
                    det = CVObjectDetector(model_path=self.flags.get("CV_DETECTOR_MODEL")).detect(img)
                    res = {"detections": det, "summary": CVObjectDetector.summarize(det)}
                    _tag(res)
                    return res
                except Exception:
                    return {}
            if tool_name == "cv_damage_classify":
                try:
                    from src.app.services.cv_damage_classifier import DamageClassifier
                    dmg = DamageClassifier(
                        model_path=self.flags.get("CV_DAMAGE_MODEL"),
                        yolo_model_path=self.flags.get("CV_DAMAGE_YOLO_MODEL"),
                    ).classify(img)
                    res = dmg or {}
                    _tag(res)
                    return res
                except Exception:
                    return {}
            if tool_name == "cv_ocr_extract":
                try:
                    from src.app.services.cv_ocr import extract_text
                    res = extract_text(img, provider=self.flags.get("CV_OCR_PROVIDER") or "tesseract")
                    _tag(res)
                    return res
                except Exception:
                    return {"text": "", "confidence": 0.0}
            if tool_name == "cv_invoice_match":
                try:
                    from src.app.services.cv_ocr import extract_text
                    expected = payload.get("expected_invoice") or payload.get("invoice_number")
                    ocr = extract_text(img, provider=self.flags.get("CV_OCR_PROVIDER") or "tesseract")
                    text = ocr.get("text") if isinstance(ocr, dict) else ""
                    match = bool(expected and text and str(expected) in str(text))
                    res = {"invoice_number": expected, "invoice_match": match, "ocr_confidence": ocr.get("confidence")}
                    _tag(res)
                    return res
                except Exception:
                    return {"invoice_match": False}
            if tool_name in ("cv_verify_serial", "cv_serial_match"):
                try:
                    from src.app.services.cv_evidence import _extract_serial
                    expected = payload.get("expected_serial") or payload.get("serial_number")
                    ocr_text = _args.get("text") if isinstance(_args, dict) else None
                    if not ocr_text:
                        from src.app.services.cv_ocr import extract_text
                        ocr_text = extract_text(img).get("text")
                    observed = _extract_serial(ocr_text or "")
                    res = {"serial_number": observed, "expected_serial": expected, "serial_match": bool(expected and observed and expected == observed)}
                    _tag(res)
                    return res
                except Exception:
                    return {"serial_match": False}
            if tool_name in ("cv_check_phash", "cv_reverse_image_search", "cv_hash_index"):
                try:
                    from src.app.services.returns import image_phash_hex
                    from src.app.services.reverse_image_search import ReverseImageSearch
                    ph = image_phash_hex(img)
                    ris = ReverseImageSearch()
                    if tool_name == "cv_hash_index":
                        ris.index_phash(ph, case_id=payload.get("case_id"))
                        res = {"phash": ph, "indexed": True}
                        _tag(res)
                        return res
                    hits = ris.find_similar(ph, max_distance=8, limit=5)
                    res = {"phash": ph, "matches": hits, "phash_match": bool(hits)}
                    _tag(res)
                    return res
                except Exception:
                    return {"phash": None, "matches": []}
            if tool_name in ("cv_image_forensics", "cv_ela_detect", "cv_splice_detect", "cv_metadata_inspect", "cv_watermark_check", "cv_geo_tag_check"):
                try:
                    from src.app.services.image_forensics import ImageForensicsService
                    f = ImageForensicsService().analyze_image(img)
                    flags = []
                    if isinstance(f, dict):
                        if f.get("manipulation_score"):
                            flags.append("manipulation_score")
                        if f.get("splice_likelihood"):
                            flags.append("splice_likelihood")
                        if f.get("ela_score"):
                            flags.append("ela_score")
                    res = {"forensics": f, "forensics_flags": flags}
                    _tag(res)
                    return res
                except Exception:
                    return {"forensics": {}}
            if tool_name == "cv_quality_score":
                try:
                    from src.app.services.cv_quality import score_quality
                    res = score_quality(img, labels=["sharp", "blurry", "dark", "glare"])
                    _tag(res)
                    return res
                except Exception:
                    return {"scores": {}}
            if tool_name == "cv_evidence_tags":
                # Lightweight tags derived from prior context
                tags = []
                try:
                    if isinstance(ctx, dict):
                        cv = ctx.get("cv") or {}
                        if cv.get("damage_type"):
                            tags.append("damage_detected")
                        if cv.get("needs_human_review"):
                            tags.append("needs_human_review")
                except Exception:
                    pass
                res = {"evidence_tags": tags}
                _tag(res)
                return res
            if tool_name == "cv_compare_claim":
                try:
                    claim = payload.get("claim") or {}
                    observed = {}
                    if isinstance(ctx, dict):
                        observed = ctx.get("cv") or {}
                    matches = []
                    if claim and observed:
                        if claim.get("damage_type") and observed.get("damage_type") == claim.get("damage_type"):
                            matches.append("damage_type")
                        if claim.get("severity") and observed.get("severity") == claim.get("severity"):
                            matches.append("severity")
                    res = {"claim_match": bool(matches), "claim_fields_matched": matches}
                    _tag(res)
                    return res
                except Exception:
                    return {"claim_match": False}
            if tool_name == "cv_damage_severity":
                res = {"damage_severity": payload.get("damage_severity") or "unknown"}
                _tag(res)
                return res
            if tool_name == "cv_blur_detect":
                res = {"blur_detected": False}
                _tag(res)
                return res
            return {"status": "unknown_tool"}

        def observe_fn(result: Any, state) -> float:
            if isinstance(result, dict):
                if result.get("serial_match") is True:
                    return 0.9
                if result.get("phash_match") is True:
                    return 0.85
                if result.get("forensics_flags"):
                    return 0.8
                if result.get("evidence_tags"):
                    return 0.7
            return 0.55

        def calibrate_fn(raw: float, _state) -> float:
            return calibrate_confidence(raw, agent_type="cv")

        def event_fn(event_type: str, data: Dict[str, Any], _state) -> None:
            if not trace_id:
                return
            try:
                payload = {"event": event_type, **(data or {})}
                log_trace_event(
                    trace_id=trace_id,
                    event_type="interleaving_event",
                    source_type="cv",
                    source_id="InterleavingController",
                    target_type=None,
                    target_id=None,
                    payload=payload,
                )
            except Exception:
                pass

        def cv_tool_policy_fn(tool_name: str, args: Dict[str, Any], _state) -> Dict[str, Any]:
            return evaluate_tool_intent(
                tool_name=tool_name,
                params=args or {},
                runtime="cv_interleaving",
                tenant_id=(payload.get("tenant_id") if isinstance(payload, dict) else None),
                trace_id=trace_id,
            )

        summary = run_interleaved(
            controller,
            think_fn,
            tool_fn,
            observe_fn,
            event_fn=event_fn,
            calibrate_fn=calibrate_fn,
            tool_policy_fn=cv_tool_policy_fn,
        )
        try:
            if isinstance(summary, dict) and isinstance(ctx, dict):
                ctx.setdefault("cv_interleaving", {}).update(summary)
        except Exception:
            pass
        # Emit CV tag summary from last tool result if present
        try:
            if controller.state.tool_calls:
                last = controller.state.tool_calls[-1]
                if isinstance(last.result, dict):
                    self._emit_cv_trace_tags(trace_id, last.tool_name, last.result)
        except Exception:
            pass
        return summary

    def execute_or_escalate(self, uid: str, proposal: Dict[str, Any], policy: Dict[str, Any], retrieved_context: Dict[str, Any] | None = None, idempotency_key: str | None = None, simulate_only: bool = False) -> bool:
        # Use central log_decision contract to persist decisions
        if not self.flags.get("DECISION_LOG_WRITES_ENABLED", False):
            return not policy.get("approval_required", False)
        try:
            with db_session() as db:
                if idempotency_key:
                    try:
                        if getattr(db.bind, "dialect", None) is not None and db.bind.dialect.name == "sqlite":
                            db.execute(text("CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
                    except Exception:
                        pass
                    exists = None
                    try:
                        exists = db.execute(text("SELECT 1 FROM idempotency_keys WHERE key = :k"), {"k": idempotency_key}).scalar()
                    except Exception:
                        exists = None
                    ok, _msg = self.firewall.idempotency_ok(bool(exists))
                    if not ok:
                        return False
                    db.execute(text("INSERT INTO idempotency_keys (key) VALUES (:k)"), {"k": idempotency_key})
                    try:
                        db.commit()
                    except Exception:
                        pass
        except Exception:
            # best-effort idempotency tracking only
            pass

        # Build retrieved_context and tenant_id
        rc = retrieved_context if retrieved_context is not None else {"memory": self.memory.get_context(uid), "live": {"cart_total_cents": proposal.get("cart_total_cents"), "sku": proposal.get("sku")}}
        try:
            tenant = None
            if isinstance(rc, dict):
                mem = rc.get("memory") if isinstance(rc.get("memory"), dict) else {}
                live = rc.get("live") if isinstance(rc.get("live"), dict) else {}
                tenant = mem.get("tenant_id") or live.get("tenant_id") or None
        except Exception:
            tenant = None

        try:
            from src.app.services.decision_log import log_decision as _log
            status = "pending" if policy.get("approval_required") else "executed"
            _log(
                agent_name="pricing_agent",
                input_data={"uid_hash": hash_uid(uid), "proposal": security_sanitize(proposal)},
                retrieved_context=security_sanitize(rc),
                proposed_action=proposal,
                agent_reasoning=proposal.get("reason", ""),
                policy_version=self.flags.get("POLICY_VERSION", "v1"),
                approval_required=bool(policy.get("approval_required", False)),
                execution_status=status,
                tenant_id=tenant,
            )
        except Exception:
            # In test/local environments without DB, tolerate and proceed
            import traceback, sys
            traceback.print_exc(file=sys.stderr)
            return not policy.get("approval_required", False)
        # Return whether execution should proceed; simulate_only means no external
        # effects, but we still persist the decision for audit/observability.
        return not policy.get("approval_required", False) and not simulate_only

    def _run_internal(self, uid: str, payload: Dict[str, Any], simulate_only: bool = False, use_rules: bool = False) -> OrchestratorResult:
        timings: dict[str, float] = {}
        t0 = time.time()
        trace_id = self._ensure_trace_id(payload)
        self._init_trace_runtime(trace_id)
        try:
            print(f"[orch.run] start trace_id={trace_id} uid={uid} simulate_only={simulate_only}")
        except Exception:
            pass
        # In test/local runs where decision log DB isn't available, avoid
        # calling DB-backed logging functions to prevent OperationalError.
        # Respect monkeypatching in tests: only override if the globals still
        # point to the original implementations.
        try:
            if not bool(self.flags.get("DECISION_LOG_WRITES_ENABLED", True)):
                try:
                    import src.app.services.decision_log as _dl  # noqa: F401
                    try:
                        if globals().get("log_decision", _dl.log_decision) is _dl.log_decision:
                            globals()["log_decision"] = lambda *a, **k: None
                    except Exception:
                        pass
                    try:
                        if globals().get("log_trace_event", _dl.log_trace_event) is _dl.log_trace_event:
                            globals()["log_trace_event"] = lambda *a, **k: None
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        try:
            resumed = self._load_agent_state(trace_id)
            if resumed:
                payload["_resumed_state"] = resumed
                log_trace_event(
                    trace_id=trace_id,
                    event_type="feedback_loop",
                    source_type="orchestrator",
                    source_id="resume_state",
                    target_type=None,
                    target_id=None,
                    payload={"resume": True, "state": resumed},
                )
        except Exception:
            pass
        self._trace_phase(
            trace_id,
            phase="phase1",
            status="started",
            agents_planned=["NLP Explore", "CV Explore", "Security Explore"],
            meta={"discipline": "always_on"},
        )
        incident_ticket_id = None
        # Fast-path insider escalation before any heavy processing.
        idem_key = payload.get("idempotency_key") if isinstance(payload, dict) else None
        tenant_id = payload.get("tenant_id") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and payload.get("unusual_hours") and not self._incident_already_ticketed(trace_id, idem_key, tenant_id):
            try:
                t = TicketingAgent()
                title = "Security alert: insider context anomaly"
                desc = json.dumps({"payload": payload, "reason": "unusual_hours"}, ensure_ascii=False)
                ticket = self._create_incident_ticket(
                    title=title,
                    description=desc,
                    severity="high",
                    tenant_id=payload.get("tenant_id") or None,
                    trace_id=trace_id,
                )
                incident_ticket_id = getattr(ticket, "id", None)
                try:
                    payload["_insider_ticketed"] = True
                except Exception:
                    pass
                try:
                    self._mark_incident_ticketed(trace_id, idem_key, tenant_id)
                except Exception:
                    pass
                try:
                    log_decision(
                        agent_name="orchestrator.incident",
                        input_data={"payload": payload, "reason": "unusual_hours"},
                        retrieved_context={},
                        proposed_action={"ticket_id": incident_ticket_id},
                        agent_reasoning="auto incident route (actor context early)",
                        policy_version=self.flags.get("POLICY_VERSION", "v1"),
                        approval_required=False,
                        execution_status="executed",
                        tenant_id=payload.get("tenant_id") or None,
                        actor_id=payload.get("actor_id") or None,
                        actor_role=payload.get("actor_role") or None,
                        event_type="IncidentRoute",
                    )
                except Exception:
                    pass
            except Exception:
                pass
        ok, msg = self.validate(payload)
        t1 = time.time()
        timings["validate"] = t1 - t0
        # Chaos engineering: optional error/jitter injections for robustness testing
        try:
            chaos = self.flags.get("CHAOS", {"enabled": False})
        except Exception:
            chaos = {"enabled": False}
        try:
            if chaos.get("enabled"):
                err_prob = float(chaos.get("error_probability", 0.0) or 0.0)
                jitter_ms = float(chaos.get("jitter_ms", 0.0) or 0.0)
                if jitter_ms > 0:
                    time.sleep(jitter_ms / 1000.0)
                if err_prob > 0 and random.random() < err_prob:
                    # Record a chaos error without failing the flow
                    try:
                        from src.app.observability.metrics import record_chaos_error
                        record_chaos_error("orchestrator.run")
                    except Exception:
                        pass
                    try:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="chaos_error_injected",
                            source_type="orchestrator",
                            source_id="chaos_engine",
                            target_type=None,
                            target_id=None,
                            payload={"error_probability": err_prob, "jitter_ms": jitter_ms},
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        if not ok:
            raise ValueError(msg)
        ctx = self.retrieve(uid, payload)
        try:
            if trace_id:
                ss = ctx.get("structured_state") if isinstance(ctx, dict) else {}
                pb = ctx.get("product_memory_bank") if isinstance(ctx, dict) else {}
                log_trace_event(
                    trace_id=trace_id,
                    event_type="memory_phase0_recall",
                    source_type="orchestrator",
                    source_id="memory_recall",
                    target_type=None,
                    target_id=None,
                    payload={
                        "structured_keys": sorted(list((ss or {}).keys()))[:20] if isinstance(ss, dict) else [],
                        "product_bank_keys": sorted(list((pb or {}).keys()))[:20] if isinstance(pb, dict) else [],
                        "has_shortlist": bool((ss or {}).get("last_shortlist_skus")) if isinstance(ss, dict) else False,
                    },
                )
        except Exception:
            pass
        # Apply tier-0 guardrails early to sanitize payloads and capture actions
        try:
            g = apply_guardrails(payload, metadata={"memory": ctx.get("memory") if isinstance(ctx, dict) else {}, "retrieved": ctx.get("retrieved_context") if isinstance(ctx, dict) else {}})
            # replace payload with sanitized payload for downstream processing
            if isinstance(g, dict) and g.get("sanitized_payload"):
                payload = g.get("sanitized_payload")
            # attach guardrail actions into a trace event if trace_id available
            try:
                if trace_id and g.get("guardrail_actions"):
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="guardrail_actions",
                        source_type="guardrails",
                        source_id="guardrails.apply",
                        target_type=None,
                        target_id=None,
                        payload={"actions": g.get("guardrail_actions"), "flags": g.get("flags")},
                    )
            except Exception:
                pass
        except Exception:
            pass
        # Security analysis (observer) runs early to influence tier selection
        try:
            sec = analyze_payload(payload)
        except Exception:
            sec = {"severity": "info", "risk_adj": 0.0}
        # Early insider/security escalation to avoid missing high-risk cases
        try:
            sev = sec.get("severity") if isinstance(sec, dict) else None
            if sev not in ("high", "critical"):
                try:
                    insider_flag = bool(sec.get("insider_flag")) if isinstance(sec, dict) else False
                    insider_score = float(sec.get("insider_score") or 0.0) if isinstance(sec, dict) else 0.0
                except Exception:
                    insider_flag = False
                    insider_score = 0.0
                if insider_flag or insider_score >= 50 or (payload.get("actor_role") and payload.get("unusual_hours")):
                    sev = "high"
            if sev in ("high", "critical") and not self._incident_already_ticketed(trace_id, idem_key, tenant_id):
                t = TicketingAgent()
                title = f"Security alert: {sev} from orchestrator"
                desc = json.dumps({"payload": payload, "security": sec}, ensure_ascii=False)
                ticket = self._create_incident_ticket(
                    title=title,
                    description=desc,
                    severity=sev,
                    tenant_id=payload.get("tenant_id") or None,
                    trace_id=trace_id,
                )
                incident_ticket_id = getattr(ticket, "id", None)
                try:
                    log_decision(
                        agent_name="orchestrator.incident",
                        input_data={"payload": payload, "security": sec},
                        retrieved_context={},
                        proposed_action={"ticket_id": incident_ticket_id},
                        agent_reasoning="auto incident route (early)",
                        policy_version=self.flags.get("POLICY_VERSION", "v1"),
                        approval_required=False,
                        execution_status="executed",
                        tenant_id=payload.get("tenant_id") or None,
                        actor_id=payload.get("actor_id") or None,
                        actor_role=payload.get("actor_role") or None,
                        event_type="IncidentRoute",
                    )
                except Exception:
                    pass
                try:
                    self._mark_incident_ticketed(trace_id, idem_key, tenant_id)
                except Exception:
                    pass
        except Exception:
            pass
        # Immediate insider escalation based on actor context signals (already handled above)
        # Lightweight intent classification via central RuleEngine
        intent_result = {}
        try:
            if getattr(self, "rule_engine", None) is not None:
                qtxt = payload.get("query") or payload.get("input") or ""
                intent_result = self.rule_engine.evaluate(qtxt, ctx)
        except Exception:
            intent_result = {}

        # Tier routing decision (if available)
        try:
            if getattr(self, "tier_router", None) is not None:
                query = payload.get("query") or payload.get("input") or ""
                router_ctx = {
                    "amount": (payload.get("cart_total_cents", 0) or 0) / 100.0,
                    "multi_turn": bool(payload.get("multi_turn", False)),
                    "tenant_id": payload.get("tenant_id") or payload.get("tenant") or None,
                }
                tier_decision = self.tier_router.route(query=query, context=router_ctx, intent_result=intent_result, security_analysis=sec)
                try:
                    adaptive_budget = self._compute_adaptive_agent_budgets(
                        query=query,
                        tier=int(getattr(tier_decision, "tier", 1) or 1),
                        base_tool_budget=int(getattr(tier_decision, "tool_budget", 1) or 1),
                        risk_adj=float((sec or {}).get("risk_adj") or 0.0) if isinstance(sec, dict) else 0.0,
                        intent_confidence=float((intent_result or {}).get("confidence") or 1.0),
                        multi_turn=bool(router_ctx.get("multi_turn")),
                    )
                    try:
                        tier_decision.tool_budget = int(adaptive_budget.get("global_tool_budget") or tier_decision.tool_budget)
                    except Exception:
                        pass
                    rt = self._trace_runtime_flags.get(str(trace_id)) if trace_id else None
                    if isinstance(rt, dict):
                        rt["adaptive_budget"] = adaptive_budget
                        self._trace_runtime_flags[str(trace_id)] = rt
                except Exception:
                    adaptive_budget = {}
                # Log a trace event summarizing tier decision when trace_id provided
                try:
                    if trace_id:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="tier_decision",
                            source_type="orchestrator",
                            source_id="tier_router",
                            target_type=None,
                            target_id=None,
                            payload={
                                "tier": tier_decision.tier,
                                "reason": tier_decision.reason,
                                "tool_budget": tier_decision.tool_budget,
                                "model": tier_decision.model,
                                "adaptive_budget": adaptive_budget if isinstance(adaptive_budget, dict) else {},
                            },
                        )
                except Exception:
                    pass
                try:
                    if trace_id and isinstance(adaptive_budget, dict) and adaptive_budget:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="adaptive_budget_applied",
                            source_type="orchestrator",
                            source_id="budget_controller",
                            target_type=None,
                            target_id=None,
                            payload=adaptive_budget,
                        )
                except Exception:
                    pass
        except Exception:
            tier_decision = None
        # Choose model tier based on payload, retrieved context, and security analysis
        try:
            model_choice = self.choose_model_tier(payload, ctx, sec)
        except Exception:
            model_choice = {"text_tier": "T1", "vision_tier": "N/A", "model": None}
        # If tier_decision computed earlier, prefer its model selection when present
        try:
            if 'tier_decision' in locals() and tier_decision is not None:
                if tier_decision.model:
                    model_choice["model"] = tier_decision.model
                model_choice["tier_decision"] = {
                    "tier": tier_decision.tier,
                    "reason": tier_decision.reason,
                    "tool_budget": tier_decision.tool_budget,
                }
        except Exception:
            pass
        self._trace_phase(
            trace_id,
            phase="phase1",
            status="completed",
            agents_planned=None,
            meta={"intent_classified": bool(intent_result), "tier_selected": bool('tier_decision' in locals() and tier_decision is not None)},
        )
        self._trace_phase(
            trace_id,
            phase="phase2",
            status="started",
            agents_planned=["Recommend", "Fraud Score", "Inventory Check"],
            meta={"discipline": "always_on"},
        )
        # Agent behavior anomaly — downgrade tiers/fallback when high
        behavior = None
        try:
            from src.app.services.agent_behavior_anomaly import detect_behavior_anomaly
            behavior = detect_behavior_anomaly()
            if isinstance(behavior, dict):
                if str(behavior.get("label")) == "high":
                    # Downgrade text tier and skip interleaving for stability
                    model_choice["text_tier"] = "T1"
                    model_choice.setdefault("notes", []).append("behavior_anomaly_high_downgrade")
                    try:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="agent_behavior_anomaly",
                            source_type="orchestrator",
                            source_id="behavior_detector",
                            target_type=None,
                            target_id=None,
                            payload=behavior,
                        )
                    except Exception:
                        pass
        except Exception:
            behavior = None
        # Tier 2 interleaving (bounded tool loop)
        try:
            if 'tier_decision' in locals() and tier_decision is not None:
                self._run_interleaving(uid, payload, ctx, tier_decision, sec, trace_id)
        except Exception:
            pass
        # CV interleaving when images are present (feature-flagged)
        try:
            if self.flags.get("INTERLEAVING_CV_ENABLED", False):
                self._run_cv_interleaving(uid, payload, ctx, trace_id)
        except Exception:
            pass
        # Emit a DecisionProposed event for observability/audit
        try:
            log_decision(
                agent_name="orchestrator.proposal",
                input_data={"payload": payload, "security": sec},
                retrieved_context=ctx.get("retrieved_context") if isinstance(ctx, dict) else {},
                proposed_action={"model_choice": model_choice},
                agent_reasoning=f"tier_decision:{model_choice.get('text_tier')}",
                policy_version=self.flags.get("POLICY_VERSION", "v1"),
                approval_required=False,
                execution_status="proposed",
                tenant_id=payload.get("tenant_id") or payload.get("tenant") or None,
                actor_id=payload.get("actor_id") or None,
                actor_role=payload.get("actor_role") or None,
                event_type="DecisionProposed",
            )
        except Exception:
            pass
        # If security severity is high/critical, create a ticket and log an IncidentRoute
        try:
            sev = sec.get("severity") if isinstance(sec, dict) else None
            if sev not in ("high", "critical"):
                try:
                    insider_flag = bool(sec.get("insider_flag")) if isinstance(sec, dict) else False
                    insider_score = float(sec.get("insider_score") or 0.0) if isinstance(sec, dict) else 0.0
                except Exception:
                    insider_flag = False
                    insider_score = 0.0
                if insider_flag or insider_score >= 50 or (payload.get("actor_role") and payload.get("unusual_hours")):
                    sev = "high"
            if sev in ("high", "critical") and not incident_ticket_id and not self._incident_already_ticketed(trace_id, idem_key, tenant_id):
                t = TicketingAgent()
                title = f"Security alert: {sev} from orchestrator"
                desc = json.dumps({"payload": payload, "security": sec, "model_choice": model_choice}, ensure_ascii=False)
                ticket = self._create_incident_ticket(
                    title=title,
                    description=desc,
                    severity=sev,
                    tenant_id=payload.get("tenant_id") or None,
                    trace_id=trace_id,
                )
                self._emit_agent_handoff(
                    from_agent="Orchestrator_Agent",
                    to_agent="Incident_Response_Agent",
                    reason="security_incident",
                    context={
                        "severity": sev,
                        "trace_id": trace_id,
                        "ticket_id": getattr(ticket, "id", None),
                        "actor_id": payload.get("actor_id"),
                    },
                    trace_id=trace_id,
                )
                try:
                    log_decision(
                        agent_name="orchestrator.incident",
                        input_data={"payload": payload, "security": sec},
                        retrieved_context=ctx.get("retrieved_context") if isinstance(ctx, dict) else {},
                        proposed_action={"ticket_id": ticket.id},
                        agent_reasoning="auto incident route",
                        policy_version=self.flags.get("POLICY_VERSION", "v1"),
                        approval_required=False,
                        execution_status="executed",
                        tenant_id=payload.get("tenant_id") or None,
                        actor_id=payload.get("actor_id") or None,
                        actor_role=payload.get("actor_role") or None,
                        event_type="IncidentRoute",
                    )
                except Exception:
                    pass
                try:
                    self._mark_incident_ticketed(trace_id, idem_key, tenant_id)
                except Exception:
                    pass
        except Exception:
            pass
        t2 = time.time()
        timings["retrieve"] = t2 - t1
        proposal = self.rule_based_reason(ctx) if use_rules else self.reason(ctx)
        proposal["decision_mode"] = "rules" if use_rules else "agent"
        proposal["factor_telemetry"] = {
            "decision_mode": proposal["decision_mode"],
            "window_precision": "na",
            "context_multipliers": "default",
            "factor_rankings": [],
        }
        t3 = time.time()
        timings["reason"] = t3 - t2
        # Record the chosen model and tiers in the proposal for observability (llm usage metadata)
        try:
            proposal["llm_model"] = model_choice.get("model") if isinstance(model_choice, dict) else None
            proposal["text_tier"] = model_choice.get("text_tier") if isinstance(model_choice, dict) else None
            proposal["vision_tier"] = model_choice.get("vision_tier") if isinstance(model_choice, dict) else None
            proposal["trace_id"] = trace_id
            if trace_id:
                rt = self._trace_runtime_flags.get(str(trace_id)) or {}
                if isinstance(rt.get("adaptive_budget"), dict) and rt.get("adaptive_budget"):
                    proposal["adaptive_budget"] = rt.get("adaptive_budget")
                if self._trace_is_degraded(trace_id):
                    proposal["decision_mode"] = "degraded"
                    proposal["degraded"] = True
                    proposal["degrade_reasons"] = self._trace_degrade_reasons(trace_id)
                    try:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="auto_degrade_policy",
                            source_type="orchestrator",
                            source_id="slo_guard",
                            target_type=None,
                            target_id=None,
                            payload={"reasons": proposal.get("degrade_reasons") or ["step_slo_breach"]},
                        )
                    except Exception:
                        pass
            if behavior:
                proposal["agent_behavior_anomaly"] = behavior
        except Exception:
            proposal["llm_model"] = None
            proposal["text_tier"] = None
            proposal["vision_tier"] = None
        self._trace_phase(
            trace_id,
            phase="phase2",
            status="completed",
            agents_planned=None,
            meta={"proposal_ready": True},
        )
        self._trace_phase(
            trace_id,
            phase="phase3",
            status="started",
            agents_planned=["InterleavingController"],
            meta={"discipline": "always_on"},
        )
        policy = self.policy(proposal)
        try:
            if trace_id and self._trace_is_degraded(trace_id):
                policy["status"] = "degraded"
                policy.setdefault("reason_codes", [])
                if "step_slo_breach" not in policy.get("reason_codes", []):
                    policy["reason_codes"] = list(policy.get("reason_codes") or []) + ["step_slo_breach"]
        except Exception:
            pass
        try:
            record_agent_invocation("orchestrator", "proposed", None)
        except Exception:
            pass
        try:
            print("[orch.run] policy computed")
        except Exception:
            pass
        # Policy gate evaluation (LLM/rules); attach to policy metadata and emit trace
        try:
            if getattr(self, "policy_gate", None) is not None:
                pg = self.policy_gate.evaluate({"proposal": proposal}, context=ctx)
                # attach gate result to policy for downstream decisioning
                policy["policy_gate"] = pg
                # publish a trace event if trace_id present
                try:
                    if trace_id:
                        # Emit both a policy_gate (for SSE/UI tests) and a policy_verdict event
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="policy_gate",
                            source_type="policy_gate",
                            source_id="policy_gate",
                            target_type=None,
                            target_id=None,
                            payload=pg,
                        )
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="policy_verdict",
                            source_type="policy_gate",
                            source_id="policy_gate",
                            target_type=None,
                            target_id=None,
                            payload=pg,
                        )
                except Exception:
                    pass
                # Add policy-derived evidence tags for playbooks
                try:
                    verdict = pg.get("verdict") if isinstance(pg, dict) else None
                    if verdict == "escalate":
                        proposal.setdefault("evidence_tags", []).append("approval_required")
                    if isinstance(pg, dict) and "threshold" in (pg.get("reason") or "").lower():
                        proposal.setdefault("evidence_tags", []).append("threshold_breach")
                except Exception:
                    pass
        except Exception:
            pass
        try:
            synthesis = deterministic_conflict_resolution(
                proposal=proposal,
                policy=policy,
                security=(sec if isinstance(sec, dict) else {}),
                fraud=(proposal.get("fraud") if isinstance(proposal.get("fraud"), dict) else {}),
            )
            proposal["synthesis_reasoning"] = synthesis
            policy = apply_synthesis_to_policy(policy, synthesis)
            self._emit_synthesis_reasoning(trace_id=trace_id, synthesis=synthesis, proposal=proposal)
        except Exception:
            pass
        self._trace_phase(
            trace_id,
            phase="phase3",
            status="completed",
            agents_planned=None,
            meta={"synthesis": "deterministic_conflict_v1"},
        )
        t4 = time.time()
        timings["policy"] = t4 - t3
        # Auto-decision: allow CV-driven auto approve/deny when enabled and safe
        try:
            try:
                print(f"[orch.run] entering auto-decision block; flags.AUTO_CV_DECISIONS_ENABLED={self.flags.get('AUTO_CV_DECISIONS_ENABLED')}")
            except Exception:
                pass
            if self.flags.get("AUTO_CV_DECISIONS_ENABLED", False):
                # Candidate sources: payload (e.g., /cv/upload), proposal['cv'], or proposal['cv_tier2']
                candidate = None
                if isinstance(payload, dict) and payload.get("cv_tier2"):
                    candidate = payload.get("cv_tier2")
                elif isinstance(proposal, dict) and proposal.get("cv_tier2"):
                    candidate = proposal.get("cv_tier2")
                elif isinstance(proposal, dict) and proposal.get("cv"):
                    candidate = proposal.get("cv")
                try:
                    print(f"[orch.run] auto-decision candidate={candidate}")
                except Exception:
                    pass
                if isinstance(candidate, dict):
                    # extract an explicit decision_action or nested verdict
                    decision_action = None
                    try:
                        verdict = candidate.get("verdict")
                        if isinstance(verdict, dict):
                            decision_action = candidate.get("decision_action") or verdict.get("verdict")
                        else:
                            decision_action = candidate.get("decision_action") or None
                    except Exception:
                        decision_action = candidate.get("decision_action") or None

                    if decision_action in ("approve", "deny"):
                        # Safety: only auto-execute when policy gate doesn't mandate manual approval
                        # Allow auto-decisions during simulate-only runs or when policy does not require approval
                        policy_override_allowed = not policy.get("approval_required", False) or bool(simulate_only)
                        if policy_override_allowed:
                            proposal["auto_decision"] = {"action": decision_action, "source": "cv", "verdict": candidate.get("verdict")}
                            try:
                                print(f"[orch.run] set auto_decision={proposal.get('auto_decision')}")
                            except Exception:
                                pass
                            # Record a trace event for audit
                            try:
                                if trace_id:
                                    log_trace_event(
                                        trace_id=trace_id,
                                        event_type="auto_cv_decision",
                                        source_type="orchestrator",
                                        source_id="auto_cv",
                                        target_type="case",
                                        target_id=payload.get("case_id") or None,
                                        payload={"action": decision_action, "verdict": candidate.get("verdict"), "policy_override_allowed": policy_override_allowed},
                                    )
                            except Exception:
                                pass
                            # Record auto-decision metric
                            try:
                                tenant = payload.get("tenant_id") or payload.get("tenant") or None
                                record_cv_auto_decision(decision_action, source="cv")
                                try:
                                    print(f"[orch.run] recorded metric for auto_decision {decision_action}")
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            # Return immediately with a proposed result when auto-decision applies
                            try:
                                return OrchestratorResult(proposal=proposal, firewall=policy, executed=not simulate_only, timings=timings)
                            except Exception:
                                pass
                            # If deny, mark needs_human_review for extra caution and route to escalation if desired
                            if decision_action == "deny":
                                proposal["needs_human_review"] = True
                                try:
                                    # Create a security ticket and emit SIEM/XDR event for high-risk denies
                                    ta = TicketingAgent()
                                    title = f"CV Forensics deny - {payload.get('case_id') or trace_id}"
                                    desc = json.dumps({"trace_id": trace_id, "case_id": payload.get("case_id"), "verdict": candidate.get("verdict"), "forensics": candidate.get("forensics")}, ensure_ascii=False)
                                    ticket = ta.create_ticket(title=title, description=desc, severity="high", tenant_id=payload.get("tenant_id") or None, trace_id=trace_id, cv_summary=candidate.get("verdict"), evidence_snapshot=(candidate.get("forensics") or {}), approval_required=False)
                                    self._emit_agent_handoff(
                                        from_agent="CV_Forensics_Agent",
                                        to_agent="Fraud_Review_Agent",
                                        reason="cv_auto_deny",
                                        context={
                                            "trace_id": trace_id,
                                            "case_id": payload.get("case_id"),
                                            "ticket_id": getattr(ticket, "id", None),
                                            "verdict": candidate.get("verdict"),
                                        },
                                        trace_id=trace_id,
                                    )
                                    # Emit security telemetry for SIEM/XDR
                                    try:
                                        record_security_event("cv_verdict_deny", "high", "cv_forensics")
                                    except Exception:
                                        pass
                                    try:
                                        record_cv_escalation("deny", tenant)
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                        else:
                            # Not allowed by policy; keep as proposed and require manual review
                            proposal.setdefault("auto_decision", {"action": "blocked_by_policy"})
                            try:
                                tenant = payload.get("tenant_id") or payload.get("tenant") or None
                                record_cv_escalation("blocked_by_policy", tenant)
                            except Exception:
                                pass
                            try:
                                return OrchestratorResult(proposal=proposal, firewall=policy, executed=not simulate_only, timings=timings)
                            except Exception:
                                pass
        except Exception:
            pass

    def _emit_synthesis_reasoning(
        self,
        *,
        trace_id: str | None,
        synthesis: Dict[str, Any] | None,
        proposal: Dict[str, Any] | None = None,
    ) -> None:
        if not trace_id or not isinstance(synthesis, dict):
            return
        try:
            payload = {
                "stage": "phase3",
                "synthesis_reasoning": synthesis,
                "proposal_id": (proposal or {}).get("proposal_id"),
                "synthesis_weight": (synthesis.get("synthesis_weight") if isinstance(synthesis, dict) else None),
            }
            log_trace_event(
                trace_id=trace_id,
                event_type="synthesis_reasoning",
                source_type="orchestrator",
                source_id="synthesis_engine",
                target_type=None,
                target_id=None,
                payload=payload,
            )
        except Exception:
            pass

        selected_playbook = None
        playbook_run_id = None
        # Playbook selection (evidence-first) and attach to proposal for downstream UIs
        try:
            from src.app.services.security_playbooks import select_cv_playbook

            risk_band = None
            try:
                isf = proposal.get("fraud_isolation_forest") or {}
                lab = str(isf.get("label") or "minimal")
                if lab in ("medium", "high"):
                    risk_band = lab
            except Exception:
                risk_band = None
            evidence_tags = list(proposal.get("evidence_tags") or [])
            # Add tier & fallback tags
            try:
                td = model_choice.get("tier_decision") if isinstance(model_choice, dict) else None
                if td and int(td.get("tier") or 1) >= 2:
                    evidence_tags.append("tier_escalation")
            except Exception:
                pass
            try:
                notes = model_choice.get("notes") if isinstance(model_choice, dict) else []
                if notes and "behavior_anomaly_high_downgrade" in notes:
                    evidence_tags.append("model_fallback")
            except Exception:
                pass
            sel = select_cv_playbook(evidence_tags, risk_band)
            if isinstance(sel, dict):
                selected_playbook = sel
                proposal["selected_playbook"] = sel
                pb = sel.get("playbook") if isinstance(sel.get("playbook"), dict) else {}
                pbid = pb.get("id")
                pbver = pb.get("version")
                try:
                    if trace_id:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="proposal_build",
                            source_type="orchestrator",
                            source_id="playbook_selector",
                            target_type="playbook",
                            target_id=str(pbid or ""),
                            payload={"playbook_id": pbid, "playbook_version": pbver, "evidence_tags": evidence_tags[:24], "risk_band": risk_band},
                        )
                except Exception:
                    pass
                try:
                    playbook_run_id = start_playbook_run(
                        trace_id=trace_id,
                        decision_id=trace_id,
                        tenant_id=(payload.get("tenant_id") if isinstance(payload, dict) else None),
                        playbook=pb,
                        owner=((pb.get("owners") or [None])[0]),
                        metadata={"risk_band": risk_band, "triggered_by": sel.get("triggered_by"), "evidence_tags": evidence_tags[:24]},
                    )
                    if playbook_run_id:
                        proposal["playbook_run_id"] = playbook_run_id
                        append_playbook_step(
                            run_id=playbook_run_id,
                            event_type="proposal_build",
                            status="completed",
                            evidence={"playbook_id": pbid, "playbook_version": pbver, "triggered_by": sel.get("triggered_by")},
                        )
                        try:
                            action_exec = execute_typed_actions(
                                run_id=playbook_run_id,
                                actions=(pb.get("actions") if isinstance(pb.get("actions"), list) else []),
                                context={"trace_id": trace_id, "tenant_id": payload.get("tenant_id")},
                            )
                            proposal["playbook_actions"] = action_exec
                            append_playbook_step(
                                run_id=playbook_run_id,
                                event_type="execution_result",
                                status="completed" if not action_exec.get("failed") else "failed",
                                evidence={"typed_actions": action_exec},
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
                # Wire ticketing for approvals on PB-POL playbooks
                try:
                    if pbid in ("PB-POL-001", "PB-POL-002") and policy.get("approval_required", False):
                        from src.app.services.ticketing import TicketingAgent
                        ta = TicketingAgent()
                        title = f"Approval workflow: {pbid}"
                        desc = f"Policy gate verdict requires approval. playbook={pbid}, trace_id={trace_id}"
                        sev = "medium"
                        ticket = ta.create_ticket(title=title, description=desc, severity=sev, trace_id=trace_id, approval_required=True)
                        proposal.setdefault("tickets", []).append({"id": getattr(ticket, "id", None), "status": getattr(ticket, "status", None)})
                        try:
                            log_trace_event(
                                trace_id=trace_id,
                                event_type="ticket_created",
                                source_type="orchestrator",
                                source_id="playbook_policy",
                                target_type="ticket",
                                target_id=str(getattr(ticket, "id", "")),
                                payload={"playbook": pbid, "status": getattr(ticket, "status", None)},
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        # ── Debate coordinator for complex queries (complexity ≥ 7 / tier ≥ 2) ──
        try:
            _complexity = 0
            try:
                _ab = (self._trace_runtime_flags.get(str(trace_id)) or {}).get("adaptive_budget") or {}
                _complexity = int(_ab.get("complexity_hits") or 0)
                _tier_val = 1
                try:
                    _tier_val = int(getattr(tier_decision, "tier", 1) or 1)
                except Exception:
                    pass
                if _tier_val >= 2:
                    _complexity += 4
                _risk = float((sec or {}).get("risk_adj") or 0.0) if isinstance(sec, dict) else 0.0
                if _risk >= 40.0:
                    _complexity += 2
            except Exception:
                pass
            if _complexity >= 7:
                from src.app.services.debate_coordinator import run_structured_debate
                _debate_scenario = "cv_ambiguity"
                try:
                    q = str((payload or {}).get("query") or "").lower()
                    if any(w in q for w in ("compare", "versus", "vs", "which is better", "tradeoff")):
                        _debate_scenario = "cv_ambiguity"
                    elif any(w in q for w in ("supplier", "vendor")):
                        _debate_scenario = "supplier_change"
                    elif any(w in q for w in ("policy", "rule")):
                        _debate_scenario = "policy_update"
                except Exception:
                    pass
                debate_result = run_structured_debate(
                    scenario=_debate_scenario,
                    proposal=proposal,
                    evidence=sec if isinstance(sec, dict) else {},
                )
                proposal["debate"] = debate_result
                if debate_result.get("judge", {}).get("decision") == "escalate":
                    proposal["needs_human_review"] = True
                try:
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="debate_completed",
                        source_type="orchestrator",
                        source_id="debate_coordinator",
                        target_type=None,
                        target_id=None,
                        payload={
                            "scenario": _debate_scenario,
                            "judge_decision": debate_result.get("judge", {}).get("decision"),
                            "risks": debate_result.get("challenger", {}).get("risks", []),
                            "complexity": _complexity,
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass

        # ── Self-reflection step: "Did we actually answer the user's question?" ──
        try:
            _query_text = str((payload or {}).get("query") or (payload or {}).get("input") or "").strip()
            if _query_text and isinstance(proposal, dict):
                _reflection_issues: List[str] = []
                _p_keys = set(proposal.keys())
                # Check: if user asked for recommendations, do we have products?
                _rec_keywords = {"recommend", "suggest", "find", "show", "laptop", "buy", "search"}
                if any(w in _query_text.lower() for w in _rec_keywords):
                    if not proposal.get("products") and not proposal.get("recommendations") and not proposal.get("ranked_products"):
                        _reflection_issues.append("no_products_in_response")
                # Check: if user asked a comparison, do we have multiple products?
                if any(w in _query_text.lower() for w in ("compare", "versus", "vs", "which")):
                    prods = proposal.get("products") or proposal.get("ranked_products") or []
                    if isinstance(prods, list) and len(prods) < 2:
                        _reflection_issues.append("comparison_needs_multiple_products")
                # Check: if user asked a price question, do we have price info?
                if any(w in _query_text.lower() for w in ("price", "cost", "how much", "budget", "cheap")):
                    if not proposal.get("price_range") and not proposal.get("budget_fit"):
                        _reflection_issues.append("price_info_missing")
                if _reflection_issues:
                    proposal["self_reflection"] = {
                        "issues": _reflection_issues,
                        "query_responded": False,
                    }
                    # Convert reflection findings into a user-facing fallback action.
                    _fallback_actions: List[str] = []
                    if "no_products_in_response" in _reflection_issues:
                        _fallback_actions.append("expand_budget_or_brand_constraints")
                    if "comparison_needs_multiple_products" in _reflection_issues:
                        _fallback_actions.append("request_second_candidate")
                    if "price_info_missing" in _reflection_issues:
                        _fallback_actions.append("request_budget_range")
                    proposal.setdefault("assistant_message", "")
                    if not str(proposal.get("assistant_message") or "").strip():
                        proposal["assistant_message"] = (
                            "I could not fully answer that yet. I can refine this quickly if you confirm your budget, "
                            "preferred brands, or whether you want me to broaden the criteria."
                        )
                    proposal["follow_up_suggestions"] = [
                        {"id": "broaden_constraints", "text": "Show alternatives just outside my budget"},
                        {"id": "compare_top2", "text": "Compare the top two options"},
                        {"id": "price_focus", "text": "Focus on best value options"},
                    ]
                    proposal["remediation"] = {
                        "required": True,
                        "actions": _fallback_actions or ["clarify_requirements"],
                    }
                else:
                    proposal["self_reflection"] = {"issues": [], "query_responded": True}
                try:
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="self_reflection",
                        source_type="orchestrator",
                        source_id="self_reflection",
                        target_type=None,
                        target_id=None,
                        payload=proposal["self_reflection"],
                    )
                except Exception:
                    pass
        except Exception:
            pass

        self._trace_phase(
            trace_id,
            phase="phase4",
            status="started",
            agents_planned=["Policy Gate", "Incident Response", "Execution Agent"],
            meta={"discipline": "always_on"},
        )
        executed = self.execute_or_escalate(
            uid,
            proposal,
            policy,
            retrieved_context=ctx.get("retrieved_context") if isinstance(ctx, dict) else None,
            idempotency_key=payload.get("idempotency_key"),
            simulate_only=simulate_only,
        )
        # Reward signal emission (+1 allow/executed, 0 escalate, -1 block)
        try:
            reward = 0
            verdict = policy.get("policy_gate", {}).get("verdict") if isinstance(policy.get("policy_gate"), dict) else None
            if verdict == "allow" and executed:
                reward = 1
            elif verdict == "block":
                reward = -1
            log_trace_event(
                trace_id=trace_id,
                event_type="reward_signal",
                source_type="orchestrator",
                source_id="reward_emitter",
                target_type=None,
                target_id=None,
                payload={"reward": reward, "verdict": verdict, "approval_required": policy.get("approval_required", False), "executed": executed},
            )
        except Exception:
            pass
        try:
            if policy.get("approval_required"):
                record_agent_escalation("orchestrator", "policy_gate")
                try:
                    tenant = payload.get("tenant_id") or payload.get("tenant") or None
                    record_cv_escalation("policy_gate", tenant)
                except Exception:
                    pass
            else:
                record_agent_invocation("orchestrator", "executed", None)
        except Exception:
            pass
        # Additional escalation metric when an explicit human review flag exists
        try:
            if proposal.get("needs_human_review"):
                tenant = payload.get("tenant_id") or payload.get("tenant") or None
                record_cv_escalation("needs_human_review", tenant)
        except Exception:
            pass
        self._trace_phase(
            trace_id,
            phase="phase4",
            status="completed",
            agents_planned=None,
            meta={"executed": bool(executed), "approval_required": bool(policy.get("approval_required", False))},
        )
        t5 = time.time()
        timings["execute_or_escalate"] = t5 - t4
        timings["total"] = t5 - t0
        self._save_agent_state(
            trace_id,
            {
                "phase": "phase4",
                "executed": bool(executed),
                "approval_required": bool(policy.get("approval_required", False)),
                "needs_human_review": bool(proposal.get("needs_human_review")),
                "ts": int(time.time()),
            },
        )
        try:
            pb = (selected_playbook or {}).get("playbook") if isinstance(selected_playbook, dict) else {}
            pbid = pb.get("id") if isinstance(pb, dict) else None
            pbver = pb.get("version") if isinstance(pb, dict) else None
            if trace_id and pbid:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="execution_result",
                    source_type="orchestrator",
                    source_id="playbook_executor",
                    target_type="playbook",
                    target_id=str(pbid),
                    payload={
                        "playbook_id": pbid,
                        "playbook_version": pbver,
                        "executed": bool(executed),
                        "approval_required": bool(policy.get("approval_required", False)),
                    },
                )
            if playbook_run_id:
                append_playbook_step(
                    run_id=playbook_run_id,
                    event_type="policy_verdict",
                    status="completed",
                    evidence={"approval_required": bool(policy.get("approval_required", False)), "policy_gate": policy.get("policy_gate")},
                )
                append_playbook_step(
                    run_id=playbook_run_id,
                    event_type="execution_result",
                    status="completed" if executed else "failed",
                    evidence={"executed": bool(executed), "needs_human_review": bool(proposal.get("needs_human_review"))},
                )
                append_playbook_step(
                    run_id=playbook_run_id,
                    event_type="feedback_loop",
                    status="pending",
                    evidence={"posthoc_link": "pending"},
                )
                complete_playbook_run(
                    run_id=playbook_run_id,
                    status="completed" if executed else "failed",
                    outcome="effective" if executed else "review_required",
                )
        except Exception:
            pass
        try:
            structured = self.memory.get_structured_state(uid) or {}
            structured["last_orchestrator_trace_id"] = trace_id
            structured["last_orchestrator_ts"] = int(time.time())
            structured["last_orchestrator_executed"] = bool(executed)
            structured["last_orchestrator_policy"] = {
                "approval_required": bool(policy.get("approval_required", False)),
                "allowed": bool(policy.get("allowed", False)),
            }
            if isinstance(proposal, dict):
                if proposal.get("proposal_id"):
                    structured["last_orchestrator_proposal_id"] = proposal.get("proposal_id")
                if proposal.get("cart_total_cents") is not None:
                    structured["last_orchestrator_cart_total_cents"] = proposal.get("cart_total_cents")
            self.memory.set_structured_state(uid, structured)

            bank = self.memory.get_product_memory_bank(uid) or {}
            runs = list(bank.get("orchestrator_runs") or [])
            runs.append(
                {
                    "ts": int(time.time()),
                    "trace_id": trace_id,
                    "executed": bool(executed),
                    "approval_required": bool(policy.get("approval_required", False)),
                    "ranked_skus": list((proposal or {}).get("ranked_skus") or [])[:12],
                }
            )
            bank["orchestrator_runs"] = runs[-20:]
            if isinstance(proposal, dict) and proposal.get("ranked_skus"):
                bank["last_ranked_skus"] = list(proposal.get("ranked_skus") or [])[:12]
            self.memory.set_product_memory_bank(uid, bank)

            if trace_id:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="memory_phase5_store",
                    source_type="orchestrator",
                    source_id="memory_store",
                    target_type=None,
                    target_id=None,
                    payload={
                        "executed": bool(executed),
                        "approval_required": bool(policy.get("approval_required", False)),
                    },
                )
        except Exception:
            pass
        # --- Layer 2/3/4 STORE: episodic save, observation compress, citation claim ---
        try:
            if EpisodicMemory is not None:
                ep = EpisodicMemory(self.memory, uid)
                ranked_skus = list((proposal or {}).get("ranked_skus") or [])[:12]
                ep.save_episode(
                    query=payload.get("query") or payload.get("user_input") or "",
                    answer=str((proposal or {}).get("reason") or ""),
                    products_shown=ranked_skus,
                    debate_ran=bool((proposal or {}).get("debate_result")),
                    model_used=str((proposal or {}).get("model_source") or ""),
                )
        except Exception:
            pass
        try:
            if Observer is not None:
                obs = Observer(self.memory, uid)
                obs.log_recommendation(list((proposal or {}).get("ranked_skus") or [])[:6])
                if (proposal or {}).get("debate_result"):
                    obs.log_debate(
                        scenario=(proposal or {}).get("debate_scenario", "unknown"),
                        decision=(proposal or {}).get("debate_result", {}).get("decision", "unknown"),
                        confidence=(proposal or {}).get("debate_result", {}).get("confidence"),
                    )
            if Reflector is not None:
                ref = Reflector(self.memory, uid)
                ref.maybe_compress()
        except Exception:
            pass
        try:
            if callable(store_claim) and isinstance(proposal, dict):
                ranked = list((proposal or {}).get("ranked_skus") or [])[:3]
                if ranked:
                    store_claim(
                        agent_name="recommendation",
                        claim_type="product_ranking",
                        claim_key=f"top3_{trace_id or 'unknown'}",
                        claim_value=json.dumps(ranked),
                        confidence=float((proposal or {}).get("why_confidence") or 0.5),
                        session_id=uid,
                    )
        except Exception:
            pass
        try:
            print(f"[orch.run] returning result trace_id={trace_id} executed={executed} proposal_keys={list(proposal.keys())[:12]}")
        except Exception:
            pass
        try:
            print("[orch.run] final return reached")
        except Exception:
            pass
        return OrchestratorResult(proposal=proposal, firewall=policy, executed=executed, timings=timings)

    def run(self, uid: str, payload: Dict[str, Any], simulate_only: bool = False, use_rules: bool = False) -> OrchestratorResult:
        trace_id = None
        try:
            if isinstance(payload, dict):
                trace_id = payload.get("trace_id") or payload.get("decision_id")
        except Exception:
            trace_id = None
        try:
            try:
                print("[orch.run] wrapper invoked")
            except Exception:
                pass
            res = self._run_internal(uid, payload, simulate_only=simulate_only, use_rules=use_rules)
            if res is None:
                try:
                    print("[orch.run] internal returned None; using fallback")
                except Exception:
                    pass
                raise RuntimeError("orchestrator_internal_return_none")
            return res
        except Exception as e:
            try:
                pid = None
                try:
                    pid = (payload or {}).get("trace_id") or (payload or {}).get("decision_id")
                except Exception:
                    pid = None
                print(f"[orch.run] exception fallback: {e}")
            except Exception:
                pass
            # Build a minimal proposal with tier metadata for tests
            try:
                spec = self.choose_model_tier(payload or {}, {"live": {"cart_total_cents": (payload or {}).get("cart_total_cents", 0)}}, {"risk_adj": 0.0})
            except Exception:
                spec = {"model": None, "text_tier": "T1", "vision_tier": "N/A"}
            # Attempt to compute canonical cart total from memory draft or payload
            cart_total = None
            try:
                ctx = self.memory.get_context(uid)
                draft_id = (ctx.get("kv") or {}).get("draft_cart_id") if isinstance(ctx, dict) else None
                if draft_id:
                    try:
                        computed = self.catalog.compute_cart_total(draft_id)
                        if isinstance(computed, (int, float)):
                            cart_total = int(computed)
                    except Exception:
                        cart_total = None
                if cart_total is None:
                    v = (payload or {}).get("cart_total_cents")
                    if isinstance(v, (int, float)):
                        cart_total = int(v)
            except Exception:
                cart_total = (payload or {}).get("cart_total_cents") if isinstance((payload or {}).get("cart_total_cents"), (int, float)) else None
            fallback_proposal = {
                "proposal_id": pid,
                "trace_id": pid,
                "error": str(e)[:200],
                "llm_model": spec.get("model"),
                "text_tier": spec.get("text_tier"),
                "vision_tier": spec.get("vision_tier"),
                "decision_mode": "fallback",
                "cart_total_cents": cart_total,
            }
            fallback_policy = {"allowed": False, "approval_required": True, "deterministic_outcome": "error"}
            return OrchestratorResult(proposal=fallback_proposal, firewall=fallback_policy, executed=False, timings=None)
        finally:
            try:
                if isinstance(payload, dict):
                    trace_id = trace_id or payload.get("trace_id") or payload.get("decision_id")
            except Exception:
                pass
            self._clear_trace_runtime(trace_id)
