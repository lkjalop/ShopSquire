"""Database-owned case contracts around V2 execution and semantic compilation."""

from src.app.services import case_contract_binding as bindings
from src.app.services.recommendation_core.envelope import CoreResponse


def _scope(envelope):
    anchors = [envelope.session.get(key) for key in ("case_anchor", "procurement_case_state")]
    anchors = [row for row in anchors if isinstance(row, dict) and row.get("case_id")]
    if not anchors:
        return None
    if len({str(row["case_id"]) for row in anchors}) != 1:
        raise ValueError("case_anchor_conflict")
    return dict(tenant_id=envelope.tenant_id, uid=envelope.uid, case_id=str(anchors[0]["case_id"]))


def _read(db, envelope, scope):
    receipt = bindings.read_case_contract_binding(db, **scope)
    if receipt["state"] not in ("current", "unselected"):
        return receipt
    for key in ("case_anchor", "procurement_case_state"):
        anchor = envelope.session.get(key)
        if (
            isinstance(anchor, dict)
            and anchor.get("case_id")
            and anchor.get("revision") is not None
        ):
            if int(anchor["revision"]) != receipt["case_revision"]:
                raise ValueError("case_revision_conflict")
    return receipt


def _held(envelope, receipt, reason, previous=None):
    extras = {
        "requirement_contract": dict(
            receipt or {}, failure_code=reason, fit_authority="none", commerce_authority="none"
        ),
        "semantic_resolution": {"catalog_authority": "blocked", "failure_code": reason},
        "slate_disposition": "clear",
        "commercial_authority_granted": False,
    }
    if previous is not None:
        for key in (
            "degraded_reason",
            "semantic_requirement_compilation",
            "procurement_decision_coordinator",
            "decision", "plan", "workload_authorization", "case_patch_application",
        ):
            if key in previous.extras:
                extras[key] = previous.extras[key]
    # Authoritative hold is deliberately recognized by facade fallback handling.
    return CoreResponse(
        envelope=envelope,
        grounding="grounded",
        message=(
            "I cannot qualify products against the current case requirements yet. "
            "Review the selected scope and its missing evidence before continuing."
        ),
        extras=extras,
        degraded=previous.degraded if previous else False,
        stage_results=list(previous.stage_results) if previous else [],
    ).finalize()


def execute_bound_turn(db, envelope, execute):
    receipt = None
    try:
        scope = _scope(envelope)
        if scope is not None:
            receipt = _read(db, envelope, scope)
            if receipt["state"] not in ("current", "unselected"):
                return _held(envelope, receipt, receipt["state"])
    except ValueError as exc:
        return _held(envelope, receipt, str(exc))
    except Exception:
        return _held(envelope, receipt, "binding_lookup_unavailable")
    if scope is None:
        return execute()
    result = None
    try:
        result = execute()
        bindings.assert_case_contract_unchanged(db, **scope, receipt=receipt)
    except ValueError as exc:
        current = _current_receipt(db, scope, receipt)
        return _held(envelope, current, str(exc), result)
    except Exception as exc:
        from src.app.services.recommendation_core.cancellation import RecommendationCancelled

        reason = (
            f"request_cancelled:{exc}"
            if isinstance(exc, RecommendationCancelled)
            else f"bound_turn_failed:{type(exc).__name__}"
        )
        return _held(envelope, receipt, reason, result)
    if receipt["state"] == "current" and not _read_only_case_result(result):
        coverage = (result.extras.get("semantic_requirement_compilation") or {}).get(
            "contract_coverage"
        ) or {}
        if not (
            coverage.get("compiled_complete") is True
            and coverage.get("contract_revision") == receipt["contract_revision"]
            and coverage.get("contract_id") == receipt["contract_id"]
        ):
            return _held(envelope, receipt, "selected_contract_not_compiled", result)
    result.extras["requirement_contract"] = receipt
    return result


def _read_only_case_result(result):
    """Status/summary can observe a valid case but cannot authorize its products."""
    extras = result.extras
    read_only = (
        result.lane == "PROCUREMENT"
        and not result.products
        and extras.get("case_operation") in ("status", "summary")
        and extras.get("preserve_current_view") is True
        and extras.get("state_changed") is False
        and extras.get("qualification_authority", "none") == "none"
        and not extras.get("commercial_authority_granted")
        and (extras.get("semantic_resolution") or {}).get("catalog_authority") != "permitted"
    )
    if read_only:
        extras["qualification_authority"] = "none"
        extras["commercial_authority_granted"] = False
    return read_only


def _current_receipt(db, scope, previous):
    try:
        return bindings.read_case_contract_binding(db, **scope)
    except Exception:
        # A failed reload must not describe the entry snapshot as still current.
        return dict(previous or {}, state="binding_lookup_unavailable")


def continues_selected_scope_research(db, envelope):
    """Recognize investigation of a literally named, server-owned selected scope.

    Continuity grants no evidence, consent, fit or commerce authority. Revoked
    selections retain their case identity so research can report revocation.
    An explicit replacement or another version must establish a new scope.
    """
    import re
    query = envelope.buyer_query or envelope.query
    if not re.search(r'\b(?:research|search|requirements?|check|sources?)\b', query, re.I):
        return False
    if re.search(r'\b(?:replace|instead|different\s+(?:workload|application)|new\s+search)\b', query, re.I):
        return False
    scope = _scope(envelope)
    if scope is None:
        return False
    receipt = _current_receipt(db, scope, {})
    context = receipt.get('context') or {}
    subject = str(context.get('subject') or '').strip()
    if not subject or not re.search(r'(?<!\w)' + re.escape(subject) + r'(?!\w)', query, re.I):
        return False
    versions = re.findall(r'\b(?:version\s+|v)([\w.-]+)', query, re.I)
    return all(version.casefold().rstrip('.') == str(context.get('version') or '').casefold()
               for version in versions)


def bind_selected_contract_plan(db, plan, envelope):
    """A buyer-selected scope is an evidence obligation, never a fit verdict.

    Preserve an existing material research plan. If the model omitted one, the
    persisted selection supplies the subject to investigate without guessing it
    from product names, workload keywords or source-authored instructions.
    """
    from dataclasses import replace
    scope = _scope(envelope)
    if scope is None or plan.steps == ['handoff_procurement']:
        return plan
    receipt = _read(db, envelope, scope)
    if receipt['state'] != 'current':
        return plan
    contract, context = bindings.require_current_case_contract(db, **scope, binding_id=receipt['binding_id'])
    if not contract.relationship:
        # Older contracts remain constraining but cannot invent a relation.
        return plan
    if plan.needs_concept_resolution and not continues_selected_scope_research(db, envelope):
        return replace(plan,source='selected_case_contract')
    purpose = f'{context.subject} {context.version}: {context.workload}'[:240]
    proposal = dict(desired_outcome=purpose, proposal_origin='persisted',
        concepts=[dict(text=context.subject,query_span=context.subject,status='unresolved',material=True)],
        evidence_questions=[], material_unknowns=[], workload_hypotheses=[],
        proposed_action='research',confidence=1.0,persisted_case_blocker=True)
    return replace(plan,source='selected_case_contract',needs_concept_resolution=True,semantic_proposal=proposal,
                   semantic_authority_state='unresolved')


def project_contract_workloads(items, stage):
    """Join completed governed contract evidence to matching workload identities.

    This does not suppress unrelated workloads or infer a version equivalence.
    The source adapter remains responsible for evidence and the compiler for fit
    predicates. A selected contract alone cannot mark a workload resolved.
    """
    coverage=stage.compilation.contract_coverage or {}
    if (not coverage.get('compiled_complete') or not stage.compilation.requirements
            or stage.semantic_decision.catalog_authority!='permitted'):
        return items
    context=coverage.get('context') or {}
    subject=str(context.get('subject') or '').strip()
    version=str(context.get('version') or '').strip()
    if not subject or not version:return items
    normalize=lambda value:' '.join(str(value).casefold().split())
    names={normalize(subject),normalize(f'{subject} {version}'),normalize(f'{subject} version {version}')}
    requirements=[row.model_dump() for row in stage.compilation.requirements]
    sources=stage.concept_data.get('items') or []
    origin=sources[0].get('url') if sources and isinstance(sources[0],dict) else None
    return [dict(row,status='resolved',canonical_title=subject,resolved_name=subject,
        reason='selected_contract_evidence_compiled',provider_coverage='selected_contract',
        provider_id=requirements[0].get('source_id'),source_record_id=coverage.get('contract_id'),
        source_url=origin,retrieved_at=requirements[0].get('observed_at'),
        requirements_completeness='selected_contract',compiled_requirements=requirements,
        simulation_only=bool(stage.concept_data.get('simulation_only')))
        if normalize(row.get('requested_name')) in names else row for row in items]


def resolve_bound_evidence_stage(db, plan, envelope, decision):
    from src.app.services.recommendation_core.evidence_stage import resolve_semantic_evidence_stage

    scope = _scope(envelope)
    options = {}
    if scope is not None:
        receipt = _read(db, envelope, scope)
        if receipt["state"] != "unselected":
            contract, context = bindings.require_current_case_contract(
                db, **scope, binding_id=receipt["binding_id"]
            )
            options = dict(requirement_contract=contract, contract_context=context)
    return resolve_semantic_evidence_stage(plan, envelope, decision, **options)


def compilation_receipt(compilation):
    """One projection of compiler evidence for API consumers and traces."""
    requirements = [item.model_dump() for item in compilation.requirements]
    return {
        "status": "accepted" if requirements else "blocked",
        "compiled_requirements": requirements,
        "rejected_claims": [dict(item) for item in compilation.rejections],
        "catalog_authority_granted": bool(requirements),
        "commercial_authority_granted": False,
        "contract_coverage": compilation.contract_coverage,
    }


def binding_execution_steps(core):
    receipt = core.extras.get("requirement_contract")
    if not receipt:
        return []
    return [
        dict(
            id="case-contract-binding",
            kind="gate",
            authority="constrains",
            label="Revalidate selected case contract",
            source="case_contract_binding",
            status="blocked" if receipt.get("failure_code") else receipt["state"],
            output=receipt,
        )
    ]
