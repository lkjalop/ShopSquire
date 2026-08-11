"""Conservative extraction of buyer-supplied hardware requirement evidence.

This module consumes already-extracted text (plain text, PDF text, or OCR).  It
does not grant authority, qualify a product, or mutate conversation/cart state.
Every claim remains buyer-supplied and unverified until a separate acceptance
and corroboration step records otherwise.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field


RequirementClass = Literal["minimum", "recommended", "target", "optimal"]
ConstraintTier = Literal["preferred", "acceptable_alternative"]


class ExtractedRequirementClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    subject: Literal["buyer_workload_requirement"] = "buyer_workload_requirement"
    attribute: Literal[
        "cpu_cores", "hardware_virtualization", "ram_gb", "storage_gb",
        "storage_type", "gpu_vram_gb", "gpu_class", "network_interface",
        "operating_system",
    ]
    operator: Literal[">=", "=", "preferred", "one_of", "conditional"]
    value: int | str | list[str]
    unit: str | None = None
    requirement_class: RequirementClass
    constraint_tier: ConstraintTier = "preferred"
    condition: str | None = None
    source_reference: str
    evidence_class: Literal["buyer_supplied"] = "buyer_supplied"
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    authority_status: Literal["unverified"] = "unverified"
    freshness_status: Literal["unknown"] = "unknown"
    source_excerpt: str = Field(max_length=500)


class ProvisionalRequirementSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["provisional"] = "provisional"
    accepted_claim_ids: list[str]
    claims: list[ExtractedRequirementClaim]
    qualification_authority: Literal["none"] = "none"


_GB = re.compile(r"(?P<value>\d{1,4})\s*(?:gb|gib)\b", re.I)
_TB = re.compile(r"(?P<value>\d{1,2})\s*(?:tb|tib)\b", re.I)
_CORE = re.compile(r"(?P<value>\d{1,3})\s*\+?\s*(?:physical\s+)?cores?\b", re.I)
_VRAM_CONTEXT = re.compile(r"\b(?:vram|gpu\s+memory|video\s+memory)\b", re.I)
_RAM_CONTEXT = re.compile(r"\b(?:system\s+memory|memory\s*\(ram\)|ram)\b", re.I)
_STORAGE_CONTEXT = re.compile(r"\b(?:storage|nvme|ssd)\b", re.I)
_ALT_HEADER = re.compile(r"\b(?:cheaper|acceptable)\s+alternative\b", re.I)


def _claim_id(source_reference: str, attribute: str, excerpt: str, ordinal: int) -> str:
    material = f"{source_reference}|{attribute}|{excerpt}|{ordinal}"
    return "buyer-claim-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _class_for(text: str, *, default: RequirementClass = "target") -> RequirementClass:
    lowered = text.lower()
    if "minimum" in lowered or "at least" in lowered or "must" in lowered:
        return "minimum"
    if "strongly recommended" in lowered or "recommended" in lowered or "preferred" in lowered:
        return "recommended"
    if "optimal" in lowered:
        return "optimal"
    return default


def extract_buyer_requirement_claims(
    text: str,
    *,
    source_reference: str,
    extraction_confidence: float = 0.75,
) -> list[ExtractedRequirementClaim]:
    """Extract explicit hardware claims without promoting them to authority.

    The parser intentionally understands a small unit-safe vocabulary. Unknown
    prose is retained outside this contract for later model-assisted proposal;
    it is never guessed into a numeric requirement here.
    """
    confidence = max(0.0, min(float(extraction_confidence), 1.0))
    tier: ConstraintTier = "preferred"
    claims: list[ExtractedRequirementClaim] = []

    def add(
        attribute: str,
        operator: str,
        value: int | str | list[str],
        excerpt: str,
        *,
        unit: str | None = None,
        requirement_class: RequirementClass | None = None,
        condition: str | None = None,
    ) -> None:
        claims.append(ExtractedRequirementClaim(
            claim_id=_claim_id(source_reference, attribute, excerpt, len(claims)),
            attribute=attribute,
            operator=operator,
            value=value,
            unit=unit,
            requirement_class=requirement_class or _class_for(excerpt),
            constraint_tier=tier,
            condition=condition,
            source_reference=source_reference,
            extraction_confidence=confidence,
            source_excerpt=excerpt[:500],
        ))

    # OCR engines often flatten a multi-section screenshot into one long line.
    # Restore only explicit hardware section boundaries; this is layout recovery,
    # not workload inference, and keeps the reducer vertical-agnostic.
    normalized_text = re.sub(
        r"\s+(?=(?:processor\s*\(cpu\)|memory\s*\(ram\)|storage|"
        r"graphics\s*\(gpu\)|networking|os\s+setup|"
        r"cheaper\s+alternative|acceptable\s+alternative)\s*[:\-])",
        "\n",
        str(text or ""),
        flags=re.I,
    )
    # Manual entry commonly uses compact comma/semicolon-separated clauses
    # ("RAM 32GB; storage 1TB NVMe; Windows 11 Pro"). Split only when the
    # following clause starts with a known capability label. This preserves
    # prose punctuation while allowing every explicit claim family to be read.
    normalized_text = re.sub(
        r"\s*;\s*(?=(?:(?:processor|cpu|memory|ram|storage|graphics|gpu|"
        r"networking|os\s+setup|windows\s+11)\b|\d+\s*(?:tb|tib)\b"
        r"(?=[^;\n]*(?:storage|nvme|ssd))))",
        "\n",
        normalized_text,
        flags=re.I,
    )
    normalized_text = re.sub(
        r"\s*,\s*(?=(?:processor\b|cpu\b|memory\b|ram\b|storage\b|"
        r"graphics\b|gpu\b|networking\b|os\s+setup\b|windows\s+11\b))",
        "\n",
        normalized_text,
        flags=re.I,
    )
    for raw_line in normalized_text.splitlines():
        line = re.sub(r"^[\s*•\-]+", "", raw_line).strip()
        if not line:
            continue
        if _ALT_HEADER.search(line):
            tier = "acceptable_alternative"
            continue
        lowered = line.lower()
        condition = None
        if " if " in f" {lowered} ":
            condition = line[line.lower().find("if "):].strip() or None

        # VRAM must be recognized before generic RAM; "32 GB RAM" can never
        # become a GPU-memory claim.
        if _VRAM_CONTEXT.search(line):
            for match in _GB.finditer(line):
                add("gpu_vram_gb", ">=", int(match.group("value")), line,
                    unit="GB", condition=condition)
            continue
        if _RAM_CONTEXT.search(line):
            values = [int(match.group("value")) for match in _GB.finditer(line)]
            for index, value in enumerate(values):
                req_class: RequirementClass = (
                    "minimum" if index == 0 and "minimum" in lowered
                    else "recommended" if index > 0 and "recommend" in lowered
                    else _class_for(line)
                )
                add("ram_gb", ">=", value, line, unit="GB", requirement_class=req_class)
            continue
        if _STORAGE_CONTEXT.search(line):
            values_gb = [int(match.group("value")) for match in _GB.finditer(line)]
            values_gb.extend(int(match.group("value")) * 1000 for match in _TB.finditer(line))
            for index, value in enumerate(values_gb):
                add(
                    "storage_gb", ">=", value, line, unit="GB",
                    requirement_class="minimum" if index == 0 else "recommended",
                )
            if "nvme" in lowered:
                add("storage_type", "=", "NVMe SSD", line,
                    requirement_class=_class_for(line))
            elif "ssd" in lowered:
                add("storage_type", "=", "SSD", line,
                    requirement_class=_class_for(line))
            continue

        if "virtualization" in lowered or "virtualisation" in lowered:
            add("hardware_virtualization", "=", "required", line,
                requirement_class="minimum")
        core = _CORE.search(line)
        if core:
            add("cpu_cores", ">=", int(core.group("value")), line, unit="cores")
        if re.search(r"\bwindows\s+11\s+pro(?:fessional)?\b", line, re.I):
            # A screenshot saying "OS setup" or "recommended" is not enough
            # to silently convert the edition into a mandatory constraint.
            add("operating_system", "preferred", "Windows 11 Pro", line,
                requirement_class=_class_for(line, default="recommended"))
        if re.search(r"\b(?:dedicated\s+)?nvidia\s+gpu\b|\brtx\s+(?:series|pro)\b", line, re.I):
            add("gpu_class", "conditional" if condition else "preferred", "NVIDIA RTX", line,
                requirement_class="recommended", condition=condition)
        if re.search(r"\b(?:rj-?45|gigabit\s+ethernet)\b", line, re.I):
            add("network_interface", "one_of", ["RJ45", "Gigabit Ethernet adapter"], line,
                requirement_class=_class_for(line, default="recommended"), condition=condition)
    deduplicated: list[ExtractedRequirementClaim] = []
    seen: set[tuple[object, ...]] = set()
    for claim in claims:
        value_key = tuple(claim.value) if isinstance(claim.value, list) else claim.value
        signature = (
            claim.attribute, claim.operator, value_key, claim.unit,
            claim.requirement_class, claim.constraint_tier, claim.condition,
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduplicated.append(claim)
    return deduplicated


def accept_provisional_requirements(
    claims: Sequence[ExtractedRequirementClaim], *, accepted_claim_ids: Sequence[str],
) -> ProvisionalRequirementSet:
    """Return an explicit buyer-reviewed subset, still without fit authority."""
    accepted = set(accepted_claim_ids)
    selected = [claim for claim in claims if claim.claim_id in accepted]
    return ProvisionalRequirementSet(
        accepted_claim_ids=[claim.claim_id for claim in selected],
        claims=selected,
    )
