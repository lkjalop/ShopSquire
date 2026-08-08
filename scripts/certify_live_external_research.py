"""Certify the real case-plan -> discovery -> official-origin claim pipeline.

This command is intentionally fail-closed.  A reachable SearXNG HTTP endpoint is
not sufficient: required novel discovery must return allowlisted results, every
planned official origin must be reachable, expected scoped claims must compile,
and emitted claims must remain inside the publisher policy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.app.services.case_research_plan import (  # noqa: E402
    approved_sources_for_plan,
    build_case_research_plan,
)
from src.app.services.official_evidence_cache import OfficialEvidenceCache  # noqa: E402
from src.app.services.official_source_governance import (  # noqa: E402
    load_official_source_manifest,
)
from src.app.services.official_workload_research import (  # noqa: E402
    research_official_sources,
)


DiscoveryRequirement = Literal["canonical_allowed", "novel_required"]


class LiveResearchCertificationError(RuntimeError):
    """Raised only for invocation errors; gate failures are written to the artifact."""


def _source_policy_failures(
    research: dict[str, Any], sources: tuple[dict[str, Any], ...],
) -> list[str]:
    by_id = {str(row["source_id"]): row for row in sources}
    failures: list[str] = []
    emitted = [*(research.get("claims") or []), *(research.get("context_claims") or [])]
    for claim in emitted:
        source_id = str(claim.get("source_id") or "")
        claim_type = str(claim.get("claim_type") or "")
        source = by_id.get(source_id)
        if source is None:
            failures.append(f"claim_from_unplanned_source:{source_id or 'unknown'}")
            continue
        forbidden = set(source.get("forbidden_claim_types") or [])
        allowed = set(source.get("allowed_claim_types") or [])
        if claim_type in forbidden:
            failures.append(f"forbidden_claim_emitted:{source_id}:{claim_type}")
        elif claim_type not in allowed:
            failures.append(f"claim_outside_allowed_scope:{source_id}:{claim_type}")
    return failures


def _source_execution(research: dict[str, Any]) -> list[dict[str, Any]]:
    """Project receipt facts without inferring a network call or cache hit."""

    if research.get("source_execution"):
        return list(research["source_execution"])
    discovery = {
        str(row.get("query_id") or ""): row
        for row in research.get("receipts") or []
        if row.get("provider_capability") == "WEB_DISCOVERY"
    }
    origins = {
        str(row.get("query_id") or ""): row
        for row in research.get("receipts") or []
        if row.get("provider_capability") == "OFFICIAL_ORIGIN_FETCH"
    }
    rows: list[dict[str, Any]] = []
    for source_id in research.get("source_ids") or []:
        found = discovery.get(str(source_id), {})
        origin = origins.get(str(source_id), {})
        allowlisted = int(found.get("allowlisted_result_count") or 0)
        cache_status = str(origin.get("cache_status") or "miss")
        if cache_status in {"fresh_hit", "stale_revalidate"}:
            selection = "cache"
        elif allowlisted > 0:
            # The governed pipeline still fetches the reviewed canonical origin;
            # discovery demonstrates findability but never changes authority.
            selection = "canonical_corroborated_by_discovery"
        else:
            selection = "canonical_fallback"
        rows.append({
            "source_id": source_id,
            "discovery_allowlisted_result_count": allowlisted,
            "origin_selection_mode": selection,
            "origin_status": origin.get("execution_status"),
            "origin_url": (origin.get("selected_origin_urls") or [None])[0],
            "cache_status": cache_status,
        })
    return rows


def certify(
    search_url: str,
    retained_purpose: str,
    output: Path,
    *,
    discovery_requirement: DiscoveryRequirement = "novel_required",
    minimum_scoped_claims: int = 1,
    expected_attributes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run the production planning/research functions and evaluate live gates."""

    if minimum_scoped_claims < 0:
        raise LiveResearchCertificationError("minimum_scoped_claims_must_be_non_negative")
    manifest = load_official_source_manifest()
    plan = build_case_research_plan(retained_purpose, manifest=manifest)
    if plan is None:
        raise LiveResearchCertificationError("no_governed_research_plan_for_purpose")
    sources = approved_sources_for_plan(plan, manifest=manifest)
    if not sources:
        raise LiveResearchCertificationError("research_plan_has_no_approved_sources")

    research = research_official_sources(
        retained_purpose,
        search_url_template=search_url,
        sources=sources,
        plan_id=plan.plan_id,
        hypothesis_ids=[row.hypothesis_id for row in plan.hypotheses],
        novel_source_ids=(
            {str(row["source_id"]) for row in sources}
            if discovery_requirement == "novel_required" else set()
        ),
        # A novel-discovery certificate must never pass on process-global cache
        # state left by an earlier canonical fetch.
        evidence_cache=(
            OfficialEvidenceCache()
            if discovery_requirement == "novel_required" else None
        ),
    )
    receipts = list(research.get("receipts") or [])
    discovery_receipts = [
        row for row in receipts if row.get("provider_capability") == "WEB_DISCOVERY"
    ]
    origin_receipts = [
        row for row in receipts if row.get("provider_capability") == "OFFICIAL_ORIGIN_FETCH"
    ]
    accepted = [*(research.get("claims") or []), *(research.get("context_claims") or [])]
    emitted_attributes = {str(row.get("attribute")) for row in research.get("claims") or []}
    failures: list[str] = []
    source_execution = _source_execution(research)
    novel_result_count = sum(
        int(row.get("discovery_result_count") or row.get("discovery_allowlisted_result_count") or 0)
        for row in source_execution
        if row.get("origin_selection_mode") == "discovered_novel"
    )
    if discovery_requirement == "novel_required" and max(
        novel_result_count,
        sum(int(row.get("allowlisted_result_count") or 0) for row in discovery_receipts),
    ) <= 0:
        failures.append("required_novel_discovery_returned_no_allowlisted_results")
    accepted_origin_receipts = [
        row for row in origin_receipts
        if row.get("execution_status") == "completed"
        and (
            row.get("cache_status") == "fresh_hit"
            or (row.get("network_execution") and row.get("external_call_dispatched"))
        )
    ]
    origin_accepted = (
        bool(source_execution)
        and len(accepted_origin_receipts) >= len(source_execution)
        and all(row.get("origin_selection_mode") != "unresolved" for row in source_execution)
    )
    if not origin_accepted:
        failures.append("official_origin_unreachable_or_not_network_executed")
    if len(accepted) < minimum_scoped_claims:
        failures.append(
            f"zero_or_insufficient_expected_scoped_claims:{len(accepted)}<{minimum_scoped_claims}"
        )
    missing_attributes = sorted(set(expected_attributes) - emitted_attributes)
    if missing_attributes:
        failures.append("expected_claim_attributes_missing:" + ",".join(missing_attributes))
    failures.extend(_source_policy_failures(research, sources))
    # A receipt marked live must carry the independent observations enforced by
    # ProviderExecutionReceipt; repeat the visible acceptance check here.
    if any(row.get("fixture") for row in receipts):
        failures.append("non_live_receipt_in_live_certification")
    if discovery_requirement == "novel_required" and any(
        row.get("provider_capability") == "WEB_DISCOVERY"
        and row.get("execution_status") == "completed"
        and (not row.get("network_execution") or not row.get("external_call_dispatched"))
        for row in receipts
    ):
        failures.append("novel_discovery_receipt_not_network_executed")

    artifact: dict[str, Any] = {
        "schema_version": "live-external-research-certification-v2",
        "certification_status": "passed" if not failures else "failed",
        "gate_failures": list(dict.fromkeys(failures)),
        "execution_mode": "live_network",
        "discovery_requirement": discovery_requirement,
        "retained_purpose": retained_purpose,
        "research_plan": plan.model_dump(mode="json"),
        "approved_source_ids": [str(row["source_id"]) for row in sources],
        "source_execution": source_execution,
        "claims": list(research.get("claims") or []),
        "context_claims": list(research.get("context_claims") or []),
        "unresolved": list(research.get("unresolved") or []),
        "receipts": receipts,
        "provider_accounting": dict(research.get("provider_accounting") or {}),
        "paid_calls": int((research.get("provider_accounting") or {}).get("paid_calls") or 0),
        "authority_rule": "discovery finds; source-specific official parser establishes scoped claims",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--search-url",
        default="http://127.0.0.1:8888/search?q={query}&format=json",
    )
    parser.add_argument(
        "--purpose",
        default="I need to simulate a PLC-controlled factory and cyberattacks against the OT network.",
    )
    parser.add_argument(
        "--discovery-requirement",
        choices=("canonical_allowed", "novel_required"),
        default="novel_required",
    )
    parser.add_argument("--minimum-scoped-claims", type=int, default=1)
    parser.add_argument("--expected-attribute", action="append", default=[])
    parser.add_argument(
        "--output", default="tmp/live_external_research_certification.json",
    )
    args = parser.parse_args()
    try:
        artifact = certify(
            args.search_url,
            args.purpose,
            Path(args.output),
            discovery_requirement=args.discovery_requirement,
            minimum_scoped_claims=args.minimum_scoped_claims,
            expected_attributes=tuple(args.expected_attribute),
        )
    except (LiveResearchCertificationError, OSError, ValueError) as exc:
        print(json.dumps({"certification_status": "failed", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(artifact, indent=2))
    return 0 if artifact["certification_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
