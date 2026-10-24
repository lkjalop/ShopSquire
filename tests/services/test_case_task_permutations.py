"""Shopping paraphrases and mixed amendments share the canonical reducer."""

import pytest

from src.app.services.case_task_delivery import case_task_intent, is_case_task_read


STATE = dict(
    requested_quantity=40,
    selected_sku="SKU-1",
    budget=dict(amount_minor=150000, currency="AUD", scope="per_unit"),
)


@pytest.mark.parametrize(
    "query,intent",
    [
        ("Draft an email asking the supplier for the shortfall.", "shortfall_email"),
        ("Prepare a message for our distributor about the missing units.", "shortfall_email"),
        ("Supplier email draft for my current request, please.", "shortfall_email"),
        ("Write an enquiry about the remaining 25 units.", "shortfall_email"),
        ("Give me market intelligence for my current request.", "market_intelligence"),
        ("What is the market outlook for this request?", "market_intelligence"),
        ("Summarise our current quantity and budget.", "case_facts"),
        ("Write an email to reset my password.", None),
        ("Tell me the supermarket opening hours.", None),
    ],
)
def test_product_independent_task_paraphrases(query, intent):
    assert case_task_intent(query) == intent


@pytest.mark.parametrize(
    "query",
    [
        "Draft an email to the supplier with budget AUD 1200 per unit.",
        "Draft a supplier email and deliver to Perth.",
        "Draft an email for the supplier; delivery by Friday.",
        "Market intelligence for my current request, but make it 50 units.",
        "Increase my budget and draft an email for the shortfall.",
        "Draft an email to the supplier and send it now.",
    ],
)
def test_task_read_cannot_swallow_amendments_or_outbound_actions(query):
    assert not is_case_task_read(query, STATE)


@pytest.mark.parametrize(
    "query",
    [
        "Draft an email for the supplier about my current request. Do not send it.",
        "Draft an email for a 25-unit shortfall.",
        "Give me market intelligence for my current request.",
    ],
)
def test_advisory_reads_and_shortage_context_do_not_amend_total_demand(query):
    assert is_case_task_read(query, STATE)
