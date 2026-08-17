"""Persist operational facts and selectively recompute one shopping case.

The observation is append-only and bitemporal: ``known_at`` says when
ShopSquire learned it, while ``effective_at`` says when the fact applies.
No RFQ, cart, payment, or shipment side effect is available from this service.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from src.app.models.orm import ShoppingCaseOperationalObservationRecord
from src.app.services.decision_dependency_graph import (
    load_decision_dependency_edges,
    traverse_decision_dependencies,
)
from src.app.services.procurement_decision_coordinator import (
    invalidations_for_changed_paths,
)
from src.app.services.procurement_decision_run import (
    EvidenceWatermark,
    StageReceipt,
    create_decision_run,
    create_decision_snapshot,
    load_decision_runs,
    persist_decision_run,
)
from src.app.services.shopping_case_revision import advance_material_case_revision
from src.app.services.case_price_intelligence import project_price_baselines
from src.app.services.shopping_case_allocation_projection import project_case_allocation
from src.app.services.shopping_case_commercial_projection import (
    project_case_commercial_decision,
)
from src.app.services.operational_tool_scope import operational_read_receipt
from src.app.services.tool_capability_selector import ToolCapability


ObservationKind = Literal[
    "inventory_quantity", "price", "supplier_lead_time",
    "quote_validity", "supplier_response", "carrier_calendar",
]
SourceType = Literal[
    "inventory_system", "price_feed", "supplier", "carrier_system", "human_admin",
]

_CHANGE = {
    "inventory_quantity": ("fulfilment.inventory", "inventory:current"),
    "price": ("fulfilment.price", "price:current"),
    "supplier_lead_time": ("fulfilment.supplier_lead_time", "delivery:observations"),
    "quote_validity": ("fulfilment.quote_validity", "supplier:offers"),
    "supplier_response": ("fulfilment.supplier_offer", "supplier:offers"),
    "carrier_calendar": ("fulfilment.carrier_calendar", "delivery:observations"),
}

_CAPABILITY = {
    "inventory_quantity": ToolCapability.INVENTORY_AVAILABILITY,
    "price": ToolCapability.FORECAST_OBSERVATION_READ,
    "supplier_lead_time": ToolCapability.SUPPLIER_OFFER_READ,
    "quote_validity": ToolCapability.SUPPLIER_OFFER_READ,
    "supplier_response": ToolCapability.SUPPLIER_OFFER_READ,
    "carrier_calendar": ToolCapability.CARRIER_SERVICE_READ,
}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("operational_observation_time_requires_timezone")
    return parsed.astimezone(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


class OperationalObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=8, max_length=160)
    expected_revision: int = Field(ge=1)
    kind: ObservationKind
    subject_ref: str = Field(min_length=1, max_length=200)
    location_ref: str | None = Field(default=None, max_length=200)
    value: dict[str, Any]
    source_type: SourceType
    evidence_ref: str = Field(min_length=1, max_length=240)
    known_at: str
    effective_at: str

    @model_validator(mode="after")
    def validate_value_shape(self) -> "OperationalObservationInput":
        _utc(self.known_at)
        _utc(self.effective_at)
        required = {
            "inventory_quantity": "quantity",
            "price": "amount_cents",
            "supplier_lead_time": "days",
            "quote_validity": "valid_until",
            "supplier_response": "status",
            "carrier_calendar": "lane_id",
        }[self.kind]
        if required not in self.value:
            raise ValueError(f"{self.kind}_requires_{required}")
        if self.kind in {"inventory_quantity", "price", "supplier_lead_time"}:
            number = self.value[required]
            if not isinstance(number, int) or isinstance(number, bool) or number < 0:
                raise ValueError(f"{required}_requires_nonnegative_integer")
        if self.kind == "price" and not str(self.value.get("currency") or "").strip():
            raise ValueError("price_requires_currency")
        if self.kind == "quote_validity":
            _utc(str(self.value[required]))
        if self.kind == "carrier_calendar":
            for key in ("lead_time_days", "cost_minor_per_unit"):
                if key in self.value:
                    number = self.value[key]
                    if not isinstance(number, int) or isinstance(number, bool) or number < 0:
                        raise ValueError(f"{key}_requires_nonnegative_integer")
            if "lane_available" in self.value and not isinstance(
                self.value["lane_available"], bool,
            ):
                raise ValueError("lane_available_requires_boolean")
        return self


def _receipt(
    *, stage: str, index: int, now: datetime, state_hash: str,
    changed_ref: str, prior_stage_id: str | None, projection: dict[str, Any],
    tool_selection_receipt: dict[str, Any] | None = None,
) -> StageReceipt:
    stage_id = f"stage-observation-{index:02d}-{stage}"
    output = {
        "stage": stage,
        "authority": "deterministic_selective_recomputation",
        "commercial_side_effect": "none",
        "projection": projection,
    }
    return StageReceipt(
        stage=stage,
        stage_id=stage_id,
        status="completed",
        started_at=now.isoformat(),
        completed_at=now.isoformat(),
        input_hash=state_hash,
        output_hash=_digest(output),
        input_artifact_refs=(changed_ref,) if index == 0 else (f"{stage}:input",),
        output_artifact_refs=(f"{stage}:output",),
        dependency_stage_ids=(prior_stage_id,) if prior_stage_id else (),
        tool_selection_receipts=(tool_selection_receipt,) if index == 0 and tool_selection_receipt else (),
    )


def _apply_operational_consequence(
    *, state_data: dict[str, Any], fulfilment: dict[str, Any],
    observation: OperationalObservationInput, facts: list[dict[str, Any]],
    evaluation_time: datetime,
    tenant_price_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute the bounded commercial consequence of the newly observed fact."""

    requested = state_data.get("requested_quantity")
    projection: dict[str, Any] = {"kind": observation.kind}
    if observation.kind == "inventory_quantity":
        available = int(observation.value["quantity"])
        fulfilment["available_now"] = available
        projection.update({"available_now": available})
        if isinstance(requested, int):
            projection.update({
                "requested_quantity": requested,
                "remaining_quantity": max(0, requested - available),
                "quantity_outcome": "enough_now" if available >= requested else "shortfall",
            })
    elif observation.kind == "price":
        amount = int(observation.value["amount_cents"])
        currency = str(observation.value["currency"]).upper()
        fulfilment.update({"unit_price_cents": amount, "currency": currency})
        projection.update({"unit_price_cents": amount, "currency": currency})
        if isinstance(requested, int):
            projection["total_price_cents"] = amount * requested
    elif observation.kind == "supplier_lead_time":
        days = int(observation.value["days"])
        fulfilment["supplier_lead_time_days"] = days
        projection["supplier_lead_time_days"] = days
    elif observation.kind == "quote_validity":
        valid_until = str(observation.value["valid_until"])
        fulfilment["quote_valid_until"] = valid_until
        projection["quote_valid_until"] = valid_until
    elif observation.kind == "supplier_response":
        response_status = str(observation.value["status"])
        fulfilment["supplier_response_status"] = response_status
        projection["supplier_response_status"] = response_status
    else:
        fulfilment["carrier_calendar_observed"] = True
        projection["carrier_calendar"] = dict(observation.value)
    if observation.kind in {
        "inventory_quantity", "supplier_lead_time", "supplier_response", "carrier_calendar",
    }:
        allocation = project_case_allocation(state_data=state_data, observations=facts)
        fulfilment["allocation_projection"] = allocation
        projection["allocation"] = allocation
    if observation.kind == "price":
        price_intelligence = project_price_baselines(tenant_price_facts or facts)
        price_intelligence["history_scope"] = "tenant_subject_cutoff_safe"
        fulfilment["price_intelligence"] = price_intelligence
        projection["price_intelligence"] = price_intelligence
    commercial = project_case_commercial_decision(
        state_data=state_data, fulfilment=fulfilment, evaluation_time=evaluation_time,
    )
    fulfilment["commercial_decision"] = commercial
    projection["commercial_decision"] = commercial
    fulfilment["operational_projection"] = projection
    return projection


def record_case_operational_observation(
    db: Any,
    *,
    tenant_id: str,
    case_id: str,
    retained_purpose: str,
    observation: OperationalObservationInput,
) -> dict[str, Any]:
    existing = db.execute(select(ShoppingCaseOperationalObservationRecord).where(
        ShoppingCaseOperationalObservationRecord.tenant_id == tenant_id,
        ShoppingCaseOperationalObservationRecord.observation_id == observation.observation_id,
    )).scalar_one_or_none()
    if existing is not None:
        return {
            "observation_id": existing.observation_id,
            "case_id": existing.case_id,
            "case_revision": existing.case_revision,
            "decision_run_id": existing.decision_run_id,
            "idempotent_replay": True,
            "commercial_authority_granted": False,
        }

    prior_runs = load_decision_runs(db, tenant_id=tenant_id, case_id=case_id)
    if not prior_runs:
        raise ValueError("decision_run_required_before_operational_observation")
    prior = prior_runs[-1]
    if prior.snapshot.case_revision != observation.expected_revision:
        raise ValueError(f"case_revision_conflict:{prior.snapshot.case_revision}")

    changed_path, changed_ref = _CHANGE[observation.kind]
    prior_edges = load_decision_dependency_edges(
        db, tenant_id=tenant_id, case_id=case_id, run_id=prior.run_id,
    )
    traversal = traverse_decision_dependencies(
        prior_edges, changed_refs=(changed_ref,),
    )
    invalidations = invalidations_for_changed_paths((changed_path,))
    allowed = invalidations[0].invalidated_stages
    stage_names = {
        receipt.stage_id: receipt.stage for receipt in prior.stage_receipts if receipt.stage_id
    }
    traversed_names = {
        stage_names[stage_id]
        for stage_id in traversal.affected_stage_ids if stage_id in stage_names
    }
    # The persisted dependency graph decides which allowed stages are affected.
    # Older runs may predate dependency edges, so retain an explicit degraded
    # fallback instead of silently doing no work.
    recomputed = tuple(stage for stage in allowed if stage in traversed_names)
    recomputation_basis = "persisted_dependency_edges"
    if not recomputed:
        recomputed = allowed
        recomputation_basis = "typed_invalidation_fallback"

    new_revision = advance_material_case_revision(
        db,
        tenant_id=tenant_id,
        case_id=case_id,
        expected_revision=observation.expected_revision,
        reason=f"operational_observation:{observation.kind}",
    )
    now = datetime.now(timezone.utc)
    known_at = _utc(observation.known_at)
    effective_at = _utc(observation.effective_at)
    row = ShoppingCaseOperationalObservationRecord(
        id=str(uuid.uuid4()),
        observation_id=observation.observation_id,
        tenant_id=tenant_id,
        case_id=case_id,
        case_revision=new_revision,
        kind=observation.kind,
        subject_ref=observation.subject_ref,
        location_ref=observation.location_ref,
        value_json=dict(observation.value),
        source_type=observation.source_type,
        evidence_ref=observation.evidence_ref,
        known_at=known_at,
        effective_at=effective_at,
        created_at=now,
    )
    state_data = prior.snapshot.case_state.model_dump(mode="python")
    fulfilment = dict(state_data.get("fulfilment") or {})
    facts = list(fulfilment.get("operational_observations") or [])
    facts.append({
        "observation_id": observation.observation_id,
        "kind": observation.kind,
        "subject_ref": observation.subject_ref,
        "location_ref": observation.location_ref,
        "value": observation.value,
        "source_type": observation.source_type,
        "evidence_ref": observation.evidence_ref,
        "known_at": known_at.isoformat(),
        "effective_at": effective_at.isoformat(),
    })
    fulfilment["operational_observations"] = facts[-128:]
    fulfilment["latest_operational_observation"] = facts[-1]
    tenant_price_facts: list[dict[str, Any]] | None = None
    if observation.kind == "price":
        history_rows = db.execute(select(
            ShoppingCaseOperationalObservationRecord
        ).where(
            ShoppingCaseOperationalObservationRecord.tenant_id == tenant_id,
            ShoppingCaseOperationalObservationRecord.kind == "price",
            ShoppingCaseOperationalObservationRecord.subject_ref == observation.subject_ref,
            ShoppingCaseOperationalObservationRecord.known_at <= now,
        ).order_by(
            ShoppingCaseOperationalObservationRecord.known_at.asc(),
            ShoppingCaseOperationalObservationRecord.observation_id.asc(),
        ).limit(511)).scalars().all()
        tenant_price_facts = [{
            "observation_id": item.observation_id,
            "kind": item.kind,
            "known_at": item.known_at.isoformat(),
            "value": dict(item.value_json or {}),
            "case_id": item.case_id,
        } for item in history_rows]
        tenant_price_facts.append(facts[-1])
    operational_projection = _apply_operational_consequence(
        state_data=state_data, fulfilment=fulfilment, observation=observation, facts=facts,
        evaluation_time=now,
        tenant_price_facts=tenant_price_facts,
    )
    state_data.update({
        "revision": new_revision,
        "objective": retained_purpose,
        "fulfilment": fulfilment,
    })
    state = prior.snapshot.case_state.model_validate(state_data)
    watermark = EvidenceWatermark(
        source=f"{observation.source_type}:{observation.evidence_ref}",
        observed_at=known_at.isoformat(),
        source_version=observation.observation_id,
        content_hash=_digest({
            "kind": observation.kind,
            "subject_ref": observation.subject_ref,
            "location_ref": observation.location_ref,
            "value": observation.value,
            "effective_at": effective_at.isoformat(),
        }),
        state="current",
    )
    watermarks = tuple(prior.snapshot.evidence_watermarks) + (watermark,)
    tool_receipt = operational_read_receipt(
        capability=_CAPABILITY[observation.kind],
        tenant_id=tenant_id,
        # This route is a governed operator intake seam, not proof that a live
        # WMS/carrier/supplier connector is enrolled.  A real adapter can use
        # the same capability while emitting its own deployment identity.
        deployment_id=f"operator_intake:{observation.source_type}",
        enabled=True,
        freshness_state="fresh",
        health_status="unknown",
        authority_score=70 if observation.source_type != "human_admin" else 60,
    ).model_dump(mode="json")
    snapshot = create_decision_snapshot(
        state,
        tenant_id=tenant_id,
        knowledge_cutoff=now,
        evaluation_time=now,
        evidence_watermarks=watermarks[-128:],
        catalog_snapshot_id=prior.snapshot.catalog_snapshot_id,
        market_snapshot_id=prior.snapshot.market_snapshot_id,
        policy_snapshot_id=prior.snapshot.policy_snapshot_id,
    )
    receipts: list[StageReceipt] = []
    dependency = None
    for index, stage in enumerate(recomputed):
        receipt = _receipt(
            stage=stage,
            index=index,
            now=now,
            state_hash=snapshot.state_hash,
            changed_ref=changed_ref,
            prior_stage_id=dependency,
            projection=operational_projection,
            tool_selection_receipt=tool_receipt,
        )
        receipts.append(receipt)
        dependency = receipt.stage_id
    run = create_decision_run(
        snapshot,
        idempotency_key=f"observation:{observation.observation_id}",
        status="completed",
        stage_receipts=tuple(receipts),
        invalidations=invalidations,
        now=now,
    )
    persist_decision_run(db, run, commit=False)
    row.decision_run_id = run.run_id
    # Add the append-only observation only after the decision run has flushed.
    # Otherwise that flush inserts the still-incomplete row, and assigning its
    # run id afterwards creates a second UPDATE.  Some SQLite certification
    # profiles recreate/adopt this table between sessions, making that update
    # vulnerable to a stale-row result even though the enclosing case CAS is
    # valid.  A single insert with the final linkage is also the clearer
    # append-only transaction shape for PostgreSQL.
    db.add(row)
    db.commit()
    return {
        "observation_id": observation.observation_id,
        "case_id": case_id,
        "case_revision": new_revision,
        "decision_run_id": run.run_id,
        "changed_path": changed_path,
        "changed_ref": changed_ref,
        "recomputed_stages": list(recomputed),
        "recomputation_basis": recomputation_basis,
        "operational_projection": operational_projection,
        "tool_selection_receipt": tool_receipt,
        "ingestion_mode": "operator_submitted_observation",
        "evidence_watermark": watermark.model_dump(mode="json"),
        "dependency_traversal": traversal.model_dump(mode="json"),
        "knowledge_cutoff": snapshot.knowledge_cutoff,
        "evaluation_time": snapshot.evaluation_time,
        "idempotent_replay": False,
        "external_calls": 0,
        "rfq_calls": 0,
        "cart_mutations": 0,
        "commercial_authority_granted": False,
    }


__all__ = ["OperationalObservationInput", "record_case_operational_observation"]
