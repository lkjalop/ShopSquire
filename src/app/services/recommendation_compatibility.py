"""V2-only compatibility edge for the retired legacy /recommend/suggest surface."""
from __future__ import annotations

import uuid
import re
from typing import Any, Dict

from fastapi import HTTPException


def _compatibility_use_case_tags(query: str, payload: Dict[str, Any]) -> list[str]:
    """Project governed V2 use cases into the frozen /suggest tag vocabulary.

    These tags are presentation compatibility only. They do not add requirements,
    authorize filtering, or override the V2 turn decision.
    """
    constraints = payload.get("constraints_used")
    constraints = constraints if isinstance(constraints, dict) else {}
    intent = payload.get("intent")
    intent = intent if isinstance(intent, dict) else {}
    canonical = [
        str(value).strip().lower()
        for value in (
            list(constraints.get("use_cases") or [])
            + list(intent.get("use_cases") or [])
            + list(intent.get("context_use_cases") or [])
            + list(intent.get("workload_use_cases") or [])
        )
        if str(value).strip()
    ]
    try:
        from src.app.services.recommend_budget_parsing import load_capability_kb

        kb = load_capability_kb()
        aliases = kb.get("use_case_aliases") or {}
        known = kb.get("use_cases") or {}
        normalized_query = " ".join(str(query or "").lower().split())
        for phrase, value in {**{key: key for key in known}, **aliases}.items():
            token = " ".join(str(phrase).lower().split())
            if token and re.search(rf"(?<!\w){re.escape(token)}(?!\w)", normalized_query):
                canonical.append(str(value).strip().lower())
    except Exception:
        pass
    legacy_names = {
        "university": "student",
        "corporate": "business",
        "creative": "content_creation",
    }
    tags: list[str] = []
    for value in canonical:
        tag = legacy_names.get(value, value)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _apply_frozen_compatibility_fields(
    *,
    payload: Dict[str, Any],
    query: str,
    classification: Dict[str, Any],
    compatibility_constraints: Dict[str, Any],
) -> None:
    """Populate fields explicitly retained by the frozen /suggest edge contract."""
    constraints = payload.get("constraints_used")
    constraints = constraints if isinstance(constraints, dict) else {}
    payload["constraints_used"] = constraints
    tags = _compatibility_use_case_tags(query, payload)
    if tags:
        constraints.setdefault("use_case_tags", tags)
        constraints.setdefault("use_case", tags[0])
    classified_intent = classification.get("turn_intent")
    if classified_intent in {"SUPPORT_CLAIM", "OFF_DOMAIN"}:
        constraints["turn_intent"] = classified_intent
    else:
        constraints.setdefault(
            "turn_intent",
            payload.get("turn_intent") or classified_intent,
        )
    slots = constraints.get("slots")
    slots = dict(slots) if isinstance(slots, dict) else {}
    if compatibility_constraints.get("budget_min") is not None:
        slots.setdefault("price_min", compatibility_constraints["budget_min"])
    if compatibility_constraints.get("budget_max") is not None:
        slots.setdefault("price_max", compatibility_constraints["budget_max"])
    constraints["slots"] = slots

    from src.app.services.recommend_budget_parsing import build_price_buckets

    payload["price_buckets"] = build_price_buckets(
        results=list(payload.get("results") or payload.get("products") or []),
        constraints=constraints,
    )
    timing = payload.get("timing_breakdown")
    timing = dict(timing) if isinstance(timing, dict) else {}
    timing.setdefault("compound_needed", False)
    timing.setdefault("compound_mode", "skip")
    payload["timing_breakdown"] = timing


def _persist_compatibility_outcome(
    *,
    trace_id: str,
    tenant_id: str,
    uid: str,
    query: str,
    status: str,
    reason: str,
    lane: str | None,
    payload: Dict[str, Any],
) -> None:
    """Persist an honest terminal compatibility outcome without reshaping the response.

    Refusals and unavailable V2 turns still expose a decision/trace identifier.  The
    identifier must resolve through the canonical decision endpoint even though no
    products or consequential actions were produced.
    """
    from src.app.services.decision_log import log_decision, log_trace_event

    safe_summary = {
        "status": status,
        "reason": reason,
        "lane": lane,
        "action_executed": False,
        "product_count": len(payload.get("products") or []),
    }
    log_trace_event(
        trace_id=trace_id,
        event_type="recommendation_compatibility_outcome",
        source_type="boundary",
        source_id="Recommendation_Compatibility",
        target_type="decision",
        target_id=trace_id,
        payload=safe_summary,
    )
    log_decision(
        agent_name="Recommendation_Compatibility",
        input_data={"query": str(query or "")[:1000]},
        retrieved_context={"compatibility_outcome": safe_summary},
        proposed_action={
            "decision_mode": "no_action",
            "action_executed": False,
            "reason": reason,
            "lane": lane,
            "evidence_items": [],
        },
        decision_id=trace_id,
        tenant_id=tenant_id,
        actor_id=uid or None,
        actor_role="buyer",
        event_type="recommendation_compatibility_outcome",
        execution_status="blocked" if status == "blocked" else "unavailable",
    )


def serve_v2_compatibility(
    *,
    request: Any,
    params: Dict[str, Any],
    redis: Any,
    db: Any,
    role: str,
) -> Dict[str, Any]:
    from src.app.observability.metrics import (
        record_recommend_compatibility_request,
        record_recommendation_dispatch,
    )
    from src.app.services.recommendation_delegation_policy import (
        v2_only_unavailable_response,
    )
    from src.app.services.recommendation_facade import dispatch_recommendation_core_typed

    tenant_id = (
        request.headers.get("X-Tenant-Id")
        or request.headers.get("x-tenant-id")
        or "default"
    ) if request is not None else "default"
    from src.app.services.recommendation_ingress import authorize_recommendation_ingress

    ingress = authorize_recommendation_ingress(
        request=request,
        redis=redis,
        query=str(params.get("query") or ""),
        uid=str(params.get("uid") or ""),
        tenant_id=tenant_id,
    )
    trace_id = str(params.get("trace_id") or ingress.trace_id or uuid.uuid4())
    from src.app.services.query_classifier import classify_query

    classification = classify_query(
        str(params.get("query") or ""),
        has_image=bool(params.get("image_labels") or params.get("image_hash")),
    )
    compatibility_constraints: Dict[str, Any] = {}
    if params.get("budget_min") is not None:
        compatibility_constraints["budget_min"] = params.get("budget_min")
    if params.get("budget_max") is not None:
        compatibility_constraints["budget_max"] = params.get("budget_max")
    if not compatibility_constraints:
        from src.app.services.budget_grammar import parse_budget

        parsed_budget = parse_budget(str(params.get("query") or ""))
        if parsed_budget is not None and parsed_budget.budget_min is not None:
            compatibility_constraints["budget_min"] = parsed_budget.budget_min
        if parsed_budget is not None and parsed_budget.budget_max is not None:
            compatibility_constraints["budget_max"] = parsed_budget.budget_max
    if (
        classification.get("turn_intent") == "SUPPORT_CLAIM"
        and classification.get("category")
        and compatibility_constraints
    ):
        # A product search that also asks a pre-sale policy question remains a
        # shopping turn. Post-purchase claims do not carry a fresh product budget.
        classification = dict(classification)
        classification["turn_intent"] = "FILTER"
    from src.app.services.bulk_intent import absurd_quantity_span, extract_quantity_span

    unit_nouns = (
        "laptop", "laptops", "computer", "computers", "desktop", "desktops",
        "monitor", "monitors", "tablet", "tablets", "phone", "phones",
        "keyboard", "keyboards", "mouse", "mice", "headset", "headsets",
        "router", "routers", "charger", "chargers", "dock", "docks",
    )
    quantity_span = extract_quantity_span(
        str(params.get("query") or ""),
        unit_nouns=unit_nouns,
    )
    absurd_quantity = absurd_quantity_span(
        str(params.get("query") or ""),
        unit_nouns=unit_nouns,
    )
    if quantity_span:
        compatibility_constraints["order_quantity"] = quantity_span[0]
    from src.app.services.recommend_nqe_helpers import apply_nqe_selection_to_constraints

    nqe_selection = apply_nqe_selection_to_constraints(
        constraints=compatibility_constraints,
        nqe_question_id=params.get("nqe_question_id"),
        nqe_option_id=params.get("nqe_option_id"),
        nqe_option_label=params.get("nqe_option_label"),
        nqe_option_value=params.get("nqe_option_value"),
    )
    from src.app.services.b2b_intent import assess_b2b_intent
    from src.app.services.escalation_policy import assess_escalation

    b2b_assessment = assess_b2b_intent(
        str(params.get("query") or ""),
        quantity=compatibility_constraints.get("order_quantity"),
    )
    escalation_assessment = assess_escalation(
        order_quantity=compatibility_constraints.get("order_quantity") or 1,
        b2b=b2b_assessment.wants_procurement_questions,
        review_requested=b2b_assessment.verdict == "ambiguous_bulk",
        irreversible_action=b2b_assessment.verdict == "anomalous",
    )
    intent_hint = params.get("turn_intent") or classification.get("turn_intent")
    outcome = dispatch_recommendation_core_typed(
        db,
        redis,
        query=str(params.get("query") or ""),
        uid=str(params.get("uid") or ""),
        tenant_id=tenant_id,
        budget_min=compatibility_constraints.get("budget_min"),
        budget_max=compatibility_constraints.get("budget_max"),
        trace_id=trace_id,
        image_labels=params.get("image_labels"),
        image_hash=params.get("image_hash"),
        image_ocr=params.get("image_ocr_text"),
        source_ip=(
            request.client.host
            if request is not None and request.client is not None
            else None
        ),
        request=request,
        image_intent=params.get("image_intent"),
        image_product_identity=params.get("image_product_identity"),
        image_cv_signals=params.get("image_cv_signals"),
        external_research_consent=bool(params.get("external_research_consent")),
        intent_hint=intent_hint,
        role=role,
        confirmed_slots={
            **(
                params.get("confirmed_slots")
                if isinstance(params.get("confirmed_slots"), dict)
                else {}
            ),
            **compatibility_constraints,
        },
        compatibility_cutover=True,
    )
    if outcome.served:
        record_recommendation_dispatch(
            outcome="v2_served",
            lane=outcome.lane,
            reason="compatibility_cutover",
        )
        record_recommend_compatibility_request("served")
        payload = dict(outcome.payload or {})
        payload.setdefault("execution_mode", "v2_compatibility")
        payload.setdefault("execution_lane", outcome.lane)
        payload.setdefault("products", list(payload.get("results") or []))
        payload.setdefault("results", list(payload.get("products") or []))
        constraints_used = (
            dict(payload.get("constraints_used") or {})
            if isinstance(payload.get("constraints_used"), dict)
            else {}
        )
        for name in ("budget_min", "budget_max"):
            cents = constraints_used.get(f"{name}_cents")
            if name not in constraints_used and isinstance(cents, (int, float)):
                constraints_used[name] = cents / 100
            if name not in constraints_used and compatibility_constraints.get(name) is not None:
                constraints_used[name] = compatibility_constraints[name]
        payload["constraints_used"] = constraints_used
        if compatibility_constraints.get("order_quantity") is not None:
            constraints_used.setdefault(
                "order_quantity", compatibility_constraints["order_quantity"]
            )
        _apply_frozen_compatibility_fields(
            payload=payload,
            query=str(params.get("query") or ""),
            classification=classification,
            compatibility_constraints=compatibility_constraints,
        )
        if absurd_quantity is not None:
            from src.app.services.bulk_intent import MAX_SOURCEABLE_QTY

            payload["refusal_note"] = (
                f"The requested quantity is outside the bounded sourcing limit; "
                f"the maximum supported request is {MAX_SOURCEABLE_QTY:,} units."
            )
        elif (
            compatibility_constraints.get("order_quantity")
            and compatibility_constraints.get("budget_max") is not None
            and not (payload.get("products") or payload.get("results"))
        ):
            from src.app.services.budget_grammar import classify_budget_scope

            if classify_budget_scope(str(params.get("query") or "")) == "total":
                payload["refusal_note"] = (
                    f"The available unit prices add up to more than the stated total "
                    f"budget for {compatibility_constraints['order_quantity']} units."
                )
        if nqe_selection:
            payload["nqe_selection_applied"] = nqe_selection
        payload["b2b_assessment"] = b2b_assessment.to_dict()
        payload["escalation_assessment"] = escalation_assessment.to_dict()
        if escalation_assessment.escalate:
            payload["needs_human_review"] = True
        if b2b_assessment.wants_procurement_questions:
            questions = [
                question for question in (payload.get("next_questions") or [])
                if isinstance(question, dict)
            ]
            if not any(question.get("id") == "ask_b2b_procurement" for question in questions):
                questions.insert(
                    0,
                    {
                        "id": "ask_b2b_procurement",
                        "label": "Confirm procurement requirements",
                    },
                )
            payload["next_questions"] = questions
        if classification.get("injection_attempt") or payload.get("injection_blocked"):
            payload["products"] = []
            payload["results"] = []
            payload["recommendations"] = []
            payload["status"] = "review_required"
            payload["assistant_message"] = str(
                payload.get("assistant_message")
                or payload.get("answer")
                or payload.get("message")
                or "I can't help with that request."
            )
            payload["message"] = payload["assistant_message"]
            payload["next_questions"] = []
            payload["injection_blocked"] = True
        elif classification.get("off_domain"):
            payload["products"] = []
            payload["results"] = []
            payload["status"] = "off_domain_request"
            payload["turn_intent"] = "OFF_DOMAIN"
            payload["assistant_message"] = (
                "I can help with shopping, product comparisons, orders, returns, "
                "and support questions."
            )
            payload["message"] = payload["assistant_message"]
            payload["next_questions"] = []
        elif (
            classification.get("turn_intent") == "SUPPORT_CLAIM"
            or str(payload.get("turn_intent") or "").upper() == "SUPPORT_CLAIM"
        ):
            payload["products"] = []
            payload["results"] = []
            payload["status"] = "support_claim"
            payload["turn_intent"] = "SUPPORT_CLAIM"
            payload["assistant_message"] = str(
                payload.get("assistant_message")
                or "I can help with that order or product issue. Please provide the "
                "order reference and a brief description of what happened."
            )
            payload["message"] = payload["assistant_message"]
            payload.setdefault(
                "next_questions",
                [{"id": "order_reference", "label": "Provide order reference"}],
            )
        elif not payload.get("products") and not payload.get("results"):
            bounded_message = str(
                payload.get("message")
                or payload.get("assistant_message")
                or "No matching products were found."
            )
            payload["message"] = bounded_message
            payload["assistant_message"] = bounded_message
            payload.pop("right_panel", None)
        from src.app.security.model_theft import protect_recommendation_output

        return protect_recommendation_output(payload, trace_id=trace_id)
    if outcome.status == "blocked":
        record_recommendation_dispatch(
            outcome="blocked",
            lane=outcome.lane,
            reason=outcome.reason,
        )
        record_recommend_compatibility_request("blocked")
        if outcome.reason.startswith("guard:"):
            # The deprecated GET historically returned a safe 200 response for
            # content-policy refusals. Preserve that transport contract while
            # keeping the V2 guard verdict authoritative and returning no data.
            blocked_payload = {
                "trace_id": trace_id,
                "decision_id": trace_id,
                "decision_trace_id": trace_id,
                "status": "review_required",
                "message": "I can't help with that request.",
                "assistant_message": "I can't help with that request.",
                "products": [],
                "results": [],
                "recommendations": [],
                "next_questions": [],
                "injection_blocked": True,
                "security": {
                    "policy_route": "blocked",
                    "reason": outcome.reason,
                    "checked_boundary": "recommendation_facade",
                },
            }
            _persist_compatibility_outcome(
                trace_id=trace_id,
                tenant_id=tenant_id,
                uid=str(params.get("uid") or ""),
                query=str(params.get("query") or ""),
                status="blocked",
                reason=outcome.reason,
                lane=outcome.lane,
                payload=blocked_payload,
            )
            return blocked_payload
        raise HTTPException(
            status_code=429 if outcome.reason.startswith("quota:") else 403,
            detail={
                "message": "Request blocked by recommendation guard",
                "reason": outcome.reason,
                "trace_id": trace_id,
            },
        )
    record_recommendation_dispatch(
        outcome="v2_unavailable",
        lane=outcome.lane,
        reason=outcome.reason or outcome.status,
    )
    record_recommend_compatibility_request("unavailable")
    unavailable = v2_only_unavailable_response(
        status=outcome.status,
        reason=outcome.reason,
        lane=outcome.lane,
        trace_id=trace_id,
    )
    unavailable.setdefault("products", [])
    unavailable.setdefault("results", [])
    unavailable.setdefault("recommendations", [])
    unavailable.setdefault(
        "proposal",
        {"decision_mode": "v2_unavailable", "ranked_skus": []},
    )
    unavailable.setdefault("policy_version", "v1")
    unavailable.setdefault("evidence_items", [])
    unavailable.setdefault(
        "evidence_weighting",
        {"retrieval": 0.5, "rules": 0.3, "policy": 0.2},
    )
    unavailable.setdefault("confidence_calibrated", 0.0)
    unavailable.setdefault(
        "counterfactual",
        "Catalog grounding or different constraints could change the recommendation.",
    )
    unavailable["constraints_used"] = dict(compatibility_constraints)
    unavailable["b2b_assessment"] = b2b_assessment.to_dict()
    unavailable["escalation_assessment"] = escalation_assessment.to_dict()
    if escalation_assessment.escalate:
        unavailable["needs_human_review"] = True
    if b2b_assessment.wants_procurement_questions:
        unavailable["next_questions"] = [
            {
                "id": "ask_b2b_procurement",
                "label": "Confirm procurement requirements",
            }
        ]
    if nqe_selection:
        unavailable["nqe_selection_applied"] = nqe_selection
    unavailable.setdefault("decision_id", trace_id)
    _persist_compatibility_outcome(
        trace_id=trace_id,
        tenant_id=tenant_id,
        uid=str(params.get("uid") or ""),
        query=str(params.get("query") or ""),
        status=outcome.status,
        reason=outcome.reason,
        lane=outcome.lane,
        payload=unavailable,
    )
    return unavailable
