from src.app.services.infrastructure_alternative_projection import (
    project_for_unresolved_form_factor,
)


def test_compatibility_turn_projects_mobile_and_fixed_choices_without_selecting_one():
    projection = project_for_unresolved_form_factor(
        subject_role="COMPATIBILITY_CHECK",
        desired_outcome="run a simulation workload",
        constraints={},
        unresolved_inputs=["execution location"],
    )

    assert projection is not None
    classes = {row.architecture_class for row in projection.alternatives}
    assert {"laptop", "mobile_workstation", "fixed_workstation"} <= classes
    assert projection.selection_authority_granted is False
    assert projection.commercial_authority_granted is False


def test_explicit_form_factor_suppresses_architecture_hedge():
    assert project_for_unresolved_form_factor(
        subject_role="RUN_SUBJECT_ON_PRODUCT",
        constraints={"form_factor": "laptop"},
    ) is None


def test_procured_subject_does_not_gain_workload_architecture_choices():
    assert project_for_unresolved_form_factor(
        subject_role="PROCURE_SUBJECT",
        constraints={},
    ) is None


def test_degraded_procured_role_uses_recorded_workload_context_for_safe_hedge():
    projection = project_for_unresolved_form_factor(
        subject_role="PROCURE_SUBJECT",
        constraints={},
        workload_context=True,
    )
    assert projection is not None
    assert projection.selection_authority_granted is False
    assert projection.commercial_authority_granted is False


def test_unresolved_role_uses_recorded_workload_context_for_safe_hedge():
    projection = project_for_unresolved_form_factor(
        subject_role="UNRESOLVED",
        constraints={},
        workload_context=True,
    )
    assert projection is not None
    assert projection.selection_authority_granted is False
