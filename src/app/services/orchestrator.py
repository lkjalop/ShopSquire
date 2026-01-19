import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from src.app.models.db import db_session
from src.app.security.firewall import TransactionFirewall
from src.app.services.memory import Memory
from src.app.repositories.catalog import CatalogRepository
import random
import time
from sqlalchemy import text
from src.app.observability.metrics import chaos_injected_total


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

    def validate(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        if "cart_total_cents" not in payload:
            return False, "Missing cart_total_cents"
        return True, "OK"

    def retrieve(self, uid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Forced retrieval for volatile facts (price/stock)
        context = self.memory.get_context(uid)
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
        if draft_id:
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
        }
        self.memory.set_recent_retrieval(uid, live)
        return {"memory": context, "live": live}

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

    def policy(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        fw = self.firewall.check_pricing(
            cart_total_cents=proposal["cart_total_cents"],
            proposed_discount_percent=proposal["discount_percent"],
        )
        return {"allowed": fw.allowed, "approval_required": fw.approval_required, "reason": fw.reason}

    def execute_or_escalate(self, uid: str, proposal: Dict[str, Any], policy: Dict[str, Any], idempotency_key: str | None = None, simulate_only: bool = False) -> bool:
        # MVP: Just log a decision; no external calls
        if simulate_only:
            return False
        if not self.flags.get("DECISION_LOG_WRITES_ENABLED", False):
            return not policy.get("approval_required", False)
        try:
            with db_session() as db:
                if idempotency_key:
                    # check idempotency
                    exists = db.execute("SELECT 1 FROM idempotency_keys WHERE key = :k", {"k": idempotency_key}).scalar()
                    ok, msg = self.firewall.idempotency_ok(bool(exists))
                    if not ok:
                        return False
                    db.execute("INSERT INTO idempotency_keys (key) VALUES (:k)", {"k": idempotency_key})
                db.execute(
                    text(
                        """
                        INSERT INTO decision_logs (
                            id, agent_name, valid_from, input_data, retrieved_context, agent_reasoning, proposed_action,
                            policy_version, approval_required, execution_status
                        ) VALUES (
                            :id, :agent, now(), :input, :ctx, :reason, :action, :policy, :approval, :status
                        )
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "agent": "pricing_agent",
                        "input": json.dumps({"uid": uid, "proposal": proposal}, ensure_ascii=False),
                        "ctx": json.dumps({"note": "see memory.recent_retrieval"}, ensure_ascii=False),
                        "reason": proposal.get("reason", ""),
                        "action": json.dumps(proposal, ensure_ascii=False),
                        "policy": "v1",
                        "approval": policy.get("approval_required", False),
                        "status": "pending" if policy.get("approval_required") else "executed",
                    },
                )
                # Use SQLAlchemy text for explicit textual SQL
                db.execute(
                    text(
                        """
                        UPDATE decision_logs SET valid_from = valid_from WHERE agent_name = :agent
                        """
                    ),
                    {"agent": "pricing_agent"},
                )
                db.commit()
        except Exception:
            # In test/local environments without DB, tolerate and proceed
            return not policy.get("approval_required", False)
        return not policy.get("approval_required", False)

    def run(self, uid: str, payload: Dict[str, Any], simulate_only: bool = False) -> OrchestratorResult:
        timings: dict[str, float] = {}
        t0 = time.time()
        ok, msg = self.validate(payload)
        t1 = time.time()
        timings["validate"] = t1 - t0
        if not ok:
            raise ValueError(msg)
        ctx = self.retrieve(uid, payload)
        t2 = time.time()
        timings["retrieve"] = t2 - t1
        proposal = self.reason(ctx)
        t3 = time.time()
        timings["reason"] = t3 - t2
        policy = self.policy(proposal)
        t4 = time.time()
        timings["policy"] = t4 - t3
        executed = self.execute_or_escalate(
            uid,
            proposal,
            policy,
            idempotency_key=payload.get("idempotency_key"),
            simulate_only=simulate_only,
        )
        t5 = time.time()
        timings["execute_or_escalate"] = t5 - t4
        timings["total"] = t5 - t0
        return OrchestratorResult(proposal=proposal, firewall=policy, executed=executed, timings=timings)
