from src.app.services.recommendation_core.gates import slot_gap_clarify


def test_known_use_case_does_not_get_asked_again_without_hardware_requirements():
    assert slot_gap_clarify(
        has_products=True,
        budget_known=True,
        has_requirements=False,
        has_use_case=True,
    ) is None


def test_missing_use_case_and_requirements_still_clarifies():
    question = slot_gap_clarify(
        has_products=True,
        budget_known=True,
        has_requirements=False,
        has_use_case=False,
    )
    assert question and question["id"] == "ask_use_case"
