"""Case-bound, publisher-governed research planning.

The planner contains no workload enum or provider name.  It projects candidate
research scopes from the governed source manifest and binds them to the buyer's
retained purpose.  Candidate scopes may include sources awaiting policy review;
execution performs a second approval check and can never inherit authority from
this proposal.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.official_source_governance import load_official_source_manifest


_TOKEN = re.compile(r"[a-z0-9]+")
_ACRONYM = re.compile(r"\b(?:[A-Z][A-Z0-9+.-]{1,7}|[0-9]+[A-Z][A-Z0-9+.-]{0,6})\b")
_PROPER_NAME = re.compile(
    r"\b(?:[A-Z][a-z0-9+_-]{2,})(?:\s+(?:[A-Z][A-Za-z0-9+_-]{2,}|"
    r"[0-9]+[A-Z][A-Za-z0-9+_-]*|[0-9]{4}(?:\s*R[0-9])?)){0,3}\b"
)
_NEGATED_CLAUSE = re.compile(
    r"\b(?:i\s+)?(?:do\s+not|don't|does\s+not|doesn't|without|not\s+interested\s+in)\b"
    r"[^.!?;]*(?:[.!?;]|$)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")
# Split a product stem from a digit-leading suffix (Emulate3D -> Emulate 3D)
# while retaining meaningful tokens such as 8K, 3D, H264, and version years.
_LETTER_DIGIT_BOUNDARY = re.compile(r"(?<=[A-Za-z])(?=\d)")
_CURRENCY_AMOUNT = re.compile(
    r"(?ix)"
    r"(?:\b(?:AUD|USD|CAD|NZD|EUR|GBP)\s*[$€£]?|[$€£]\s*)"
    r"\d[\d,]*(?:\.\d+)?\b"
)
_COMMERCIAL_NUMBER = re.compile(
    r"(?ix)\b(?:budget(?:\s+(?:is|of|around|under|over|up\s+to))?|"
    r"spend(?:ing)?(?:\s+(?:around|under|over|up\s+to))?|"
    r"cost(?:ing)?(?:\s+(?:around|under|over|up\s+to))?)\s*"
    r"\d[\d,]*(?:\.\d+)?\b"
)
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "buyer", "current", "do",
    "for", "from", "generic", "hardware", "i", "in", "is", "it", "large",
    "local", "named", "of", "official", "only", "or", "requirements", "scope",
    "software", "system", "the", "to", "use", "with", "work", "workload",
}
_GENERIC_ACTIVATION_PHRASES = {
    "requirement", "system requirement", "hardware requirement",
    "software requirement", "minimum requirement", "recommended requirement",
}
_DISCOVERY_FILLER = _STOP | {
    "acceptable", "actually", "anything", "care", "could", "engineering", "gaming", "good",
    "about", "but", "buy", "can", "could", "edit", "help", "laptop", "looking", "machine", "need",
    "officially", "play", "please", "process", "product", "recommend", "run", "should",
    "something", "supported", "suitable", "team", "thing", "this", "vendor",
    "under", "wants", "what", "which", "will", "would", "our",
}
_PROPER_NAME_FILLER = _DISCOVERY_FILLER | {
    "answer", "check", "compare", "find", "inspect", "look", "maybe", "tell",
}


def _lexical_boundaries(value: str) -> str:
    """Expose CamelCase and letter/digit product boundaries to tokenization."""

    split = _CAMEL_BOUNDARY.sub(" ", str(value or ""))
    return _LETTER_DIGIT_BOUNDARY.sub(" ", split)


def _sanitize_discovery_input(value: str) -> str:
    """Remove transport and commercial data without deleting titles or versions."""

    sanitized = _URL.sub(" ", str(value or ""))
    sanitized = _CURRENCY_AMOUNT.sub(" ", sanitized)
    sanitized = _COMMERCIAL_NUMBER.sub(" ", sanitized)
    return _lexical_boundaries(sanitized)


class CaseResearchHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=2, max_length=200)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    authority: Literal["proposed"] = "proposed"


class CaseAmbiguityObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ambiguity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    ambiguity_type: str = Field(min_length=2, max_length=100)
    subject_span: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=2, max_length=300)
    hypothesis_ids: list[str] = Field(min_length=1, max_length=3)
    resolution_owners: list[
        Literal["catalog", "research", "buyer", "computation", "supplier", "tenant_policy", "human"]
    ] = Field(min_length=1, max_length=4)
    divergent_axes: list[str] = Field(default_factory=list, max_length=8)


class CaseResearchObligation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obligation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    obligation_type: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=2, max_length=300)
    resolution_owner: Literal[
        "catalog", "research", "buyer", "computation", "supplier", "tenant_policy", "human"
    ]
    status: Literal["unresolved", "planned", "resolved", "blocked"] = "unresolved"


class CaseDiscoveryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    axis: Literal["concept_and_software", "requirements_and_compatibility", "support_and_constraints"]
    query: str = Field(min_length=3, max_length=700)
    authority: Literal["discovery_only"] = "discovery_only"


class CaseResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["case-research-plan-v1"] = "case-research-plan-v1"
    plan_id: str = Field(pattern=r"^crp-[a-f0-9]{20}$")
    retained_purpose: str = Field(min_length=3, max_length=500)
    ambiguities: list[CaseAmbiguityObject] = Field(min_length=1, max_length=8)
    hypotheses: list[CaseResearchHypothesis] = Field(min_length=1, max_length=3)
    source_candidate_ids: list[str] = Field(default_factory=list, max_length=16)
    publisher_status: Literal["resolved_enrolled", "unresolved"] = "resolved_enrolled"
    discovery_queries: list[CaseDiscoveryQuery] = Field(default_factory=list, max_length=3)
    obligations: list[CaseResearchObligation] = Field(min_length=1, max_length=16)
    next_question: str = Field(min_length=3, max_length=300)
    external_calls: Literal[0] = 0
    authority: Literal["proposal_only"] = "proposal_only"


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall(str(value or "").lower()) if token not in _STOP}


def _proper_names(value: str) -> tuple[list[str], set[str]]:
    names: list[str] = []
    tokens: set[str] = set()
    for raw_name in _PROPER_NAME.findall(value):
        name = raw_name.strip()
        name_tokens = set(_TOKEN.findall(name.lower()))
        if name.casefold() in _PROPER_NAME_FILLER or name_tokens <= _PROPER_NAME_FILLER or name_tokens <= tokens:
            continue
        names.append(name)
        tokens.update(name_tokens)
    return names, tokens


def _discovery_subject(value: str) -> str:
    """Bound buyer prose to salient terms without classifying a workload."""

    positive_text = _NEGATED_CLAUSE.sub(" ", _sanitize_discovery_input(value))
    proper_names, proper_tokens = _proper_names(positive_text)
    acronyms = [
        item.strip("+.-") for item in _ACRONYM.findall(positive_text)
        if item.strip("+.-").casefold() not in proper_tokens
    ]
    content = [
        token for token in _TOKEN.findall(positive_text.lower())
        if token not in _DISCOVERY_FILLER
        and token not in proper_tokens
        and (len(token) > 2 or any(ch.isdigit() for ch in token))
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for term in [*proper_names, *acronyms, *content]:
        folded = term.casefold()
        if folded not in seen:
            seen.add(folded)
            terms.append(term)
    terms = terms[:8]
    return " ".join(terms) or "buyer described workload"


def _publisher_domain_hypothesis(proper_names: list[str]) -> str | None:
    """Return one low-authority origin hint for a named publisher/product pair.

    This is deliberately only a search constraint. The resulting origin still
    has to survive candidate ranking and explicit case approval before fetch.
    """

    if not proper_names:
        return None
    tokens = _TOKEN.findall(_lexical_boundaries(proper_names[0]).lower())
    if len(tokens) < 2:
        return None
    stem = tokens[0]
    if len(stem) < 4 or stem in _PROPER_NAME_FILLER or not stem.isalpha():
        return None
    return f"{stem}.com"


def _source_terms(source: Mapping[str, Any]) -> set[str]:
    applicability = source.get("applicability") or {}
    values: list[str] = [
        str(source.get("publisher") or ""),
        str(applicability.get("scope") or ""),
        *[str(item).replace("_", " ") for item in applicability.get("workloads") or []],
        *[str(item) for item in source.get("artefact_patterns") or []],
    ]
    return _tokens(" ".join(values))


def _normalized_phrase(value: str) -> str:
    tokens = _TOKEN.findall(_lexical_boundaries(str(value or "").replace("_", " ")).lower())
    return " ".join(token[:-1] if len(token) > 4 and token.endswith("s") else token for token in tokens)


def _source_phrases(source: Mapping[str, Any]) -> set[str]:
    applicability = source.get("applicability") or {}
    activation = source.get("activation_policy") or {}
    return {
        phrase
        for phrase in (
            *[_normalized_phrase(item) for item in applicability.get("workloads") or []],
            *[_normalized_phrase(item) for item in source.get("artefact_patterns") or []],
            *[_normalized_phrase(item) for item in activation.get("provisional_scope_aliases") or []],
        )
        if phrase and phrase not in _GENERIC_ACTIVATION_PHRASES
    }


def _requires_named_application(source: Mapping[str, Any]) -> bool:
    """Whether this publisher can speak only for a named application/framework.

    The source manifest already records this boundary in scope/exclusions.  Enforcing
    it here prevents an adjacent concept (for example photogrammetry) from borrowing
    AutoCAD or Blender requirements merely because both mention large 3D data.
    """

    applicability = source.get("applicability") or {}
    scope = _normalized_phrase(applicability.get("scope") or "")
    exclusions = " ".join(
        _normalized_phrase(item) for item in applicability.get("exclusions") or []
    )
    allowed = {str(item) for item in source.get("allowed_claim_types") or []}
    return bool(
        " named " in f" {scope} "
        or scope.endswith(" only")
        or "other cgi application" in exclusions
        or "other cad application" in exclusions
        or allowed & {"minimum_requirements", "recommended_requirements", "target_requirements"}
    )


def _named_application_hit(source: Mapping[str, Any], normalized_purpose: str) -> bool:
    activation = source.get("activation_policy") or {}
    if activation.get("scope_aliases_are_proposal_grade") is True:
        aliases = {
            _normalized_phrase(value)
            for value in activation.get("provisional_scope_aliases") or []
            if _normalized_phrase(value)
        }
        if any(f" {alias} " in normalized_purpose for alias in aliases):
            return True
    generic = {
        "system requirement", "requirement", "large dataset", "point cloud",
        "large complex model", "bim", "driver", "windows", "manufacturing",
        "predictive maintenance", "model card revision",
    }
    for raw in source.get("artefact_patterns") or []:
        phrase = _normalized_phrase(raw)
        if not phrase or phrase in generic:
            continue
        if f" {phrase} " in normalized_purpose:
            return True
        # Versioned product patterns such as "AutoCAD 2026" also accept the
        # distinctive product name without forcing the buyer to know a version.
        tokens = phrase.split()
        if len(tokens) > 1 and any(ch.isdigit() for ch in tokens[-1]):
            product = " ".join(tokens[:-1])
            if product not in generic and f" {product} " in normalized_purpose:
                return True
    return False


def _candidate_sources_for_purpose(
    retained_purpose: str,
    *,
    manifest: Mapping[str, Any] | None,
    enforce_named_applicability: bool,
) -> tuple[dict[str, Any], ...]:
    purpose_tokens = _tokens(retained_purpose)
    if not purpose_tokens:
        return ()
    normalized_purpose = f" {_normalized_phrase(retained_purpose)} "
    buyer_acronyms = {item.lower().strip("+.-") for item in _ACRONYM.findall(retained_purpose)}
    source_manifest = dict(manifest or load_official_source_manifest())
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for raw in source_manifest.get("sources") or []:
        source = dict(raw)
        activation = source.get("activation_policy") or {}
        required_any_terms = {
            _normalized_phrase(value)
            for value in activation.get("required_any_terms") or []
            if _normalized_phrase(value)
        }
        if required_any_terms and not any(
            f" {term} " in normalized_purpose for term in required_any_terms
        ):
            continue
        phrases = _source_phrases(source)
        exact_phrases = {
            phrase for phrase in phrases
            if f" {phrase} " in normalized_purpose
        }
        acronym_hits = buyer_acronyms & _source_terms(source)
        if not exact_phrases and not acronym_hits:
            continue
        if (
            enforce_named_applicability
            and _requires_named_application(source)
            and not _named_application_hit(source, normalized_purpose)
        ):
            continue
        score = sum(len(phrase.split()) + 2 for phrase in exact_phrases) + 4 * len(acronym_hits)
        ranked.append((-score, str(source.get("source_id") or ""), source))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in ranked[:8])


def candidate_sources_for_purpose(
    retained_purpose: str,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return bounded source-scope candidates without granting execution authority."""

    return _candidate_sources_for_purpose(
        retained_purpose,
        manifest=manifest,
        enforce_named_applicability=True,
    )


def _hypothesis_label(source: Mapping[str, Any]) -> str:
    scope = str((source.get("applicability") or {}).get("scope") or "").strip()
    return scope[:200] or str(source.get("publisher") or "Official workload scope")[:200]


def build_case_research_plan(
    retained_purpose: str,
    *,
    manifest: Mapping[str, Any] | None = None,
    allow_open_world: bool = False,
) -> CaseResearchPlan | None:
    sources = candidate_sources_for_purpose(retained_purpose, manifest=manifest)
    adjacent_sources = _candidate_sources_for_purpose(
        retained_purpose,
        manifest=manifest,
        enforce_named_applicability=False,
    )
    if not sources:
        # A nearby enrolled application is a discovery hint, not authority. Preserve
        # that evidence gap as an open-world plan rather than snapping to its claims.
        if not allow_open_world and not adjacent_sources:
            return None
        purpose = " ".join(str(retained_purpose or "").split())[:500]
        if len(purpose) < 3:
            return None
        hypotheses = [CaseResearchHypothesis(
            hypothesis_id="open_world_workload",
            label="Unresolved workload requiring authoritative source discovery",
            source_ids=[],
        )]
        material = f"{purpose}|open-world-v1"
        discovery_subject = _discovery_subject(purpose)
        proper_names, _ = _proper_names(_NEGATED_CLAUSE.sub(" ", purpose))
        requirements_subject = proper_names[0] if proper_names else discovery_subject
        publisher_domain_hint = _publisher_domain_hypothesis(proper_names)
        support_query = (
            f"site:{publisher_domain_hint} {requirements_subject} documentation requirements"
            if publisher_domain_hint
            else f"{requirements_subject} vendor support certification security"
        )
        return CaseResearchPlan(
            plan_id="crp-" + hashlib.sha256(material.encode()).hexdigest()[:20],
            retained_purpose=purpose,
            ambiguities=[CaseAmbiguityObject(
                ambiguity_id="open_world_scope",
                ambiguity_type="open_world_workload_scope",
                subject_span=purpose[:240],
                description="The requested outcome has no enrolled authoritative publisher scope yet.",
                hypothesis_ids=["open_world_workload"],
                resolution_owners=["research", "tenant_policy", "buyer"],
                divergent_axes=["named_software", "local_execution_scope", "support_or_certification"],
            )],
            hypotheses=hypotheses,
            source_candidate_ids=[],
            publisher_status="unresolved",
            discovery_queries=[
                # Resolve a bounded publisher-origin hypothesis first. Some
                # public engines throttle later requests in a burst; spending
                # the healthiest call on the authority candidate is safer than
                # spending it on broad contextual results.
                CaseDiscoveryQuery(query_id="support", axis="support_and_constraints", query=support_query),
                CaseDiscoveryQuery(query_id="concept", axis="concept_and_software", query=f"{discovery_subject} official documentation"),
                CaseDiscoveryQuery(query_id="requirements", axis="requirements_and_compatibility", query=f"{requirements_subject} system requirements compatibility"),
            ],
            obligations=[
                CaseResearchObligation(
                    obligation_id="publisher_resolution", obligation_type="publisher_discovery",
                    description="Discover a likely authoritative origin without treating search results as evidence.",
                    resolution_owner="research", status="planned",
                ),
                CaseResearchObligation(
                    obligation_id="publisher_approval", obligation_type="publisher_policy",
                    description="Approve a discovered publisher origin before fetching evidence.",
                    resolution_owner="tenant_policy",
                ),
                CaseResearchObligation(
                    obligation_id="exact_product_identity", obligation_type="product_configuration",
                    description="Corroborate exact catalog configurations against accepted claims.",
                    resolution_owner="catalog", status="planned",
                ),
            ],
            next_question=(
                "What project scale or simulation complexity must it handle, and which stages must run locally?"
                if proper_names
                else "Which named software or standard governs this work, and what must run locally?"
            ),
        )
    hypotheses: list[CaseResearchHypothesis] = []
    for index, source in enumerate(sources[:3], 1):
        hypotheses.append(CaseResearchHypothesis(
            hypothesis_id=f"scope_{index}_{str(source['source_id'])[:42].replace('-', '_')}",
            label=_hypothesis_label(source), source_ids=[str(source["source_id"])],
        ))
    pending = any(source.get("review_status") != "approved" for source in sources)
    source_ids = [str(source["source_id"]) for source in sources]
    material = "|".join([retained_purpose.strip(), *source_ids, *[row.hypothesis_id for row in hypotheses]])
    plan_id = "crp-" + hashlib.sha256(material.encode()).hexdigest()[:20]
    obligations = [
        CaseResearchObligation(
            obligation_id="workload_meaning", obligation_type="workload_interpretation",
            description="Resolve which proposed workload scope the buyer intends.",
            resolution_owner="buyer",
        ),
        CaseResearchObligation(
            obligation_id="official_requirements", obligation_type="current_requirements",
            description="Retrieve and normalize applicable official publisher requirements.",
            resolution_owner="research", status="planned",
        ),
        CaseResearchObligation(
            obligation_id="exact_product_identity", obligation_type="product_configuration",
            description="Corroborate exact catalog configurations against accepted claims.",
            resolution_owner="catalog", status="planned",
        ),
    ]
    if pending:
        obligations.append(CaseResearchObligation(
            obligation_id="publisher_approval", obligation_type="publisher_policy",
            description="Approve applicable publisher policies before live execution.",
            resolution_owner="tenant_policy",
        ))
    ambiguity = CaseAmbiguityObject(
        ambiguity_id="workload_scope",
        ambiguity_type="workload_scope",
        subject_span=retained_purpose[:240],
        description="Several governed publisher scopes may materially change product fit.",
        hypothesis_ids=[row.hypothesis_id for row in hypotheses],
        resolution_owners=["buyer", "research", "tenant_policy" if pending else "catalog"],
        divergent_axes=["named_software", "local_execution_scope", "dataset_or_project_scale"],
    )
    return CaseResearchPlan(
        plan_id=plan_id, retained_purpose=retained_purpose[:500],
        ambiguities=[ambiguity], hypotheses=hypotheses,
        source_candidate_ids=source_ids, obligations=obligations,
        publisher_status="resolved_enrolled",
        next_question=(
            "Which named software and version will you use, and which simulation, rendering, "
            "or processing stages must run locally?"
        ),
    )


def approved_sources_for_plan(
    plan: CaseResearchPlan,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    source_manifest = dict(manifest or load_official_source_manifest())
    wanted = set(plan.source_candidate_ids)
    return tuple(
        dict(source) for source in source_manifest.get("sources") or []
        if source.get("source_id") in wanted and source.get("review_status") == "approved"
    )


def plan_hypothesis_labels(plan: CaseResearchPlan) -> dict[str, str]:
    return {row.hypothesis_id: row.label for row in plan.hypotheses}


__all__ = [
    "CaseAmbiguityObject", "CaseDiscoveryQuery", "CaseResearchHypothesis", "CaseResearchObligation",
    "CaseResearchPlan", "approved_sources_for_plan", "build_case_research_plan",
    "candidate_sources_for_purpose", "plan_hypothesis_labels",
]
