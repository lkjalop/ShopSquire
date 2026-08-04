from src.app.services.demand_forecast import rolling_origin_evaluation
from src.app.services.synthetic_policy_counterfactual import (
    compare_inventory_policies,
)


def test_prediction_intervals_are_calibrated_per_model_on_held_out_origins():
    history = [0, 1, 0, 2, 0, 0, 3] * 18

    evaluation = rolling_origin_evaluation(
        history,
        horizon_days=5,
        min_train_points=14,
    )

    assert evaluation["winner"] in evaluation["models"]
    intervals = {
        name: row["prediction_interval"]
        for name, row in evaluation["models"].items()
    }
    assert all(row["status"] == "observed" for row in intervals.values())
    assert all(row["method"] == "split_conformal_absolute_residual" for row in intervals.values())
    assert all(0.0 <= row["empirical_coverage"] <= 1.0 for row in intervals.values())
    assert all(row["evaluation_origins"] > 0 for row in intervals.values())
    assert len({row["calibration_error_units"] for row in intervals.values()}) > 1
    assert evaluation["selected_prediction_interval"] == intervals[evaluation["winner"]]


def test_prediction_interval_reports_explicit_undefined_state_without_origins():
    evaluation = rolling_origin_evaluation([1.0, 0.0, 1.0], horizon_days=2)

    assert evaluation["status"] == "insufficient_history"
    assert evaluation["selected_prediction_interval"]["status"] == "undefined_no_selected_model"
    assert evaluation["models"] == {}


def test_policy_counterfactual_is_explicitly_undefined_for_zero_demand():
    replay = {
        "history": {
            "daily_history": [
                {"latent_demand_units": 0},
                {"latent_demand_units": 0},
            ],
            "purchase_orders": [],
        },
        "profile": {
            "reorder_point": 1,
            "reorder_quantity": 2,
        },
    }

    result = compare_inventory_policies(
        replay,
        candidate_reorder_point=2,
        candidate_reorder_quantity=3,
        candidate_label="test",
    )

    assert result["status"] == "undefined_zero_demand"
    assert result["baseline"] is None
    assert result["candidate"] is None
    assert result["execution_allowed"] is False
    assert result["causal_claim_allowed"] is False
