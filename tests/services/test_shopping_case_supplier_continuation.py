from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.orm import Base
from src.app.services.shopping_case_supplier_continuation import (
    SupplierOfferInput,
    normalize_supplier_offers,
    resolve_confirmed_cart_target,
    select_fulfillment_option,
)


def _db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_existing_procurement_offer_is_buyer_safe_and_retains_provenance() -> None:
    offers = normalize_supplier_offers([SupplierOfferInput(
        source_type="existing_procurement_case", source_reference="case-17/rfq-2",
        supplier_reference="supplier-approved-3", offered_sku="SKU-EXACT",
        relationship="exact", quantity_available=18, lead_time_days=8,
        unit_price_cents=500_000,
    )])

    assert offers[0].supplier_send == "not_performed"
    assert offers[0].purchase_commitment is False
    assert offers[0].provenance == {
        "source_type": "existing_procurement_case",
        "source_reference": "case-17/rfq-2",
        "supplier_reference": "supplier-approved-3",
    }


def test_selection_is_revision_bound_and_idempotent() -> None:
    with _db() as db:
        args = dict(
            tenant_id="default", case_id="sc-1", uid="buyer", expected_revision=0,
            choice="split_delivery", preferred_sku="PREFERRED", requested_quantity=30,
            available_now=12, idempotency_key="select-key-1",
            offers=[SupplierOfferInput(
                source_type="deterministic_certification_fixture",
                source_reference="fixture-1", supplier_reference="supplier-fixture",
                offered_sku="PREFERRED", relationship="exact", quantity_available=18,
            )],
        )
        first, error = select_fulfillment_option(db, **args)
        replay, replay_error = select_fulfillment_option(db, **args)
        stale, stale_error = select_fulfillment_option(db, **{
            **args, "idempotency_key": "select-key-2", "expected_revision": 0,
        })

    assert error is None and replay_error is None
    assert first == replay
    assert stale is None and stale_error == "stale_fulfillment_revision:1"


def test_substitute_never_resolves_without_explicit_authorization() -> None:
    with _db() as db:
        selection, _ = select_fulfillment_option(
            db, tenant_id="default", case_id="sc-2", uid="buyer", expected_revision=0,
            choice="substitute", preferred_sku="PREFERRED", requested_quantity=30,
            available_now=12, idempotency_key="select-substitute",
            offers=[SupplierOfferInput(
                source_type="deterministic_certification_fixture",
                source_reference="fixture-2", supplier_reference="supplier-fixture",
                offered_sku="SUBSTITUTE", relationship="compatible_substitute",
                quantity_available=30,
            )],
        )
    assert selection is not None
    offer = selection.offers[0]
    try:
        resolve_confirmed_cart_target(
            selection, selected_offer_id=offer.offer_id, substitution_authorized=False,
        )
    except ValueError as exc:
        assert str(exc) == "substitution_requires_explicit_authorization"
    else:
        raise AssertionError("silent substitution was accepted")

    target, quantity, chosen = resolve_confirmed_cart_target(
        selection, selected_offer_id=offer.offer_id, substitution_authorized=True,
    )
    assert (target, quantity, chosen.offer_id) == ("SUBSTITUTE", 30, offer.offer_id)


def test_split_and_wait_keep_exact_preferred_sku() -> None:
    for choice in ("split_delivery", "wait_preferred"):
        with _db() as db:
            selection, error = select_fulfillment_option(
                db, tenant_id="default", case_id=f"sc-{choice}", uid="buyer",
                expected_revision=0, choice=choice, preferred_sku="PREFERRED",
                requested_quantity=30, available_now=12,
                idempotency_key=f"select-{choice}", offers=[],
            )
        assert error is None and selection is not None
        target, quantity, offer = resolve_confirmed_cart_target(
            selection, selected_offer_id=None, substitution_authorized=False,
        )
        assert (target, quantity, offer) == ("PREFERRED", 30, None)
