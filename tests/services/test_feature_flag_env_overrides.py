from __future__ import annotations

import json

from src.app.config import load_feature_flags


def test_load_feature_flags_allows_fulfillment_defer_env_override(tmp_path, monkeypatch):
    flags_path = tmp_path / "feature_flags.json"
    flags_path.write_text(json.dumps({"FULFILLMENT_DEFER_TO_CART": False}), encoding="utf-8")

    monkeypatch.setenv("FULFILLMENT_DEFER_TO_CART", "1")

    flags = load_feature_flags(str(flags_path))
    assert flags["FULFILLMENT_DEFER_TO_CART"] is True
