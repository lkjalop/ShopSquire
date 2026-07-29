"""V2-owned recommendation response and trace transaction.

The transaction is dependency-injected so compatibility adapters do not own
sanitization, formatting, security, or persistence semantics.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from src.app.services.negation_filter import apply_negation_exclusions


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResponseTransactionDependencies:
    security_sanitize: Callable[[dict[str, Any]], dict[str, Any]]
    sanitize_specs: Callable[[dict[str, Any]], Any]
    inject_knowledge: Callable[[dict[str, Any], str | None], Any]
    attach_evidence: Callable[[dict[str, Any], str | None], Any]
    localize: Callable[[dict[str, Any], Any], dict[str, Any]]
    exclude_off_category: Callable[[dict[str, Any]], dict[str, Any]]
    annotate_integrity: Callable[[dict[str, Any]], dict[str, Any]]
    formatter_enabled: Callable[[], bool]
    finalize_answer: Callable[[dict[str, Any]], dict[str, Any]]
    dereference_labels: Callable[[dict[str, Any]], dict[str, Any]]
    apply_security_challenge: Callable[[dict[str, Any]], dict[str, Any]]
    log_trace_event: Callable[..., Any]
    log_decision: Callable[..., Any]


def _intent_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    constraints = (
        payload.get("constraints_used")
        if isinstance(payload.get("constraints_used"), dict)
        else {}
    )
    use_case = (
        payload.get("use_case_analysis")
        if isinstance(payload.get("use_case_analysis"), dict)
        else {}
    )
    return {
        "persona": payload.get("buyer_persona") or constraints.get("buyer_persona"),
        "use_case_key": use_case.get("use_case_key") or constraints.get("use_case"),
        "budget_min": constraints.get("budget_min"),
        "budget_max": constraints.get("budget_max"),
        "source": "recommendation_payload",
    }


def _product_summary(payload: dict[str, Any]) -> list[dict[str, Any]]:
    products = []
    if isinstance(payload.get("results"), list):
        products = payload.get("results") or []
    elif isinstance(payload.get("products"), list):
        products = payload.get("products") or []
    elif isinstance((payload.get("proposal") or {}).get("results"), list):
        products = (payload.get("proposal") or {}).get("results") or []
    if (
        not products
        and not payload.get("off_catalog")
        and re.search(
            r"\b(top picks|i['’]ve found \d+|found \d+ "
            r"(matches|products|options))\b",
            str(payload.get("assistant_message") or payload.get("message") or "").lower(),
        )
    ):
        right_panel = (
            payload.get("right_panel")
            if isinstance(payload.get("right_panel"), dict)
            else {}
        )
        seeded = []
        for section_key in ("lower_tier", "higher_tier"):
            section = (
                right_panel.get(section_key)
                if isinstance(right_panel.get(section_key), dict)
                else {}
            )
            for item in (
                section.get("items")
                if isinstance(section.get("items"), list)
                else []
            ):
                if isinstance(item, dict):
                    seeded.append(dict(item))
        if seeded:
            products = seeded
            payload["results"] = seeded
            payload["products"] = seeded
        else:
            message = (
                "No products found in your current range. I can widen budget "
                "or show nearest in-stock options."
            )
            payload["assistant_message"] = message
            payload["message"] = message
    summary = []
    for product in products[:8]:
        if not isinstance(product, dict):
            continue
        summary.append({
            "sku": str(product.get("sku") or ""),
            "name": str(product.get("name") or ""),
            "score_norm": (
                float(product.get("score_norm"))
                if isinstance(product.get("score_norm"), (int, float))
                else product.get("score_norm")
            ),
            "reasons": [
                str(item)
                for item in (
                    product.get("reasons")
                    or (product.get("factors") or {}).get("positive")
                    or []
                )[:3]
            ],
            "reason_codes": (product.get("reason_codes") or [])[:3],
            "price": (
                float(product.get("price"))
                if isinstance(product.get("price"), (int, float))
                else product.get("price")
            ),
        })
    return summary


def _right_panel_contract(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("right_panel")
    source = source if isinstance(source, dict) else {}
    try:
        contract = json.loads(json.dumps(source, ensure_ascii=False, default=str))
    except Exception:
        contract = {"mode": str(source.get("mode") or "")}
    if "anchor_sections" not in contract:
        contract["anchor_sections"] = []
    return contract


def finalize_response_transaction(
    payload: dict[str, Any] | None,
    trace_id: str | None,
    *,
    dependencies: ResponseTransactionDependencies,
    negation_terms: list[str] | None = None,
    current_query: str = "",
) -> dict[str, Any]:
    """Apply the byte-compatible response pipeline and persist its trace once."""
    original = payload or {}
    try:
        output = dependencies.security_sanitize(original)
    except Exception:
        output = original
    try:
        dependencies.sanitize_specs(output)
    except Exception as exc:
        logger.debug("response spec sanitization skipped: %s", exc)
    dependencies.inject_knowledge(output, trace_id)
    dependencies.attach_evidence(output, trace_id)
    try:
        locale = (
            output.get("locale")
            or (output.get("constraints_used") or {}).get("locale")
            or ((output.get("proposal") or {}).get("nlp") or {}).get("locale")
        )
        output = dependencies.localize(output, locale)
    except Exception as exc:
        logger.debug("recommend payload localization skipped: %s", repr(exc)[:100])
    output = dependencies.exclude_off_category(output)
    output = apply_negation_exclusions(output, list(negation_terms or []))
    output = dependencies.annotate_integrity(output)
    if dependencies.formatter_enabled():
        output = dependencies.finalize_answer(output)
    output = dependencies.dereference_labels(output)
    output = dependencies.apply_security_challenge(output)
    if not trace_id:
        return output
    output["trace_id"] = trace_id
    output.setdefault("decision_trace_id", trace_id)
    output.setdefault("decision_id", trace_id)
    try:
        if not bool(output.get("_trace_recommendation_persisted")):
            products_summary = _product_summary(output)
            right_panel_contract = _right_panel_contract(output)
            intent = _intent_snapshot(output)
            execution_steps = output.get("execution_steps") or []
            dependencies.log_trace_event(
                trace_id=trace_id,
                event_type="recommendation_result",
                source_type="agent",
                source_id="Trace_Persistence_Agent",
                target_type="ui",
                target_id="right_panel",
                payload={
                    "products_summary": products_summary,
                    "right_panel_contract": right_panel_contract,
                    "intent_snapshot": intent,
                    "execution_steps": execution_steps,
                },
            )
            persisted_id = dependencies.log_decision(
                agent_name="Recommendation_Agent",
                input_data={"query": str(current_query or ""), "intent": intent},
                retrieved_context={
                    "agent_chain": output.get("agent_chain") or [{
                        "agent": "Recommendation_Agent",
                        "duration_ms": None,
                    }],
                    "products_count": len(products_summary),
                    "policy_gates": output.get("policy_gates") or {},
                    "right_panel_contract": right_panel_contract,
                    "execution_steps": execution_steps,
                },
                proposed_action={
                    "decision_mode": str(
                        output.get("decision_mode") or "catalog_recommendation",
                    ),
                    "results": products_summary,
                    "products_summary": products_summary,
                    "right_panel_contract": right_panel_contract,
                    "reasoning": (
                        output.get("assistant_message") or output.get("message")
                    ),
                },
                decision_id=trace_id,
                tenant_id=str(output.get("tenant_id") or "default"),
                actor_id=str(output.get("uid") or "") or None,
                actor_role="buyer",
                event_type="recommendation_result",
            )
            output["_trace_recommendation_persisted"] = bool(persisted_id)
    except Exception as exc:
        output["_trace_recommendation_persisted"] = False
        logger.warning(
            "recommendation trace persistence failed for %s: %s",
            trace_id,
            exc,
        )
    return output
