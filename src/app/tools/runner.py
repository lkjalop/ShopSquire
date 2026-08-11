from __future__ import annotations

import os
import json
import time
from typing import Any, Dict

import httpx

from src.app.observability.metrics import record_tool_invocation, record_mcp_security_block
from src.app.observability.tracing import get_tracer
from src.app.policy.gate import evaluate_policy_gate
from src.app.repositories.catalog import CatalogRepository
from src.app.security.agent_events import log_mcp_tool_invocation
from src.app.services.decision_log import log_trace_event
from src.app.services.registry import get_tool, get_tool_contract_fingerprint, get_tool_metadata, load_from_config
from src.app.routers.approvals import enqueue_approval
from src.app.services.agent_containment import is_contained


class ToolRunner:
    def __init__(self):
        self.bridge_url = os.getenv("TOOL_BRIDGE_URL", "http://localhost:9001")
        self.bridge_timeout = float(os.getenv("TOOL_BRIDGE_TIMEOUT", "2.0"))
        self.repo = CatalogRepository()
        self.tracer = get_tracer("tool-runner")
        try:
            load_from_config()
        except Exception:
            pass

    def _bridge_call(self, tool: str, params: Dict[str, Any], *, tenant_id: str | None, trace_id: str | None) -> Dict[str, Any]:
        with self.tracer.start_as_current_span("tools.bridge_call") as span:
            span.set_attribute("tools.bridge_url", self.bridge_url)
            span.set_attribute("tools.name", tool)
            with httpx.Client(timeout=self.bridge_timeout) as client:
                contract_hash = get_tool_contract_fingerprint(tool)
                headers = {"X-ShopSquire-Tool-Contract": contract_hash}
                bridge_token = str(os.getenv("TOOL_BRIDGE_TOKEN", "") or "").strip()
                if bridge_token:
                    headers["Authorization"] = f"Bearer {bridge_token}"
                resp = client.post(
                    f"{self.bridge_url.rstrip('/')}/tools/run",
                    headers=headers,
                    json={"tool": tool, "params": params, "tenant_id": tenant_id, "trace_id": trace_id, "contract_hash": contract_hash},
                )
                resp.raise_for_status()
                result = resp.json()
                strict = str(os.getenv("TOOL_BRIDGE_CONTRACT_ENFORCE", "0")).lower() in {"1", "true", "yes", "on"}
                returned_hash = str(result.pop("_tool_contract_hash", "") or "") if isinstance(result, dict) else ""
                if strict and returned_hash != contract_hash:
                    raise RuntimeError("tool_bridge_contract_mismatch")
                return result

    def _local_tool(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool == "catalog.search":
            query = str(params.get("query") or "")
            limit = int(params.get("limit") or 5)
            with self.tracer.start_as_current_span("tools.catalog_search") as span:
                span.set_attribute("tools.query_len", len(query))
                span.set_attribute("tools.limit", limit)
                products = self.repo.search_products(query, limit=limit)
            return {
                "results": [
                    {
                        "sku": p.sku,
                        "name": p.name,
                        "price_cents": p.price_cents,
                        "currency": p.currency,
                    }
                    for p in products
                ]
            }
        if tool == "inventory.check":
            sku = str(params.get("sku") or "")
            with self.tracer.start_as_current_span("tools.inventory_check") as span:
                span.set_attribute("tools.sku", sku)
                product = self.repo.get_product_by_sku(sku) if sku else None
                stock = self.repo.get_stock_by_product_id(product.id) if product else None
            return {"sku": sku, "stock": stock}
        if tool == "shipping.quote":
            subtotal = int(params.get("subtotal_cents") or 0)
            return {
                "carrier": "UPS",
                "service": "2-day",
                "cost_cents": max(799, int(subtotal * 0.05)),
                "eta_days": 2,
            }
        plugin = get_tool(tool)
        if callable(plugin):
            try:
                out = plugin(**params) if isinstance(params, dict) else plugin(params)
                return out if isinstance(out, dict) else {"result": out}
            except Exception as exc:
                return {"error": f"plugin_error:{exc}"}
        return {"error": "unknown_tool"}

    def run(self, tool: str, params: Dict[str, Any], source: str = "demo-user", trace_id: str | None = None, tenant_id: str | None = None) -> Dict[str, Any]:
        with self.tracer.start_as_current_span("tools.run") as span:
            span.set_attribute("tools.name", tool)
            try:
                tmeta = get_tool_metadata(tool)
                if tmeta:
                    span.set_attribute("tools.risk", str(tmeta.get("risk") or "unknown"))
            except Exception:
                pass
            start = time.perf_counter()
            status = "ok"
            result: Dict[str, Any] = {}
            source_mode = "bridge"
            # Enforcement: contained agents cannot execute tools (disable tool route).
            try:
                if is_contained(agent_id=str(source or ""), capability="tool_run"):
                    status = "blocked"
                    record_tool_invocation(tool, status, 0.0)
                    try:
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="agent_containment_enforced",
                            source_type="agent",
                            source_id="ToolRunner",
                            target_type="agent",
                            target_id=str(source or ""),
                            payload={"capability": "tool_run", "tool": tool, "status": "blocked"},
                        )
                    except Exception:
                        pass
                    return {
                        "tool": tool,
                        "status": status,
                        "source": "agent_containment",
                        "result": {"error": "agent_contained"},
                        "duration_seconds": 0.0,
                    }
            except Exception:
                pass
            try:
                gate_ctx = {
                    "tool": tool,
                    "params": params,
                    "policy_version": "2026-01-27",
                    "buyer_type": params.get("buyer_type"),
                    "compliance_provided": params.get("compliance_provided"),
                }
                gate = evaluate_policy_gate(gate_ctx)
                approval_id = None
                if gate.approval_required:
                    try:
                        approval_id = enqueue_approval(f"tool:{tool}", {"tool": tool, "params": params}, reason="policy_gate")
                    except Exception:
                        approval_id = None
                log_trace_event(
                    trace_id=trace_id,
                    event_type="policy_gate",
                    source_type="agent",
                    source_id="Policy_Gate_Agent",
                    target_type="system",
                    target_id=None,
                    payload={
                        "decision": gate.decision,
                        "reasons": gate.reasons,
                        "rule_hits": gate.rule_hits,
                        "policy_version": gate.policy_version,
                        "compliance_tags": gate.compliance_tags,
                        "action": gate.action,
                        "approval_required": gate.approval_required,
                        "approval_id": approval_id,
                        "tool": tool,
                    },
                )
                if gate.decision == "deny":
                    status = "blocked"
                    record_tool_invocation(tool, status, 0.0)
                    return {
                        "tool": tool,
                        "status": status,
                        "source": "policy_gate",
                        "policy_gate": {
                            "decision": gate.decision,
                            "reasons": gate.reasons,
                            "rule_hits": gate.rule_hits,
                            "policy_version": gate.policy_version,
                            "compliance_tags": gate.compliance_tags,
                            "action": gate.action,
                            "approval_required": gate.approval_required,
                            "approval_id": approval_id,
                        },
                        "result": {"error": "blocked_by_policy"},
                        "duration_seconds": 0.0,
                    }
                if gate.decision == "review":
                    status = "review_required"
                    record_tool_invocation(tool, status, 0.0)
                    return {
                        "tool": tool,
                        "status": status,
                        "source": "policy_gate",
                        "policy_gate": {
                            "decision": gate.decision,
                            "reasons": gate.reasons,
                            "rule_hits": gate.rule_hits,
                            "policy_version": gate.policy_version,
                            "compliance_tags": gate.compliance_tags,
                            "action": gate.action,
                            "approval_required": gate.approval_required,
                            "approval_id": approval_id,
                        },
                        "result": {"error": "review_required"},
                        "duration_seconds": 0.0,
                    }
            except Exception:
                pass
            # Pre-invocation security check (demo): block obvious injection markers
            try:
                params_str = json.dumps(params, ensure_ascii=False)
                import re
                injection = [
                    r"(?i)ignore\s+instructions",
                    r"(?i)\broot\b",
                    r"(?i)rm\s+-rf",
                ]
                if any(re.search(p, params_str) for p in injection):
                    record_mcp_security_block(tool, "prompt_injection")
                    status = "blocked"
                    record_tool_invocation(tool, status, 0.0)
                    try:
                        log_mcp_tool_invocation(
                            tool_name=tool,
                            source=source,
                            destination="blocked",
                            details={"status": status, "reason": "prompt_injection", "params": params},
                        )
                    except Exception:
                        pass
                    return {"tool": tool, "status": status, "source": "blocked", "result": {"error": "blocked_by_security"}, "duration_seconds": 0.0}
            except Exception:
                pass
            try:
                result = self._bridge_call(tool, params, tenant_id=tenant_id, trace_id=trace_id)
            except Exception:
                strict_bridge = str(os.getenv("TOOL_BRIDGE_CONTRACT_ENFORCE", "0")).lower() in {"1", "true", "yes", "on"}
                if strict_bridge:
                    status = "blocked"
                    duration = time.perf_counter() - start
                    record_tool_invocation(tool, status, duration)
                    return {
                        "tool": tool,
                        "status": status,
                        "source": "bridge_security_boundary",
                        "result": {"error": "tool_bridge_identity_or_contract_failure"},
                        "duration_seconds": duration,
                    }
                source_mode = "local"
                try:
                    result = self._local_tool(tool, params)
                    if result.get("error"):
                        status = "error"
                except Exception as exc:
                    status = "error"
                    result = {"error": str(exc)}
            duration = time.perf_counter() - start
            record_tool_invocation(tool, status, duration)
            try:
                log_mcp_tool_invocation(
                    tool_name=tool,
                    source=source,
                    destination=source_mode,
                    details={"status": status, "duration_seconds": duration, "params": params},
                )
            except Exception:
                pass
            return {"tool": tool, "status": status, "source": source_mode, "result": result, "duration_seconds": duration}
