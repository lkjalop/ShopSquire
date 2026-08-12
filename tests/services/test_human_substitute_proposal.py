from types import SimpleNamespace

import pytest

from src.app.services.human_substitute_proposal import HumanSubstituteRequest, propose_human_substitute


def test_human_substitute_uses_canonical_revision_bound_plan(monkeypatch):
    cart = [{"sku": "OLD", "quantity": 12, "name": "Old laptop"}]
    monkeypatch.setattr("src.app.routers.cart._load_cart_row", lambda *_a, **_k: ("cart-1", cart, 4))
    monkeypatch.setattr(
        "src.app.services.human_substitute_proposal.get_variant",
        lambda *_a, **_k: SimpleNamespace(active=True, price_cents=420000, name="New laptop"),
    )
    captured = {}
    monkeypatch.setattr(
        "src.app.services.human_substitute_proposal.propose_plan",
        lambda **kwargs: captured.update(kwargs) or {"plan_id": "cmp-1", "expires_at": "later", "risk": "confirm"},
    )
    result = propose_human_substitute(
        tenant_id="tenant-a",
        incident_id="inc-1",
        trace_id="trace-1",
        request=HumanSubstituteRequest(
            buyer_uid="buyer-1", source_sku="OLD", replacement_sku="NEW", quantity=30,
            supplier_provenance="Synthetic Supplier B offer q-2", delivery_consequence="30 available now",
        ),
    )
    op = captured["plan"].ops[0]
    assert op.action == "replace_item"
    assert op.target_skus == ("OLD",)
    assert op.replacement_sku == "NEW"
    assert op.unit_price_cents == 420000
    assert result["buyer_confirmation_required"] is True
    assert result["commercial_authority"] == "none"


@pytest.mark.parametrize("source,replacement", [("OLD", "OLD"), ("", "NEW")])
def test_human_substitute_rejects_invalid_identity(source, replacement):
    with pytest.raises(ValueError):
        propose_human_substitute(
            tenant_id="tenant-a", incident_id="inc-1", trace_id="trace-1",
            request=HumanSubstituteRequest(
                buyer_uid="buyer-1", source_sku=source, replacement_sku=replacement, quantity=1,
                supplier_provenance="offer", delivery_consequence="now",
            ),
        )
