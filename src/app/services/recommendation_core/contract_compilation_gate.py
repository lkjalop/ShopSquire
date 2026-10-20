"""Optional contract gate for the existing authoritative compiler.

Contract selection is a server-owned argument, never a field trusted from a
provider response. Passing this gate does not bypass registry compilation.
"""
from datetime import datetime
from typing import Mapping

from src.app.services.requirement_contract import (
    ContractContext, RequirementContract, assess_contract_coverage,
)


def gate_contract_claims(claims: list[Mapping], *, contract: RequirementContract,
                         context: ContractContext | None, now: datetime | None = None):
    normalized = []
    for index, claim in enumerate(claims):
        # Caller-supplied IDs can collide. Local indices bind gate decisions to
        # the exact input row; raw provider authority_status cannot upgrade it.
        normalized.append({**claim, "claim_id": str(index),
            "attribute": claim.get("attribute_key"),
            "authority_status": "verified_official" if (
                claim.get("status") == "accepted" and claim.get("authority") == "official_requirements"
                and context is not None
                and claim.get("artefact_name") == context.subject
                and claim.get("artefact_version") == context.version
            ) else "observed_held"})
    if context is None:
        return {}, {"contract_id": contract.id, "contract_revision": contract.revision,
                    "coverage_complete": False, "failure_code": "contract_context_missing",
                    "fit_authority": "none", "commerce_authority": "none"}
    coverage = assess_contract_coverage(contract, context=context, claims=normalized, now=now)
    eligible = {int(index): row["obligation_id"] for row in coverage["obligations"]
                if row["state"] == "covered" for index in row["accepted_claim_ids"]}
    return eligible, coverage
