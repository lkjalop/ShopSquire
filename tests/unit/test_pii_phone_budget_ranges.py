import pytest

from src.app.deps import PII_PHONE


@pytest.mark.parametrize(
    "text",
    [
        "budget between 900-1300",
        "budget between 900\u20131300",  # en dash
        "range 900 to 1300",
        "$900-$1300",
    ],
)
def test_pii_phone_does_not_match_budget_ranges(text: str):
    assert PII_PHONE.search(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "PayID me $150 on 0450 123 456",
        "+61 450 123 456",
        "Call me on 555-123-4567",
    ],
)
def test_pii_phone_matches_real_phone_like_numbers(text: str):
    assert PII_PHONE.search(text) is not None

