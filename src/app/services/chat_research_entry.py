"""Resolve consent and its displayed policy from one immutable turn snapshot."""
from dataclasses import dataclass
import re
from typing import Any

from src.app.services.clarification_state import external_research_consent_granted
from src.app.services.research_policy import active_research_policy


@dataclass(frozen=True)
class ResearchEntry:
    policy: dict[str, Any]
    explicit_consent: bool
    policy_authorized: bool
    authorized: bool
    basis: str


def literal_research_subject_matches(query: str, retained_purpose: str) -> bool:
    """Associate a bounded literal requirements question; grant no source/fit authority.

    Only an exact token span already in the owned purpose is accepted, including
    version tokens. Other topics, broad pronouns and paraphrases remain unresolved.
    """
    prefix = r'(?:search(?:\s+online)?(?:\s+for)?|check|look\s+up|find|research)\s+(?:the\s+)?(?:official\s+)?'
    patterns = (
        prefix + r'(?P<subject>[^!?;\n]{2,160}?)\s+(?:system\s+|hardware\s+)?requirements[.!?]?\s*',
        prefix + r'(?:system\s+|hardware\s+)?requirements\s+for\s+(?P<subject>[^!?;\n]{2,160}?)[.!?]?\s*',
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, str(query or '').strip(), flags=re.IGNORECASE)
        if not match:
            continue
        subject = re.findall(r'[a-z0-9]+', match.group('subject').lower())
        if not any(len(token) >= 3 and any(c.isalpha() for c in token)
                   and token not in {'the', 'this', 'that', 'current', 'software', 'hardware', 'system', 'our'}
                   for token in subject):
            continue
        purpose = ' ' + ' '.join(re.findall(r'[a-z0-9]+', str(retained_purpose or '').lower())) + ' '
        if ' ' + ' '.join(subject) + ' ' in purpose:
            return True
    return False


def research_entry_authorization(*, payload, submitted_query: str) -> ResearchEntry:
    policy = active_research_policy()
    # JSON strings such as "false" are not affirmative consent.
    explicit = ((payload or {}).get("external_research_consent") is True
                if "external_research_consent" in (payload or {})
                else external_research_consent_granted(submitted_query))
    enabled = bool(policy.get("external_research_enabled"))
    automatic = (enabled and bool(policy.get("auto_authorize_read_only"))
                 and (payload or {}).get("external_research_consent") is not False)
    authorized = enabled and (explicit or automatic)
    return ResearchEntry(policy, explicit, automatic, authorized,
        "buyer_action" if authorized and explicit else "tenant_policy" if automatic else "none")


def build_chat_research_request(*, uid, response_confirmed_slots, _case_research_plan,
                                turn_research_authorization_basis, operation_id,
                                decision_trace_id, data):
    from src.app.routers.shopping_cases import ResearchShoppingCaseRequest
    return ResearchShoppingCaseRequest(
        uid=str(uid or "guest")[:200],
        budget_cents=(
            int(float(response_confirmed_slots.get("budget_max")) * 100)
            if response_confirmed_slots.get("budget_max") is not None else None
        ),
        research_plan_id=_case_research_plan.plan_id,
        ambiguity_object_ids=[
            row.ambiguity_id for row in _case_research_plan.ambiguities
        ],
        hypothesis_ids=[
            row.hypothesis_id for row in _case_research_plan.hypotheses
        ],
        research_authorized=True,
        authorization_basis=turn_research_authorization_basis,
        execution_id=operation_id,
        decision_trace_id=decision_trace_id,
        workload_kind_hints=list(dict.fromkeys(
            str(item.get("kind") or "").strip().lower()
            for item in list(
                (
                    data.get("decision", {}).get("workload_entities")
                    if isinstance(data.get("decision"), dict) else []
                ) or []
            )[:3]
            if isinstance(item, dict)
            and str(item.get("kind") or "").strip().lower()
            in {"game", "software"}
        )),
        unresolved_concepts=(lambda coverage, workloads: (
            [
                str(item.get("query_span") or item.get("text") or "").strip()[:160]
                for item in coverage[:3]
                if isinstance(item, dict)
                and str(item.get("query_span") or item.get("text") or "").strip()
            ]
            or [
                str(item.get("name") or "").strip()[:160]
                for item in workloads[:3]
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
        ))(
            list(
                ((
                    (data.get("decision") or {}).get("coverage_abstention_shadow")
                    if isinstance(data.get("decision"), dict) else {}
                ) or {}).get("concepts") or []
            ),
            list(
                (
                    (data.get("decision") or {}).get("workload_entities")
                    if isinstance(data.get("decision"), dict) else []
                ) or []
            ),
        ),
    )
