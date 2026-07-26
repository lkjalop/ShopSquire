from src.app.services.reorder_supplier_flow import plan_reorder_with_supplier_draft


def test_forecast_failure_never_creates_zero_quantity_supplier_draft():
    called = []

    def broken_forecast(*_args):
        raise RuntimeError("forecast provider unavailable")

    def draft(**kwargs):
        called.append(kwargs)
        return kwargs

    result = plan_reorder_with_supplier_draft(
        sku="SKU-1",
        current_stock=2,
        reorder_point=5,
        forecast_fn=broken_forecast,
        draft_fn=draft,
    )

    assert result["status"] == "degraded_no_proposal"
    assert result["reason"] == "forecast_unavailable"
    assert result["proposed_qty"] is None
    assert result["draft"] is None
    assert called == []
