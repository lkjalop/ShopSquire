"""Shadow-only LLM renderer for canonical workload decisions.

The candidate is never buyer-authoritative and never replaces deterministic copy.
This module exists so models can be measured against the same bounded object before
any cohort is allowed to see their prose.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Mapping


_NUM_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")
_FLOOR_LANGUAGE_RE = re.compile(
    r"\b(?:need(?:s|ed)?|require(?:s|d)?|minimum|at\s+least|must\s+have|recommended?)\b",
    re.IGNORECASE,
)
_BEHAVIORAL_PROMISE_RE = re.compile(
    r"\b(?:expect|achieve|deliver|run(?:s)?\s+at|smooth|fps|frames?\s+per\s+second|"
    r"tokens?\s+per\s+second|benchmark\s+(?:score|result)|training\s+(?:takes|time))\b",
    re.IGNORECASE,
)
_WINDOWS_PRO_ADVICE_RE = re.compile(
    r"\b(?:upgrade\s+to|use|choose|need(?:s)?|require(?:s|d)?|recommend(?:ed)?)\s+"
    r"windows(?:\s+11)?\s+pro\b",
    re.IGNORECASE,
)


def _candidate_mentions_row(candidate_lower: str, row: Mapping[str, Any]) -> bool:
    """Conservative matching for decision-material hardware dimensions.

    Labels are preferred; the aliases cover the small set whose canonical keys
    differ substantially from buyer-facing prose.  This does not try to infer a
    requirement: it only decides whether prose made a claim about a ledger row.
    """
    key = str(row.get("attribute_key") or "").strip().lower()
    label = str(row.get("attribute_label") or "").strip().lower()
    aliases = {
        "ram_gb": ("ram", "memory"),
        "gpu_vram_gb": ("vram", "gpu memory", "graphics memory"),
        "storage_gb": ("storage", "ssd", "nvme"),
        "cpu_cores": ("cpu", "processor", "cores"),
        "gpu_tgp_w": ("gpu power", "tgp", "power limit"),
        "os_edition": ("operating system", "os edition", "windows"),
    }.get(key, ())
    terms = tuple(term for term in (label, key.replace("_", " "), *aliases) if len(term) >= 3)
    return any(term in candidate_lower for term in terms)


def build_shadow_prompt(decision: Mapping[str, Any]) -> str:
    bounded = {
        "schema_version": decision.get("schema_version"),
        "workload": decision.get("workload"),
        "product": decision.get("product"),
        "overall_decision": decision.get("overall_decision"),
        "compatibility_status": decision.get("compatibility_status"),
        "performance_status": decision.get("performance_status"),
        "scale_status": decision.get("scale_status"),
        "qualification_scope": decision.get("qualification_scope"),
        "budget_status": decision.get("budget_status"),
        "availability_status": decision.get("availability_status"),
        "authorized_narration_blocks": list(decision.get("authorized_narration_blocks") or [])[:12],
        "fit_ledger": list(decision.get("fit_ledger") or [])[:32],
        "critic": decision.get("critic"),
    }
    return (
        "Render a concise shopping explanation from this authorized decision JSON only. "
        "Do not add facts, prices, requirements, performance promises, or product identities. "
        "State material unknowns. Never say qualified if the decision is conditional, unresolved, "
        "or not qualified. Return prose only.\nDECISION_JSON:\n"
        + json.dumps(bounded, sort_keys=True, ensure_ascii=False, default=str)
    )


def validate_shadow_narration(text: str, decision: Mapping[str, Any]) -> list[str]:
    candidate = str(text or "").strip()
    if not candidate:
        return ["empty_candidate"]
    violations: list[str] = []
    low = candidate.lower()
    overall = str(decision.get("overall_decision") or "unresolved")
    if overall not in {"qualified_for_stated_scope", "over_spec_for_stated_scope"}:
        if any(term in low for term in (
            "good choice", "great choice", "great for", "ideal for", "perfect for",
            "fully qualified", "is qualified", "will handle",
        )):
            violations.append("decision_overstatement")
    unknowns = list(((decision.get("workload") or {}).get("material_unknowns") or []))
    unknowns.extend(
        str(row.get("attribute_label") or row.get("attribute_key") or "")
        for row in list(decision.get("fit_ledger") or [])
        if str(row.get("verdict")) in {"unknown", "contested"}
    )
    if any(str(item).strip() for item in unknowns):
        if not any(term in low for term in ("unknown", "unresolved", "still need", "not verified", "cannot confirm")):
            violations.append("material_unknowns_omitted")
    allowed_numbers = set(_NUM_RE.findall(json.dumps(decision, default=str)))
    for number in _NUM_RE.findall(candidate):
        if number not in allowed_numbers:
            violations.append(f"unreferenced_numeric_claim:{number}")
    rows = list(decision.get("fit_ledger") or [])
    if _FLOOR_LANGUAGE_RE.search(candidate):
        for row in rows:
            if not _candidate_mentions_row(low, row):
                continue
            if not list(row.get("requirement_claim_ids") or []):
                key = str(row.get("attribute_key") or "unknown")
                violations.append(f"unsourced_hardware_floor:{key}")
    # ``performance_status=verified`` proves that exact behavioral evidence
    # exists; it does not authorize the narrator to invent a score, frame rate,
    # duration, or qualitative result.  Specific behavioral prose will only be
    # allowed once a verbatim-safe behavioral result is carried in an authorized
    # block.  Until then the honest statement is simply that performance was or
    # was not verified.
    if _BEHAVIORAL_PROMISE_RE.search(candidate):
        violations.append("behavioral_claim_without_exact_evidence")
    if _WINDOWS_PRO_ADVICE_RE.search(candidate):
        os_rows = [
            row for row in rows
            if str(row.get("attribute_key") or "") in {"os", "os_edition", "operating_system"}
        ]
        has_sourced_pro_requirement = any(
            list(row.get("requirement_claim_ids") or [])
            and "windows" in str(row.get("required_text") or "").lower()
            and "pro" in str(row.get("required_text") or "").lower()
            for row in os_rows
        )
        if not has_sourced_pro_requirement:
            violations.append("windows_pro_advice_without_requirement_reference")
    if str(decision.get("budget_status") or "unknown") == "over":
        if not any(term in low for term in ("over budget", "over the budget", "budget ceiling", "budget conflict")):
            violations.append("budget_conflict_omitted")
    for row in rows:
        if str(row.get("verdict") or "") not in {"unknown", "contested"}:
            continue
        if not _candidate_mentions_row(low, row):
            key = str(row.get("attribute_key") or "unknown")
            violations.append(f"ledger_gap_omitted:{key}")
    if str(((decision.get("critic") or {}).get("status") or "")) == "blocked":
        if "critic" not in low and "evidence" not in low and "cannot" not in low:
            violations.append("critic_block_omitted")
    return list(dict.fromkeys(violations))[:16]


def run_shadow_narration(
    decision: Mapping[str, Any],
    *,
    generate: Callable[[str], str],
    model_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        candidate = str(generate(build_shadow_prompt(decision)) or "").strip()
        violations = validate_shadow_narration(candidate, decision)
        return {
            "mode": "shadow",
            "model_id": str(model_id),
            "status": "accepted_shadow" if not violations else "rejected_shadow",
            "candidate": candidate if not violations else None,
            "candidate_retained_for_audit": candidate,
            "violations": violations,
            "buyer_visible": False,
            "commercial_authority_granted": False,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {
            "mode": "shadow",
            "model_id": str(model_id),
            "status": "error",
            "candidate": None,
            "violations": [f"generator_error:{type(exc).__name__}"],
            "buyer_visible": False,
            "commercial_authority_granted": False,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
