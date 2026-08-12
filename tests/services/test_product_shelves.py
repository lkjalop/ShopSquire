from __future__ import annotations

import pytest

from src.app.services.recommendation_core.product_shelves import (
    AvailabilityProjection,
    ShelfCandidateInput,
    build_product_shelves,
)
from src.app.services.recommendation_core.workload_decision import (
    FitLedgerRow,
    ProductConfigurationIdentity,
    WorkloadContract,
    reduce_workload_decision,
)


def _product(index: int, *, sku: str | None = None, config: str | None = None):
    return ProductConfigurationIdentity(
        sku=sku or f"SKU-{index}",
        identifier_type="manufacturer_part_number",
        identifier=f"MPN-{index}-{config or 'A'}",
        configuration_hash=(config or format(index, "x")).ljust(64, "a"),
        form_factor="laptop",
    )


def _row(*, verdict="meets_minimum", verification="verified"):
    return FitLedgerRow(
        attribute_key="ram_gb",
        attribute_label="RAM",
        required=[[">=", 32]],
        required_text=">= 32 GB",
        observed=32 if verdict != "unknown" else None,
        observed_text="32 GB" if verdict != "unknown" else "not recorded",
        verdict=verdict,
        verification_status=verification,
        claim_class="attested",
        requirement_claim_ids=["req-ram"],
        capability_claim_ids=["cap-ram"] if verdict != "unknown" else [],
        artefact_name="Test Workload",
        freshness_status="fresh",
    )


def _decision(product, *, verdict="meets_minimum", verification="verified"):
    return reduce_workload_decision(
        workload=WorkloadContract(
            desired_outcome="bounded test workload",
            artefact_name="Test Workload",
            artefact_version="1",
        ),
        product=product,
        rows=[_row(verdict=verdict, verification=verification)],
        budget_status="within",
    )


def _candidate(
    index: int,
    *,
    price: int = 100_000,
    score: float | None = None,
    shared=True,
    hypotheses=(),
    product=None,
    available_now: int | None = None,
):
    product = product or _product(index)
    scopes = {}
    if shared is not False:
        scopes["shared"] = _decision(product) if shared is True else shared
    for hypothesis_id, decision in hypotheses:
        scopes[hypothesis_id] = decision
    return ShelfCandidateInput(
        product=product,
        title=f"Product {index}",
        price_cents=price,
        relevance_score=float(20 - index if score is None else score),
        availability=([] if available_now is None else [AvailabilityProjection(
            location_id="network", status="in_stock" if available_now else "sold_out",
            quantity=available_now, freshness_status="fresh",
        )]),
        fit_by_scope=scopes,
    )


def _shelf(projection, shelf_id):
    return next(item for item in projection.shelves if item.shelf_id == shelf_id)


def test_top_three_and_stable_next_five_are_deterministic():
    candidates = [_candidate(index) for index in range(1, 11)]

    first = build_product_shelves(candidates)
    second = build_product_shelves(list(reversed(candidates)))

    first_shelf = _shelf(first, "shared")
    second_shelf = _shelf(second, "shared")
    assert [item.product.sku for item in first_shelf.initial] == [
        "SKU-1", "SKU-2", "SKU-3"
    ]
    assert [item.product.sku for item in first_shelf.next_page] == [
        "SKU-4", "SKU-5", "SKU-6", "SKU-7", "SKU-8"
    ]
    assert first_shelf.remaining_count == 2
    assert second_shelf.model_dump() == first_shelf.model_dump()


def test_shared_and_material_hypothesis_shelves_rank_independently():
    a, b, c = _product(1), _product(2), _product(3)
    candidates = [
        _candidate(1, score=0.8, product=a, hypotheses=(("vm_lab", _decision(a)),)),
        _candidate(2, score=0.9, product=b, hypotheses=(("local_3d", _decision(b)),)),
        _candidate(
            3,
            score=0.7,
            product=c,
            hypotheses=(("vm_lab", None), ("local_3d", _decision(c))),
        ),
    ]

    projection = build_product_shelves(
        candidates,
        hypothesis_ids=["vm_lab", "local_3d"],
        scope_labels={"vm_lab": "VM / network lab", "local_3d": "Local 3D"},
    )

    assert [item.product.sku for item in _shelf(projection, "shared").initial] == [
        "SKU-2", "SKU-1", "SKU-3"
    ]
    assert [item.product.sku for item in _shelf(projection, "vm_lab").initial] == [
        "SKU-1", "SKU-3"
    ]
    assert _shelf(projection, "vm_lab").initial[1].fit_status == "conditional"
    assert [item.product.sku for item in _shelf(projection, "local_3d").initial] == [
        "SKU-2", "SKU-3"
    ]


def test_budget_creates_explicit_within_and_stretch_shelves():
    candidates = [
        _candidate(1, price=200_000, score=0.7),
        _candidate(2, price=250_000, score=0.9),
        _candidate(3, price=250_001, score=1.0),
        _candidate(4, price=400_000, score=0.8),
    ]

    projection = build_product_shelves(candidates, budget_cents=250_000)

    assert [item.product.sku for item in _shelf(
        projection, "shared:within_budget"
    ).initial] == ["SKU-2", "SKU-1"]
    stretch = _shelf(projection, "shared:stretch")
    assert [item.product.sku for item in stretch.initial] == ["SKU-3", "SKU-4"]
    assert stretch.budget_band == "stretch"
    assert all(item.price_cents > 250_000 for item in stretch.initial)
    assert all(item.commercial_decision.status == "OVER_BUDGET" for item in stretch.initial)
    assert all(item.commercial_decision.budget_outcome == "within" for item in _shelf(
        projection, "shared:within_budget"
    ).initial)


def test_no_budget_uses_relevance_before_price():
    projection = build_product_shelves(
        [
            _candidate(1, price=100_000, score=0.5),
            _candidate(2, price=500_000, score=0.9),
        ]
    )
    assert [item.product.sku for item in _shelf(projection, "shared").initial] == [
        "SKU-2", "SKU-1"
    ]


def test_quantity_fit_is_visible_without_displacing_the_better_workload_fit():
    projection = build_product_shelves(
        [
            _candidate(1, score=0.95, available_now=3),
            _candidate(2, score=0.80, available_now=30),
            _candidate(3, score=0.70, available_now=0),
        ],
        requested_quantity=30,
    )
    products = _shelf(projection, "shared").initial

    assert [item.product.sku for item in products] == ["SKU-1", "SKU-2", "SKU-3"]
    assert products[0].quantity_fit == "partial"
    assert products[0].available_now == 3
    assert products[0].shortfall == 27
    assert products[1].quantity_fit == "enough_now"
    assert products[2].quantity_fit == "unavailable"
    assert products[0].commercial_decision.status == "QUALIFIED_PARTIAL"
    assert products[1].commercial_decision.status == "QUALIFIED_NOW"

    deadline_products = _shelf(
        projection, "shared:available_by_deadline"
    ).initial
    assert [item.product.sku for item in deadline_products] == [
        "SKU-2", "SKU-1", "SKU-3",
    ]
    assert _shelf(
        projection, "shared:available_by_deadline"
    ).decision_view == "available_by_deadline"


def test_high_value_review_adds_cheaper_shelf_without_hiding_technical_winner():
    projection = build_product_shelves(
        [
            _candidate(1, price=600_000, score=1.0, available_now=3),
            _candidate(2, price=450_000, score=0.8, available_now=15),
            _candidate(3, price=479_999, score=0.7, available_now=15),
            _candidate(4, price=500_000, score=0.6, available_now=15),
        ],
        requested_quantity=15,
    )

    assert _shelf(projection, "shared").initial[0].product.sku == "SKU-1"
    alternatives = _shelf(
        projection, "shared:commercially_proportionate"
    )
    assert alternatives.decision_view == "commercially_proportionate"
    assert [item.product.sku for item in alternatives.initial] == [
        "SKU-2", "SKU-3",
    ]
    assert all(item.price_cents <= 480_000 for item in alternatives.initial)


def test_verified_hard_failure_is_excluded_but_unknown_is_conditional():
    failed_product = _product(1)
    unknown_product = _product(2)
    candidates = [
        _candidate(
            1,
            product=failed_product,
            shared=_decision(failed_product, verdict="below_minimum"),
        ),
        _candidate(
            2,
            product=unknown_product,
            shared=_decision(unknown_product, verdict="unknown"),
        ),
    ]

    projection = build_product_shelves(candidates)

    shelf = _shelf(projection, "shared")
    assert [item.product.sku for item in shelf.initial] == ["SKU-2"]
    assert shelf.initial[0].fit_status == "conditional"
    assert [(item.sku, item.reason) for item in projection.exclusions] == [
        ("SKU-1", "verified_hard_failure")
    ]


def test_most_expensive_configuration_loses_when_verified_requirement_fails():
    expensive = _product(1)
    supported = _product(2)
    projection = build_product_shelves([
        _candidate(
            1, price=1_500_000, score=1.0, product=expensive,
            shared=_decision(expensive, verdict="below_minimum"),
        ),
        _candidate(
            2, price=500_000, score=0.7, product=supported,
            shared=_decision(supported),
        ),
    ])

    assert [item.product.sku for item in _shelf(projection, "shared").initial] == ["SKU-2"]
    assert [(item.sku, item.reason) for item in projection.exclusions] == [
        ("SKU-1", "verified_hard_failure")
    ]


def test_unverified_below_minimum_cannot_be_excluded_as_hard_failure():
    product = _product(1)
    candidate = _candidate(
        1,
        product=product,
        shared=_decision(product, verdict="below_minimum", verification="unverified"),
    )

    projection = build_product_shelves([candidate])

    assert _shelf(projection, "shared").initial[0].fit_status == "conditional"
    assert projection.exclusions == []


def test_decision_evidence_cannot_cross_exact_configuration_identity():
    configuration_a = _product(1, sku="FAMILY-SKU", config="a")
    configuration_b = _product(1, sku="FAMILY-SKU", config="b")

    with pytest.raises(ValueError, match="decision_configuration_mismatch:shared"):
        ShelfCandidateInput(
            product=configuration_b,
            title="Same family, different configuration",
            price_cents=200_000,
            fit_by_scope={"shared": _decision(configuration_a)},
        )


def test_same_marketing_sku_with_distinct_configurations_remains_distinct():
    configuration_a = _product(1, sku="FAMILY-SKU", config="a")
    configuration_b = _product(1, sku="FAMILY-SKU", config="b")
    projection = build_product_shelves(
        [
            _candidate(1, product=configuration_a, score=0.9),
            _candidate(2, product=configuration_b, score=0.8),
        ]
    )

    products = _shelf(projection, "shared").initial
    assert [item.product.sku for item in products] == ["FAMILY-SKU", "FAMILY-SKU"]
    assert products[0].identity_key != products[1].identity_key


def test_duplicate_exact_configuration_is_rejected_instead_of_merging_evidence():
    product = _product(1)
    candidate = _candidate(1, product=product)
    with pytest.raises(ValueError, match="duplicate_candidate_configuration"):
        build_product_shelves([candidate, candidate])
