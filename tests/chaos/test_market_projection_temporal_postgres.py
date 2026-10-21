"""Run the same canonical producer/temporal assertions on owned PostgreSQL."""
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from src.app.services import market_projection as market
from tests.chaos.test_request_database_owner_postgres import native_owners
from tests.services.test_canonical_fact_adapters import _migration
from tests.services.test_market_projection_temporal import (
    NOW,SECRET,
    test_signed_current_snapshot_uses_on_hand_minus_commitments_and_safety,
    test_invalid_newer_snapshot_cannot_shadow_current_signed_snapshot,
    test_snapshot_order_compares_instants_across_offsets,
    test_start_inclusive_and_no_validity_fields_use_bounded_observation,
    test_missing_on_hand_does_not_promote_a_future_order_confirmation_to_stock,
    test_foreign_tenant_snapshot_cannot_shadow_owned_stock,
    test_sales_window_never_counts_a_future_event,
)


@pytest.fixture()
def db(native_owners,monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(market,'datetime',Clock)
    monkeypatch.setenv('MARKET_SOURCE_ERP_SECRET',SECRET)
    monkeypatch.setenv('MARKET_SOURCE_NETSUITE_SECRET',SECRET)
    with Session(native_owners[0]) as session:
        for name in ('20260721_market_fact_contract.py','20260722_market_fact_governance.py','20260723_market_fact_quarantine_dedup.py'):
            _migration(session,name,'native_temporal_'+name[:-3])
        session.commit()
        yield session
