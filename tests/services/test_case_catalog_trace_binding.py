from src.app.routers import shopping_cases
from src.app.services import shopping_case_trace_reader


def test_current_turn_catalog_boundary_uses_explicit_decision_trace(monkeypatch) -> None:
    observed = {}

    def fake_load(_db, **kwargs):
        observed.update(kwargs)
        return [{
            "event_type": "ambiguity_exploration_projected",
            "payload": {
                "catalog_candidate_set": {
                    "schema_version": "catalog-candidate-set-v1",
                    "retained_purpose": "laptop for a cited workload",
                    "status": "eligible",
                    "taxonomy_handle": "el-6-6",
                    "taxonomy_label": "Electronics > Computers > Laptops",
                    "taxonomy_source": "storefront_context",
                    "configuration_ids": ["cfg-1"],
                    "excluded_configuration_ids": [],
                    "reason": "query_specific_catalog_candidates",
                },
            },
        }]

    monkeypatch.setattr(shopping_case_trace_reader, "load_case_trace_events", fake_load)

    result = shopping_cases._case_catalog_candidate_set_from_trace(
        object(), case_id="sc-1", tenant_id="default", decision_trace_id="trace-1",
    )

    assert observed["decision_trace_id"] == "trace-1"
    assert result.configuration_ids == ["cfg-1"]
