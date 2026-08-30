"""Fail-closed coverage checks for open-world workload requests.

A product category match is not evidence that the buyer's stated purpose was understood. This
module detects only a generic product-to-purpose relationship and checks whether accepted,
data-owned use-case vocabulary covers that purpose. It never maps a purpose to a requirement,
product, or SKU.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PURPOSE_PATTERNS = (
    re.compile(r"\bfor\s+(?P<span>[^,.;?!]{2,160})", re.IGNORECASE),
    re.compile(r"\bto\s+(?P<span>[^,.;?!]{2,160})", re.IGNORECASE),
)
_GRAMMAR_WORDS = frozenset({
    "a", "an", "and", "at", "for", "help", "i", "it", "me", "my", "need", "of",
    "play", "please", "run", "that", "the", "this", "to", "with", "want", "use",
    "using", "work",
})
_RESEARCH_META_WORDS = frozenset({
    "approved", "authorize", "authorized", "consent", "official", "permission",
    "research", "search", "source", "sources", "vendor", "vendors",
})


def _tokens(value: Any) -> set[str]:
    out: set[str] = set()
    for token in _TOKEN_RE.findall(str(value or "").lower()):
        if (token in _GRAMMAR_WORDS or len(token) <= 1
                or re.fullmatch(r"\d+(?:fps|hz|k)?", token)):
            continue
        # Taxonomy labels commonly use plurals while buyer turns use singulars.
        # This is lexical normalization only; it creates no domain mapping.
        if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        out.add(token)
    return out


def _registry_vocabulary(value: Any) -> set[str]:
    """Collect human vocabulary from registry data without treating numeric rules as language."""
    if isinstance(value, str):
        return _tokens(value)
    if isinstance(value, Mapping):
        out: set[str] = set()
        for key, child in value.items():
            if str(key) in {"requirements", "budget_band_hint"}:
                continue
            out.update(_tokens(key))
            out.update(_registry_vocabulary(child))
        return out
    if isinstance(value, (list, tuple, set)):
        out: set[str] = set()
        for child in value:
            out.update(_registry_vocabulary(child))
        return out
    return set()


def _purpose_spans(query: str) -> list[str]:
    from src.app.services.clarification_state import request_text_without_research_meta

    request_text = request_text_without_research_meta(query)
    spans: list[str] = []
    for pattern in _PURPOSE_PATTERNS:
        for match in pattern.finditer(request_text):
            span = str(match.group("span") or "").strip()
            span_tokens = _tokens(span)
            if span_tokens and span_tokens <= _RESEARCH_META_WORDS:
                continue
            if re.match(
                r"^(?:that|the|approved|official)\s+(?:research|search|sources?)\b",
                span,
                re.IGNORECASE,
            ):
                continue
            if (span_tokens and any(any(char.isalpha() for char in token) for token in span_tokens)
                    and span not in spans):
                spans.append(span[:160])
    return spans[:3]


def _coverage_sets(
    *, use_cases: Sequence[str], workload_entities: Sequence[Sequence[str]], node_path: str | None,
) -> list[set[str]]:
    covered: list[set[str]] = []
    node_tokens = _tokens(node_path)
    if node_tokens:
        covered.append(node_tokens)
    try:
        from src.app.services.use_case_registry import load_use_cases

        for vertical in ("electronics", "home", "appliances", "furniture", "fashion", "pharmacy"):
            rows = load_use_cases(vertical).get("use_cases") or {}
            # Registry data, rather than a model-selected label, defines vocabulary
            # coverage. A router omission must not make an enrolled workload look novel.
            for key, row in rows.items():
                if not isinstance(row, Mapping):
                    continue
                vocabulary = _registry_vocabulary({key: row})
                if vocabulary:
                    covered.append(vocabulary)
    except Exception:
        pass  # Missing registry data cannot create coverage authority.
    for entity in workload_entities:
        if isinstance(entity, (list, tuple)) and len(entity) >= 2:
            entity_tokens = _tokens(entity[1])
            if entity_tokens:
                covered.append(entity_tokens)
    return covered


def unresolved_purpose_proposal(
    *, query: str, use_cases: Sequence[str] = (),
    workload_entities: Sequence[Sequence[str]] = (), node_path: str | None = None,
    existing_semantic: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an abstention proposal when a material stated purpose lacks coverage."""
    existing = dict(existing_semantic or {})
    if existing.get("validation") == "valid":
        return existing
    spans = _purpose_spans(query)
    if not spans:
        return existing
    coverage_sets = _coverage_sets(
        use_cases=use_cases, workload_entities=workload_entities, node_path=node_path,
    )
    # A familiar request can be covered jointly by the taxonomy ("laptop") and
    # one enrolled use case ("gaming"). Never union unrelated use-case rows:
    # vocabulary from two different profiles must not jointly authorize an
    # unfamiliar purpose.
    node_tokens = _tokens(node_path)
    unresolved: list[str] = []
    for span in spans:
        try:
            from src.app.services.connectors.workload_evidence import default_registry

            if default_registry().recognizes_offline(span):
                continue
        except Exception:
            pass  # Provider failure cannot create coverage authority.
        span_tokens = _tokens(span)
        required = 1 if len(span_tokens) == 1 else min(2, len(span_tokens))
        best_overlap = max(
            (len(span_tokens & (item | node_tokens)) for item in coverage_sets),
            default=len(span_tokens & node_tokens),
        )
        if span_tokens and best_overlap < required:
            unresolved.append(span)
    if not unresolved:
        return existing
    return {
        "validation": "valid",
        "desired_outcome": str(query or "").strip()[:240],
        "product_category_candidates": [],
        "concepts": [
            {
                "text": concept, "query_span": concept, "status": "unresolved",
                "material": True, "interpretations": [],
            }
            for concept in unresolved[:3]
        ],
        # Coverage detection can identify an unsupported purpose span but has no
        # authority to invent domain interpretations. Competing hypotheses are a
        # bounded model proposal and remain empty in this deterministic abstention.
        "workload_hypotheses": [],
        "material_unknowns": [
            {
                "unknown_id": f"purpose-{index + 1}",
                "description": f"Authoritative meaning and requirements for {concept}",
                "resolution_source": "research",
                "material": True,
            }
            for index, concept in enumerate(unresolved[:3])
        ],
        "evidence_questions": [{
            "question_id": "workload_architecture",
            "question": (
                "Should this workload run locally, remotely, or in a hybrid setup, and what "
                "scale or result target must it support?"
            ),
            "purpose": "resolve_performance_target", "material": True,
        }],
        "proposed_action": "research_then_clarify",
        "confidence": 0.25,
        "proposal_origin": "coverage_abstention",
    }


def discard_covered_model_workload_echo(
    *, query: str, use_cases: Sequence[str], workload_entities: list[tuple[str, str]],
    node_path: str | None,
) -> list[tuple[str, str]]:
    """Drop a model-only workload title when enrolled semantics already cover the turn."""
    if not workload_entities:
        return workload_entities
    from src.app.services.recommendation_core.literal_workload_identity import (
        literal_workload_identity_candidate,
    )
    # A title copied from the buyer's current turn is not a model echo.  This
    # used to protect games only, so an equally literal software title such as
    # ``Agisoft Metashape`` was recovered by the router and then silently
    # discarded here.  The subsequent generic taxonomy match produced an
    # OFF_CATALOG answer and left the previous case revision on screen.
    if literal_workload_identity_candidate(query):
        return workload_entities
    unresolved = unresolved_purpose_proposal(
        query=query, use_cases=use_cases, workload_entities=(), node_path=node_path,
    )
    return workload_entities if unresolved else []
