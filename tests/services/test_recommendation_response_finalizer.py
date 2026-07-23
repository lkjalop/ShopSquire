from src.app.services import recommendation_response_finalizer as finalizer


def test_finalizer_freezes_one_trace_and_ordered_sku_identity(monkeypatch):
    recorded = {}

    def fake_trace(**kwargs):
        recorded["event"] = kwargs

    def fake_decision(**kwargs):
        recorded["decision"] = kwargs
        return True

    monkeypatch.setattr(finalizer, "log_trace_event", fake_trace)
    monkeypatch.setattr(finalizer, "log_decision", fake_decision)

    payload = {
        "turn_intent": "COMPARE",
        "execution_mode": "v2_served",
        "results": [
            {
                "sku": "SKU-B",
                "name": "Second",
                "why": ["within_budget", "gpu_vram_gb >= 8"],
                "score_norm": 0.92,
                "workload_fit": {"overall": "meets"},
            },
            {"sku": "SKU-A", "name": "First"},
        ],
        "constraints_used": {
            "use_case": "gaming",
            "budget_max": 2000,
            "requirements": {"gpu_vram_gb": [[">=", 8]]},
        },
        "right_panel": {"mode": "recommendations"},
    }
    out = finalizer.finalize_core_response(
        payload, "trace-voice-1", query="compare these",
        tenant_id="tenant-a", uid="buyer-a",
    )

    expected = {
        "trace_id": "trace-voice-1",
        "ordered_skus": ["SKU-B", "SKU-A"],
    }
    assert out["canonical_identity"] == expected
    assert out["right_panel"]["canonical_identity"] == expected
    assert recorded["event"]["payload"]["canonical_identity"] == expected
    assert recorded["event"]["payload"]["right_panel_contract"]["canonical_identity"] == expected
    proposed = recorded["decision"]["proposed_action"]
    assert proposed["canonical_identity"] == expected
    assert [row["sku"] for row in proposed["products_summary"]] == expected["ordered_skus"]
    assert proposed["products_summary"][0]["reasons"] == [
        "within_budget", "gpu_vram_gb >= 8",
    ]
    assert proposed["products_summary"][0]["score_norm"] == 0.92
    assert proposed["products_summary"][0]["workload_fit"] == {"overall": "meets"}
    assert recorded["event"]["payload"]["constraints_used"]["use_case"] == "gaming"
    assert recorded["event"]["payload"]["security"] == {
        "policy_route": "allow",
        "checked_boundary": "recommendation_facade",
        "has_image": False,
    }
    assert proposed["intent_analysis"]["budget_max"] == 2000
    assert proposed["intent_analysis"]["requirements"] == {
        "gpu_vram_gb": [[">=", 8]],
    }
    assert proposed["execution_mode"] == "v2_served"
