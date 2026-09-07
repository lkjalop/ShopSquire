import pytest

from src.app.services.subject_role import SubjectRole, propose_subject_role, validate_subject_role


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Buy 200 CRM seats under AUD 120k annually", SubjectRole.PROCURE_SUBJECT),
        ("I need 10 laptops with a total budget of AUD 30,000", SubjectRole.PROCURE_SUBJECT),
        ("Antivirus for 500 endpoints at $45/device/year", SubjectRole.PROCURE_SUBJECT),
        ("Buy Photoshop licences for 40 designers", SubjectRole.PROCURE_SUBJECT),
        ("Buy Jira licences for 40 developers", SubjectRole.PROCURE_SUBJECT),
        ("Jira Software subscription for 200 users, budget AUD 90k", SubjectRole.PROCURE_SUBJECT),
        ("A laptop that can run Jira and Confluence smoothly", SubjectRole.RUN_SUBJECT_ON_PRODUCT),
        ("A workstation for Blender under AUD 5k", SubjectRole.UNRESOLVED),
        ("Laptops that can run Photoshop for 40 designers", SubjectRole.RUN_SUBJECT_ON_PRODUCT),
        ("Is Baldur's Gate 3 compatible with this laptop?", SubjectRole.COMPATIBILITY_CHECK),
        ("I process surveys in Agisoft Metashape; what hardware do I need?", SubjectRole.RUN_SUBJECT_ON_PRODUCT),
        ("Rockwell Emulate3D must run locally on this workstation", SubjectRole.RUN_SUBJECT_ON_PRODUCT),
    ],
)
def test_subject_role_matrix(query, expected):
    assert propose_subject_role(query) is expected


def test_for_is_not_itself_workload_authority_without_a_semantic_proposal():
    assert validate_subject_role(
        "ERP for the finance team",
        node_handle="so-1-2-14",
        sold_state=False,
        model_proposal=None,
    ) is SubjectRole.UNRESOLVED


def test_audience_is_not_a_workload_and_validated_role_is_not_overridden_by_for():
    assert propose_subject_role('I need 25 gaming laptops for a training lab') is SubjectRole.PROCURE_SUBJECT
    assert validate_subject_role('A computer chair for my laptop', node_handle=None,
        sold_state=False, model_proposal='PROCURE_SUBJECT') is SubjectRole.PROCURE_SUBJECT
    assert propose_subject_role('A workstation for a design team') is SubjectRole.UNRESOLVED


@pytest.mark.parametrize(
    "query, identity, category, role",
    [
        ("ERP for the finance team, budget AUD 2M", "ERP", "software", "PROCURE_SUBJECT"),
        ("What about a computer chair?", "computer chair", "product", "ADJACENT_PRODUCT"),
        ("AsterCAD for our design team", "AsterCAD", "software", "PROCURE_SUBJECT"),
    ],
)
def test_open_vocabulary_entity_proposals_are_literal_and_role_bounded(
    query, identity, category, role,
):
    from src.app.services.subject_role import validate_entity_frame

    frame = validate_entity_frame(query, {
        "identity": identity,
        "buyer_span": identity,
        "entity_category": category,
        "turn_role": role,
        "confidence": 0.87,
    })
    assert frame.identity == identity
    assert frame.entity_category == category
    assert validate_subject_role(
        query,
        node_handle=None,
        sold_state=None,
        model_proposal=frame.turn_role,
    ).value == role


def test_entity_identity_must_be_a_literal_buyer_span():
    from src.app.services.subject_role import validate_entity_frame

    frame = validate_entity_frame(
        "AsterCAD for our design team",
        {"identity": "Invented Suite", "entity_category": "software", "turn_role": "PROCURE_SUBJECT"},
    )
    assert frame.identity is None
