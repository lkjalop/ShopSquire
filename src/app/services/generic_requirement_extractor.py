"""Provider-neutral requirement extraction with deterministic evidence criticism."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ExtractedOfficialRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute: str = Field(min_length=1, max_length=80)
    operator: Literal[">=", "<=", "equals", "in"]
    value: int | float | str | list[str]
    unit: str | None = Field(default=None, max_length=24)
    requirement_class: Literal["minimum", "recommended", "target", "conditional"]
    condition: str | None = Field(default=None, max_length=400)
    citation_url: HttpUrl
    page_section: str = Field(min_length=1, max_length=240)
    quoted_evidence_span: str = Field(min_length=3, max_length=600)
    observed_at: datetime


class ExtractionCritique(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: list[ExtractedOfficialRequirement] = Field(default_factory=list)
    rejected: list[dict[str, str]] = Field(default_factory=list)


_NUMERIC_PATTERNS = (
    ("ram_gb", re.compile(r"(?P<span>(?P<value>\d{1,4})\s*GB\s+(?:of\s+)?(?:RAM|memory))", re.I)),
    ("gpu_vram_gb", re.compile(r"(?P<span>(?P<value>\d{1,3})\s*GB\s+(?:of\s+)?(?:VRAM|graphics memory))", re.I)),
    ("storage_gb", re.compile(r"(?P<span>(?P<value>\d{1,4})\s*(?P<scale>TB|GB)\s+(?:NVMe|SSD|storage))", re.I)),
    ("cpu_cores", re.compile(r"(?P<span>(?P<value>\d{1,3})\+?\s+(?:physical\s+)?(?:CPU\s+)?cores?)", re.I)),
)

_SECTION_CLASS = re.compile(
    r"\b(minimum|minimal|recommended|basic|advanced|extreme|high)\b", re.I,
)


def _requirement_class(value: str) -> Literal["minimum", "recommended", "target", "conditional"]:
    folded = value.lower()
    if "minimum" in folded or "minimal" in folded or "at least" in folded or "required" in folded:
        return "minimum"
    if "recommended" in folded or "recommend" in folded:
        return "recommended"
    if any(token in folded for token in ("basic", "advanced", "extreme", "high")):
        return "conditional"
    return "conditional" if " if " in f" {folded} " else "target"


def extract_generic_requirements(
    text: str,
    *,
    citation_url: str,
    observed_at: datetime,
    page_section: str = "System requirements",
) -> list[ExtractedOfficialRequirement]:
    """Extract only explicit, nearby numeric requirement statements."""

    rows: list[ExtractedOfficialRequirement] = []
    # HTML table/list boundaries are preserved by the official-origin text
    # adapter. Carry the nearest explicit tier heading into each row so an
    # arbitrary reviewed publisher page can expose minimum/recommended bands
    # without a title-specific parser.
    annotated_lines: list[tuple[str, str]] = []
    active_section = page_section
    for raw_line in str(text or "").splitlines() or [str(text or "")]:
        line = " ".join(raw_line.split())
        if not line:
            continue
        heading = _SECTION_CLASS.search(line)
        if heading and len(line) <= 160:
            active_section = line[:240]
        annotated_lines.append((line, active_section))
    extraction_text = "\n".join(line for line, _section in annotated_lines)
    for attribute, pattern in _NUMERIC_PATTERNS:
        for match in pattern.finditer(extraction_text):
            line_start = extraction_text.rfind("\n", 0, match.start()) + 1
            line_end = extraction_text.find("\n", match.end())
            if line_end < 0:
                line_end = len(extraction_text)
            line = extraction_text[line_start:line_end]
            start = max(line_start, extraction_text.rfind(".", line_start, match.start()) + 1)
            end_marker = extraction_text.find(".", match.end(), line_end)
            end = line_end if end_marker < 0 else end_marker + 1
            span = " ".join(extraction_text[start:end].split())[:600]
            line_index = extraction_text.count("\n", 0, line_start)
            section = annotated_lines[min(line_index, len(annotated_lines) - 1)][1]
            requirement_class = _requirement_class(span)
            if requirement_class == "target":
                requirement_class = _requirement_class(section)
            value = int(match.group("value"))
            if attribute == "storage_gb" and str(match.groupdict().get("scale") or "").upper() == "TB":
                value *= 1000
            rows.append(ExtractedOfficialRequirement(
                attribute=attribute, operator=">=", value=value, unit="GB" if attribute != "cpu_cores" else "cores",
                requirement_class=requirement_class,
                condition=f"Published tier: {section}" if requirement_class == "conditional" else None,
                citation_url=citation_url, page_section=section,
                quoted_evidence_span=span, observed_at=observed_at,
            ))
    return rows


def critique_extracted_requirements(
    claims: list[ExtractedOfficialRequirement],
    *,
    source_text: str,
    accepted_url: str,
    allowed_attributes: set[str] | None = None,
    forbidden_attributes: set[str] | None = None,
) -> ExtractionCritique:
    """Reject uncited, out-of-policy, contradicted, or out-of-scope claims."""

    allowed = set(allowed_attributes or set())
    forbidden = set(forbidden_attributes or set())
    accepted: list[ExtractedOfficialRequirement] = []
    rejected: list[dict[str, str]] = []
    seen: dict[tuple[str, str, str], int | float | str | tuple[str, ...]] = {}
    for claim in claims:
        reason = ""
        value = tuple(claim.value) if isinstance(claim.value, list) else claim.value
        key = (
            claim.attribute,
            claim.requirement_class,
            claim.page_section.casefold() if claim.requirement_class == "conditional" else "",
        )
        if str(claim.citation_url).rstrip("/") != str(accepted_url).rstrip("/"):
            reason = "citation_origin_mismatch"
        elif claim.quoted_evidence_span not in source_text:
            reason = "quoted_span_not_found"
        elif claim.attribute in forbidden:
            reason = "forbidden_attribute"
        elif allowed and claim.attribute not in allowed:
            reason = "attribute_out_of_scope"
        elif key in seen and seen[key] != value:
            reason = "contradictory_claim"
        if reason:
            rejected.append({"attribute": claim.attribute, "reason": reason})
            continue
        seen[key] = value
        accepted.append(claim)
    return ExtractionCritique(accepted=accepted, rejected=rejected)


__all__ = [
    "ExtractedOfficialRequirement", "ExtractionCritique",
    "critique_extracted_requirements", "extract_generic_requirements",
]
