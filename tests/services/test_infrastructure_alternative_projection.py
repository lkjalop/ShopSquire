from src.app.services.infrastructure_alternative_projection import (
    project_infrastructure_alternatives,
)


def test_projection_covers_all_architecture_classes_without_selecting_one():
    projection = project_infrastructure_alternatives(
        desired_outcome="Run an OT cyber simulation workload",
        unresolved_inputs=["number of concurrent operators", "offline operation"],
    )

    assert [item.architecture_class for item in projection.alternatives] == [
        "laptop",
        "mobile_workstation",
        "fixed_workstation",
        "server",
        "cloud",
    ]
    assert projection.selected_class is None
    assert projection.selection_authority_granted is False
    assert projection.commercial_authority_granted is False
    assert projection.unresolved_inputs == [
        "number of concurrent operators", "offline operation",
    ]
    assert all(item.qualification_status == "requires_evidence" for item in projection.alternatives)
