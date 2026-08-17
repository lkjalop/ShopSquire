from src.app.services.case_price_intelligence import project_price_baselines


def _price(index, amount, currency="AUD"):
    return {
        "observation_id": f"price-{index}", "kind": "price",
        "known_at": f"2026-08-{index:02d}T00:00:00Z",
        "value": {"amount_cents": amount, "currency": currency},
    }


def test_price_baselines_are_causal_measured_and_non_authoritative():
    result = project_price_baselines([
        _price(1, 100_00), _price(2, 110_00), _price(3, 120_00), _price(4, 130_00),
    ], alpha=0.5)
    assert result["status"] == "measured"
    assert result["observation_count"] == 4
    assert set(result["mae_minor_units"]) == {"seasonal_naive", "ewma"}
    assert result["selected_baseline"] in result["mae_minor_units"]
    assert len(result["evaluation_pairs"]) == 3
    assert result["evaluation_pairs"][0] == {
        "target_observation_id": "price-2",
        "target_known_at": "2026-08-02T00:00:00Z",
        "actual_minor_units": 110_00,
        "predictions_minor_units": {"seasonal_naive": 100_00, "ewma": 100_00.0},
        "training_observation_count": 1,
    }
    assert result["evaluation_semantics"].startswith("prequential")
    assert result["pricing_authority_granted"] is False


def test_price_baseline_does_not_mix_currency_without_fx_authority():
    result = project_price_baselines([
        _price(1, 100_00), _price(2, 110_00, "USD"), _price(3, 120_00),
    ])
    assert result == {
        "status": "not_comparable", "reason": "mixed_currency_without_fx_authority",
    }


def test_price_baseline_reports_insufficient_history_honestly():
    result = project_price_baselines([_price(1, 100_00), _price(2, 110_00)])
    assert result["status"] == "insufficient_history"
    assert result["minimum_required"] == 3
