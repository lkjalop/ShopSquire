from src.app.services.recommendation_core.workload_decision import (
    FitLedgerRow,
    ProductConfigurationIdentity,
    WorkloadContract,
    deterministic_narration,
    reduce_workload_decision,
)


def _row(**overrides):
    values = {
        "attribute_key": "ram_gb",
        "attribute_label": "RAM",
        "required": [[">=", 32]],
        "required_text": ">= 32 GB",
        "observed": 32,
        "observed_text": "32 GB",
        "verdict": "meets_minimum",
        "verification_status": "verified",
        "claim_class": "attested",
        "requirement_claim_ids": ["req-1"],
        "capability_claim_ids": ["cap-1"],
        "artefact_name": "GNS3",
        "artefact_version": "3.1",
        "freshness_status": "fresh",
    }
    values.update(overrides)
    return FitLedgerRow(**values)


def _product(**overrides):
    values = {
        "sku": "LAP-1",
        "identifier_type": "manufacturer_part_number",
        "identifier": "83LY001SAU",
        "configuration_hash": "a" * 64,
        "form_factor": "laptop",
    }
    values.update(overrides)
    return ProductConfigurationIdentity(**values)


def test_qualified_requires_named_workload_exact_configuration_and_claims():
    decision = reduce_workload_decision(
        workload=WorkloadContract(
            desired_outcome="small OT lab", artefact_name="GNS3", artefact_version="3.1",
            execution_shape="local", scale_inputs={"nodes": 8},
        ),
        product=_product(), rows=[_row()], budget_status="within",
        availability_status="available",
    )
    assert decision.overall_decision == "qualified_for_stated_scope"
    assert decision.critic.status == "pass"
    assert len(decision.infrastructure_alternatives.alternatives) == 5


def test_ambiguous_workload_cannot_qualify_a_product():
    decision = reduce_workload_decision(
        workload=WorkloadContract(
            desired_outcome="digital twin",
            surviving_hypothesis_ids=["ot-lab", "omniverse"],
            material_unknowns=["Which digital-twin workflow?"],
        ),
        product=_product(), rows=[_row()],
    )
    assert decision.overall_decision == "unresolved"
    assert "unresolved" in deterministic_narration(decision).lower()


def test_unverified_requirement_cannot_fail_product():
    decision = reduce_workload_decision(
        workload=WorkloadContract(artefact_name="GNS3"), product=_product(),
        rows=[_row(observed=16, observed_text="16 GB", verdict="below_minimum",
                   verification_status="unverified")],
    )
    assert decision.critic.status == "blocked"
    assert "unverified_requirement_failed_product:ram_gb" in decision.critic.violations


def test_catalog_only_identity_caps_qualification_at_conditional():
    decision = reduce_workload_decision(
        workload=WorkloadContract(artefact_name="GNS3"),
        product=_product(identifier_type="title", identifier="Gaming Laptop", form_factor="unknown"),
        rows=[_row()],
    )
    assert decision.overall_decision == "conditional"
    assert "qualified_without_exact_product_configuration" in decision.critic.violations


def test_behavioral_evidence_is_separate_from_compatibility():
    decision = reduce_workload_decision(
        workload=WorkloadContract(artefact_name="USD Composer"), product=_product(), rows=[_row()],
        behavioral_evidence=[{"evidence_distance": "near"}],
    )
    assert decision.compatibility_status == "passes"
    assert decision.performance_status == "inferred"


def test_over_spec_needs_explicit_cheaper_complete_match():
    normal = reduce_workload_decision(
        workload=WorkloadContract(artefact_name="GNS3"), product=_product(),
        rows=[_row(verdict="meets_recommended")], budget_status="within",
    )
    over = reduce_workload_decision(
        workload=WorkloadContract(artefact_name="GNS3"), product=_product(),
        rows=[_row(verdict="meets_recommended")], budget_status="within",
        cheaper_complete_match_exists=True,
    )
    assert normal.overall_decision == "qualified_for_stated_scope"
    assert over.overall_decision == "over_spec_for_stated_scope"


def test_authorized_blocks_and_deterministic_copy_name_budget_conflict_and_exact_gaps():
    decision = reduce_workload_decision(
        workload=WorkloadContract(
            desired_outcome="portable model fine-tuning",
            artefact_name="Named trainer",
        ),
        product=_product(),
        rows=[
            _row(
                attribute_key="os_edition", attribute_label="Host OS edition",
                observed=None, observed_text="not recorded", verdict="unknown",
                verification_status="unverified", requirement_claim_ids=["req-os"],
                capability_claim_ids=[],
            ),
            _row(
                attribute_key="gpu_tgp_w", attribute_label="GPU power limit",
                observed=115, observed_text="115 W", verdict="contested",
                requirement_claim_ids=["req-tgp"], capability_claim_ids=["cap-tgp"],
            ),
        ],
        budget_status="over",
    )
    by_name = {block["block"]: block for block in decision.authorized_narration_blocks}
    assert by_name["budget_conflict"]["status"] == "over"
    assert by_name["ledger_gaps"]["items"] == [
        {"attribute_key": "os_edition", "attribute_label": "Host OS edition"},
        {"attribute_key": "gpu_tgp_w", "attribute_label": "GPU power limit"},
    ]
    assert by_name["ledger_gaps"]["claim_refs"] == ["req-os", "req-tgp", "cap-tgp"]

    copy = deterministic_narration(decision)
    assert "exceeds the buyer's budget ceiling" in copy
    assert "Host OS edition" in copy
    assert "GPU power limit" in copy
