"""P0-sec: procurement-draft evidence must be tenant-scoped. `_default_hippograph` accepted a
`tenant_id` but did NOT forward it to `build_hippograph_insights`, so every draft used the shared
"default" scope regardless of tenant — a cross-tenant leak on a SUPPLIER-OUTBOUND artifact (Tenant
A's graph evidence, e.g. an unrelated Lenovo backpack, could surface in Tenant B's RFQ draft).
`build_hippograph_insights` already forwards tenant_id to `build_from_db`; only the call site leaked.
"""
from __future__ import annotations


def test_default_hippograph_forwards_tenant_id(monkeypatch):
    import src.app.services.fulfillment.draft as draft
    import src.app.services.hippograph_feedback as hf

    captured = {}

    def _spy(db, **kwargs):
        captured["tenant_id"] = kwargs.get("tenant_id")
        captured["seed_skus"] = kwargs.get("seed_skus")
        return {}

    monkeypatch.setattr(hf, "build_hippograph_insights", _spy)
    draft._default_hippograph(None, "SKU-TENANT-B", "tenant-B")

    assert captured["tenant_id"] == "tenant-B", (
        "cross-tenant leak: _default_hippograph must forward tenant_id to the hippograph insights")
    assert captured["seed_skus"] == ["SKU-TENANT-B"]
