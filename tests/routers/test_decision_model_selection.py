from src.app.routers import decisions


def test_model_directed_trace_does_not_invent_rule_tier():
    model_selection = {
        "selected": "qwen3:14b",
        "source": "model",
        "authority": "proposes",
    }

    model_selection["decision"] = decisions._default_model_decision(model_selection)

    assert model_selection["decision"] == {"action": "model_directed"}
    assert "prefer_small" not in str(model_selection)


def test_non_model_fast_path_keeps_rule_tier_signal():
    assert decisions._default_model_decision({"complex": False}) == {
        "action": "prefer_small",
    }
