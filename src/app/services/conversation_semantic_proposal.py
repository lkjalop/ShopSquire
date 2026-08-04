"""Constrained model proposals for dialogue acts; deterministic code remains authoritative."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


DialogueAct = Literal[
    "status",
    "amend_quantity",
    "amend_destination",
    "amend_deadline",
    "amend_warranty",
    "correct_product",
    "clarify",
]


class SemanticReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["case", "product", "order_line"]
    identifier: str = Field(min_length=1, max_length=240)


class SemanticProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialogue_act: DialogueAct
    case_id: str = Field(min_length=1, max_length=240)
    session_epoch: str = Field(min_length=1, max_length=240)
    references: list[SemanticReference] = Field(default_factory=list, max_length=8)
    slot: str | None = Field(default=None, max_length=80)
    value: str | int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=500)


@dataclass(frozen=True)
class ProposalDecision:
    outcome: Literal["accepted", "clarify", "rejected"]
    reason: str
    proposal: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_ACT_SLOT = {
    "amend_quantity": "quantity",
    "amend_destination": "destination",
    "amend_deadline": "deadline",
    "amend_warranty": "warranty",
    "correct_product": "product_sku",
}


def validate_semantic_proposal(
    raw: Any, *, current_state: dict[str, Any]
) -> ProposalDecision:
    """Validate shape and references without mutating conversation or commerce state."""
    try:
        proposal = SemanticProposal.model_validate(raw)
    except ValidationError:
        return ProposalDecision("rejected", "proposal_schema_invalid")

    if proposal.case_id != str(current_state.get("case_id") or ""):
        return ProposalDecision("rejected", "proposal_case_conflict")
    if proposal.session_epoch != str(current_state.get("session_epoch") or ""):
        return ProposalDecision("rejected", "proposal_epoch_conflict")

    known_refs = {
        ("case", str(current_state.get("case_id") or "")),
        ("product", str(current_state.get("product_sku") or "")),
        ("order_line", str(current_state.get("order_line_id") or "")),
    }
    for reference in proposal.references:
        if (reference.kind, reference.identifier) not in known_refs:
            return ProposalDecision("rejected", f"unknown_{reference.kind}_reference")

    expected_slot = _ACT_SLOT.get(proposal.dialogue_act)
    if expected_slot:
        if proposal.slot != expected_slot or proposal.value in (None, ""):
            return ProposalDecision("clarify", "proposal_value_required")
    elif proposal.dialogue_act == "status" and proposal.slot is not None:
        return ProposalDecision("rejected", "status_cannot_amend")

    if proposal.dialogue_act == "correct_product":
        explicit = str(current_state.get("explicit_product_sku") or "")
        if explicit and str(proposal.value) != explicit:
            return ProposalDecision("rejected", "explicit_product_conflict")

    if proposal.confidence < 0.65 or proposal.dialogue_act == "clarify":
        return ProposalDecision("clarify", "proposal_confidence_insufficient")
    return ProposalDecision("accepted", "proposal_consistent", proposal.model_dump())


def propose_dialogue_act(
    *,
    current_state: dict[str, Any],
    model_proposer: Callable[[dict[str, Any]], Any],
) -> ProposalDecision:
    """Call a bounded proposer, then pass its output through the deterministic reducer."""
    model_input = {
        "case_id": str(current_state.get("case_id") or ""),
        "session_epoch": str(current_state.get("session_epoch") or ""),
        "product_sku": str(current_state.get("product_sku") or ""),
        "order_line_id": str(current_state.get("order_line_id") or ""),
        "allowed_dialogue_acts": list(DialogueAct.__args__),
    }
    try:
        raw = model_proposer(model_input)
    except Exception:
        return ProposalDecision("clarify", "semantic_proposer_unavailable")
    return validate_semantic_proposal(raw, current_state=current_state)
