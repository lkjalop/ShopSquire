from __future__ import annotations

import json

from src.app.config import load_feature_flags


def test_retired_fulfillment_defer_flag_cannot_be_resurrected_by_environment(tmp_path, monkeypatch):
    flags_path = tmp_path / "feature_flags.json"
    flags_path.write_text(json.dumps({"FULFILLMENT_DEFER_TO_CART": False}), encoding="utf-8")

    monkeypatch.setenv("FULFILLMENT_DEFER_TO_CART", "1")

    flags = load_feature_flags(str(flags_path))
    assert "FULFILLMENT_DEFER_TO_CART" not in flags


def test_load_feature_flags_allows_env_only_sales_response_threshold(
    tmp_path, monkeypatch
):
    flags_path = tmp_path / "feature_flags.json"
    flags_path.write_text(
        json.dumps({"SALES_RESPONSE_NUDGE_ENABLED": True}),
        encoding="utf-8",
    )

    monkeypatch.setenv("SALES_RESPONSE_OVERSTOCK_UNITS", "10")

    flags = load_feature_flags(str(flags_path))
    assert flags["SALES_RESPONSE_OVERSTOCK_UNITS"] == "10"
