"""Revision-bound terminal projection, shared by chat response surfaces."""
from __future__ import annotations


def project_chat_terminal(*, out, server_research_result, server_research_failure,
                          params_case_patch_idempotency_key, ambiguity_exploration,
                          active_shopping_case_id, decision_trace_id, data, products,
                          effective_turn_facts):
    # Publish one revision-bound terminal read model for every chat exit.  The
    # browser may render progress while this turn runs, but it must install
    # research shelves and trace identity only from this completed contract.
    # Prefer the outcome rebuilt by the atomic case commit.  The research
    # service result is bound to the revision on which network work started;
    # exposing it after the terminal commit produced a nested stale revision.
    # The committed read model contains the same receipts rebound to the one
    # buyer-visible terminal revision.  Only non-persisted turns fall back to
    # the service projection.
    _research_outcome = (
        out.get("research_outcome")
        if isinstance(out.get("research_outcome"), dict) else None
    )
    if not isinstance(_research_outcome, dict):
        _research_outcome = (
            (server_research_result or {}).get("research_outcome")
            if isinstance(server_research_result, dict) else {}
        )
    if isinstance(out.get("server_research_result"), dict) and _research_outcome:
        out["server_research_result"] = {
            **out["server_research_result"],
            "research_outcome": dict(_research_outcome),
        }
    _research_run = (
        (server_research_result or {}).get("research")
        if isinstance(server_research_result, dict) else None
    )
    _research_run_id = (
        str((_research_run or {}).get("run_id") or "").strip() or None
        if isinstance(_research_run, dict) else None
    )
    _operation_id = f"chat:{params_case_patch_idempotency_key}"
    _case_revision = int(out.get("shopping_case_revision") or 1)
    from src.app.services.terminal_research_narration import terminal_research_narration

    out["assistant_message"] = terminal_research_narration(
        research_outcome=_research_outcome,
        current_exploration=ambiguity_exploration,
        subject_role=out.get("subject_role"),
        execution_evidence=(
            data.get("execution_evidence")
            if isinstance(data.get("execution_evidence"), dict) else {}
        ),
        existing_message=str(out.get("assistant_message") or ""),
        product_shelves=out.get('product_shelves'),
        catalog_browse=out.get('semantic_resolution'),
        catalog_product_count=len(products),
    )
    from src.app.services.terminal_qualification import terminal_questions
    out['next_questions'] = terminal_questions(out.get('next_questions'), _research_outcome)
    if isinstance(ambiguity_exploration, dict) and isinstance(ambiguity_exploration.get('next_question'), dict):
        _remaining_questions = terminal_questions([ambiguity_exploration['next_question']], _research_outcome)
        ambiguity_exploration['next_question'] = _remaining_questions[0] if _remaining_questions else None
    out.update({
        "operation_id": _operation_id,
        "case_id": active_shopping_case_id or None,
        "case_revision": _case_revision,
        "research_run_id": _research_run_id,
    })
    from src.app.services.chat_case_continuity import project_retained_facts
    project_retained_facts(out)
    from src.app.services.terminal_research_reconciliation import gate_terminal_catalog_projection
    _terminal_catalog = gate_terminal_catalog_projection(
        research_status=(server_research_result or {}).get("status"),
        products=products, product_shelves=out.get("product_shelves"),
        requirement_completeness=_research_outcome.get("requirement_completeness"),
        catalog_authority=("blocked" if server_research_failure else
            _research_outcome.get("catalog_authority")
            or (out.get("turn_read_model") or {}).get("catalog_authority")),
    )
    if (_terminal_catalog.catalog_authority in {"unknown", "blocked"}
            and (products or ambiguity_exploration
                 or out.get("subject_role") in {"PROCURE_SUBJECT", "COMPATIBILITY_CHECK", "HOST_WORKLOAD"})
            and not _research_outcome.get("identity")
            and not int(_research_outcome.get("accepted_claim_count") or 0)
            and not int(_research_outcome.get("held_claim_count") or 0)
            and not (data.get("execution_evidence") or {}).get("failure_code")):
        out["assistant_message"] = (
            "Product fit and budget suitability remain unresolved. "
            "The workload requirements and exact product configuration still need evidence. "
            "No product has been qualified and no cart or supplier action was authorized."
        )
    if (out.get('case_additive_workload') and not server_research_failure
            and not (data.get('execution_evidence') or {}).get('failure_code')
            and not int(_research_outcome.get('accepted_claim_count') or 0)):
        from src.app.services.additive_workload_projection import hold_prior_slate
        _, out['assistant_message'] = hold_prior_slate(
            out['case_additive_workload'], out.get('confirmed_slots'))
    products = list(_terminal_catalog.products)
    out.update(products=products, product_shelves=_terminal_catalog.product_shelves)
    _terminal_research_resolved = str(
        (server_research_result or {}).get("status") or ""
    ) == "requirements_resolved"
    _terminal_research_status = str(
        (server_research_result or {}).get("status") or ""
    ).strip()
    if not _terminal_research_status and _research_outcome:
        if int(_research_outcome.get("accepted_claim_count") or 0) > 0:
            _terminal_research_status = "requirements_resolved"
            _terminal_research_resolved = True
        elif _research_outcome.get("identity"):
            _terminal_research_status = "identity_resolved_requirements_incomplete"
        elif str(_research_outcome.get("discovery_status") or "") == "degraded":
            _terminal_research_status = "research_degraded"
        else:
            _terminal_research_status = str(
                _research_outcome.get("discovery_status") or "not_applicable"
            )
    if isinstance(ambiguity_exploration, dict):
        exploration_question = ambiguity_exploration.get("next_question")
        if (isinstance(exploration_question, dict)
                and not any(q.get("id") == exploration_question.get("id")
                            for q in out.get("next_questions") or [])):
            out["next_questions"] = list(out.get("next_questions") or []) + [exploration_question]
    out["needs_disambiguation"] = bool(out.get("next_questions"))
    out["right_panel"] = {
        **(out.get("right_panel") or {}), "canonical_budget": out.get("canonical_budget"),
        "retained_buyer_facts": out.get("retained_buyer_facts"),
    }
    if out.get('retained_buyer_facts'):
        from src.app.services.chat_case_continuity import retained_facts_message
        summary=retained_facts_message(out['retained_buyer_facts'])
        if summary and not out['assistant_message'].startswith(summary):
            out['assistant_message']=summary+' '+out['assistant_message']
    committed = out.get("turn_read_model")
    if (isinstance(committed, dict) and committed.get("case_id") == out.get("case_id")
            and committed.get("case_revision") == out.get("case_revision")):
        out["assistant_message"] = str(committed.get("assistant_message") or "")
        out["right_panel"] = dict(committed.get("right_panel") or {})
        products = list(committed.get("products") or [])
        out["products"] = products
    out["terminal_outcome"] = {
        "schema_version": "turn-terminal-outcome-v1",
        "operation_id": _operation_id,
        "decision_trace_id": decision_trace_id,
        "case_id": active_shopping_case_id or None,
        "case_revision": _case_revision,
        "research_run_id": _research_run_id,
        "recommendation_status": _terminal_catalog.recommendation_status,
        "retained_buyer_facts": out.get("retained_buyer_facts"),
        "research_status": _terminal_research_status or str(
            (ambiguity_exploration or {}).get("status") or "not_applicable"
        ),
        "canonical_facts": effective_turn_facts(
            data.get("canonical_facts") or {}, canonical_budget=out.get("canonical_budget"),
            canonical_quantity=(out.get('retained_buyer_facts') or {}).get('requested_quantity'),
            accepted_budget=(out.get('retained_buyer_facts') or {}).get('budget'),
        ),
        "semantic_status": (
            data.get("semantic_status")
            if isinstance(data.get("semantic_status"), dict)
            else {"status": "not_evaluated"}
        ),
        "catalog_authority": _terminal_catalog.catalog_authority,
        "catalog_scope": (
            (out.get("turn_read_model") or {}).get("catalog_scope")
            if isinstance(out.get("turn_read_model"), dict) else None
        ),
        "commerce_authority": str(
            _research_outcome.get("commerce_authority") or "none"
        ),
        "research_outcome": _research_outcome or None,
        "ambiguity_exploration": ambiguity_exploration,
        "products": list(products or []),
        "right_panel": out.get("right_panel"),
        "architecture_alternatives": out.get("architecture_alternatives"),
        "slate_disposition": (
            "clear" if (
                server_research_failure
                or str(_research_outcome.get("catalog_authority") or "") == "blocked"
                or (ambiguity_exploration is not None and not _terminal_research_resolved)
            ) else str(out.get("slate_disposition") or "replace")
        ),
        "next_questions": list(out.get("next_questions") or []),
        "product_shelves": (
            out.get("product_shelves")
            if isinstance(out.get("product_shelves"), dict) else None
        ),
        "assistant_message": str(out.get("assistant_message") or ""),
        "execution_evidence": (
            data.get("execution_evidence")
            if isinstance(data.get("execution_evidence"), dict) else {}
        ),
    }
    from src.app.services.chat_turn_projection import terminal_scope_contract
    scope_contract = terminal_scope_contract(
        scope=out["terminal_outcome"].get("catalog_scope"),
        case_id=out.get("case_id"), case_revision=out.get("case_revision"),
        applicable=(data.get("semantic_status") or {}).get("request_scope")
        not in {"informational", "service_or_place"},
    )
    out.update(scope_contract)
    out["terminal_outcome"].update(scope_contract)
    if isinstance(out.get("right_panel"), dict):
        out["right_panel"].update(scope_contract)
    return products
