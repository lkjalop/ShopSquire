"""Data-owned workload boundaries; source text cannot select or relax a contract.

This gate checks coverage, not product fit or commerce permission. Callers supply
the selected context explicitly. Publishers and application names are data.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    subject: str = Field(min_length=1)
    version: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    workload: str = Field(min_length=1)


class RequirementObligation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    attribute: str = Field(min_length=1)
    tier: Literal["minimum", "recommended", "target"]
    source_ids: tuple[str, ...] = Field(min_length=1)
    max_age_hours: int = Field(gt=0)


class RequirementContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    context: ContractContext
    relationship: str | None = Field(default=None, min_length=1, max_length=80)
    obligations: tuple[RequirementObligation, ...] = Field(min_length=1)
    exclusions: tuple[str, ...] = ()
    evidence_notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_obligations(self):
        if len({o.id for o in self.obligations}) != len(self.obligations):
            raise ValueError("duplicate_obligation_id")
        if len({(o.attribute, o.tier) for o in self.obligations}) != len(self.obligations):
            raise ValueError("ambiguous_obligation_attribute_tier")
        return self

    @property
    def revision(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def load_requirement_contract(path: Path) -> RequirementContract:
    # Paths are deployment-selected, never extracted from external documents.
    return RequirementContract.model_validate_json(path.read_text(encoding="utf-8"))


def _fresh(claim: Mapping, *, now: datetime, hours: int) -> bool:
    try:
        observed = datetime.fromisoformat(str(claim["observed_at"]).replace("Z", "+00:00"))
        expires = datetime.fromisoformat(str(claim["expires_at"]).replace("Z", "+00:00")) if claim.get("expires_at") else None
        if observed.tzinfo is None or (expires and expires.tzinfo is None):
            return False
        age = (now - observed).total_seconds()
        return 0 <= age <= hours * 3600 and (expires is None or now < expires)
    except (KeyError, ValueError, TypeError):
        return False


def assess_contract_coverage(contract: RequirementContract, *, context: ContractContext,
                             claims: list[Mapping], now: datetime | None = None) -> dict:
    """No keyword routing, inferred equivalence or source-authored authority.

Claims here must already come from a governed accepted-claim ledger. A matching
string in an external page is not a receipt. Every surviving predicate still
requires registry compilation and independently evidenced product comparison.
"""
    now = now or datetime.now(timezone.utc)
    context_matches = context == contract.context
    rows = []
    for obligation in contract.obligations:
        candidates = [c for c in claims if c.get("attribute") == obligation.attribute
                      and c.get("requirement_class") == obligation.tier]
        accepted, rejected = [], []
        for claim in candidates:
            reasons = []
            if not context_matches or claim.get("applicability") != context.model_dump():
                reasons.append("applicability_unproven_or_mismatched")
            if claim.get("source_id") not in obligation.source_ids:
                reasons.append("source_not_enrolled_for_obligation")
            if claim.get("authority_status") != "verified_official" or claim.get("revoked_at"):
                reasons.append("evidence_not_authorized")
            if not claim.get("source_revision") or not claim.get("source_excerpt") or not claim.get("claim_id"):
                reasons.append("provenance_incomplete")
            if not _fresh(claim, now=now, hours=obligation.max_age_hours):
                reasons.append("evidence_not_current")
            if claim.get("claim_origin", "observed") != "observed":
                reasons.append("derivation_not_authorized")
            if claim.get("value") is None or claim.get("operator") not in {">=", "<=", "=", "equals", "in"}:
                reasons.append("predicate_missing")
            (rejected if reasons else accepted).append(
                {"claim_id": claim.get("claim_id"), "reasons": reasons} if reasons else dict(claim))
        values = {json.dumps([c.get("operator"), c.get("value"), c.get("unit")], sort_keys=True) for c in accepted}
        state = "conflicted" if len(values) > 1 else "covered" if accepted else "missing"
        rows.append({"obligation_id": obligation.id, "attribute": obligation.attribute,
                     "tier": obligation.tier, "state": state,
                     "accepted_claim_ids": [c["claim_id"] for c in accepted], "rejections": rejected})
    return {"contract_id": contract.id, "contract_revision": contract.revision,
            "context": context.model_dump(), "context_matches": context_matches,
            "obligations": rows, "coverage_complete": context_matches and all(r["state"] == "covered" for r in rows),
            "fit_authority": "none", "commerce_authority": "none"}
