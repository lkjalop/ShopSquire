"""A relevant topic label is not a measured ETA or physical-stock observation."""
import pytest

import tests.services.test_market_question_relevance as fixtures

db = fixtures.db


def test_unmet_search_demand_is_not_physical_stock_evidence(db):
    fixtures.seed(db, fixtures.evidence("inventory_demand_mismatch"))
    result = fixtures.context(db, "How many units are currently in stock?")
    assert result["delivery_status"] == "blocked"
    assert result["answered_market_facets"] == []
    assert result["unanswered_market_facets"] == ["stock"]
    assert result["market_evidence"]["citations"] == []


def test_a_current_physical_snapshot_keeps_the_stock_positive(db):
    fixtures.seed(db, fixtures.evidence("inventory_snapshot", magnitude_low=20, magnitude_high=20,
        uom="units", measurement_definition="Current sellable units at the recorded warehouse"))
    result = fixtures.context(db, "How many units are currently in stock?")
    assert result["delivery_status"] == "available"
    assert result["answered_market_facets"] == ["stock"]


@pytest.mark.parametrize("changes", [
    dict(magnitude_low=None, magnitude_high=None),
    dict(magnitude_low=5, magnitude_high=5, uom=None),
    dict(magnitude_low=10, magnitude_high=5),
    dict(magnitude_low=-1, magnitude_high=5),
    dict(magnitude_low=None, magnitude_high=5),
    dict(magnitude_low=5, magnitude_high=5, measurement_definition=None),
    dict(magnitude_low=True, magnitude_high=5),
    dict(magnitude_low="5", magnitude_high=5),
    dict(magnitude_low=float("nan"), magnitude_high=5),
    dict(magnitude_low=5, magnitude_high=float("inf")),
])
def test_eta_needs_a_defined_absolute_measurement_not_only_a_lead_time_label(db, changes):
    evidence = dict(magnitude_low=5, magnitude_high=5, uom="days",
                    measurement_definition="Supplier-quoted elapsed calendar days")
    evidence.update(changes)
    fixtures.seed(db, fixtures.evidence("supplier_lead_time", **evidence))
    result = fixtures.context(db, "What is the supplier ETA for this request?")
    assert result["delivery_status"] == "partial"
    assert result["answered_market_facets"] == []
    assert result["unanswered_market_facets"] == ["lead_time"]
    assert result["market_evidence"]["citations"]


@pytest.mark.parametrize("low,high,uom", [(0, 0, "days"), (3, 5, "days"), (24, 48, "hours")])
def test_defined_current_lead_time_measurements_keep_the_positive(db, low, high, uom):
    fixtures.seed(db, fixtures.evidence("supplier_lead_time", magnitude_low=low, magnitude_high=high,
        uom=uom, measurement_definition="Supplier-quoted elapsed time"))
    result = fixtures.context(db, "What is the supplier ETA for this request?")
    assert result["delivery_status"] == "available"
    assert result["answered_market_facets"] == ["lead_time"]


def test_a_measured_delay_change_does_not_establish_an_absolute_eta(db):
    fixtures.seed(db, fixtures.evidence("lead_time_change", magnitude_low=3, magnitude_high=3,
        uom="days", measurement_definition="Increase relative to an earlier lead-time baseline"))
    result = fixtures.context(db, "What is the supplier ETA for this request?")
    assert result["delivery_status"] == "partial"
    assert result["unanswered_market_facets"] == ["lead_time"]


@pytest.mark.parametrize("query", ["Have supplier lead times changed?", "Are there shipping delays?"])
def test_an_absolute_quote_cannot_establish_a_change_or_a_delay(db, query):
    fixtures.seed(db, fixtures.evidence("supplier_lead_time"))
    result = fixtures.context(db, query)
    assert result["delivery_status"] == "partial"
    assert result["unanswered_market_facets"] == ["lead_time"]


@pytest.mark.parametrize("query,kind,low", [
    ("Have supplier lead times changed?", "lead_time_change", -2),
    ("Are lead times longer?", "lead_time_change", 3),
    ("Are there shipping delays?", "delivery_delay", 2),
])
def test_a_defined_change_or_delay_answers_its_own_question(db, query, kind, low):
    fixtures.seed(db, fixtures.evidence(kind, magnitude_low=low, magnitude_high=low, uom="days",
        measurement_definition="Difference from the recorded prior duration or promised delivery"))
    result = fixtures.context(db, query)
    assert result["delivery_status"] == "available"
    assert result["answered_market_facets"] == ["lead_time"]


def test_combined_eta_and_change_needs_both_measurements(db):
    fixtures.seed(db, fixtures.evidence("lead_time_change", magnitude_low=3, magnitude_high=3,
        uom="days", measurement_definition="Increase from the previous quoted lead time"))
    assert fixtures.context(db, "Have lead times changed and when will these arrive?")["delivery_status"] == "partial"
    fixtures.seed(db, fixtures.evidence("supplier_lead_time"))
    assert fixtures.context(db, "Have lead times changed and when will these arrive?")["delivery_status"] == "available"
