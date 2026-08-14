from src.app.services.hippograph_trust_projection import project_path_trust


def test_empty_path_is_insufficient_not_healthy():
    view = project_path_trust({"edges": []})
    assert view.status == "insufficient" and view.evidence_records == 0


def test_inference_unknown_authority_and_stale_state_stay_conditional():
    view = project_path_trust({"edges": [{"evidence": [{
        "signal_class": "inferred", "source_authority": "unspecified",
        "attributes": {"measurement_state": "stale"},
    }]}]})
    assert view.status == "conditional"
    assert view.inferred_records == 1
    assert view.unknown_authority_records == 1
    assert view.stale_or_contradicted_records == 1


def test_attested_current_path_can_be_healthy_without_becoming_fit_authority():
    view = project_path_trust({"edges": [{"evidence": [{
        "signal_class": "attested", "source_authority": "oem",
        "attributes": {"measurement_state": "attested"},
    }]}]})
    assert view.status == "healthy" and view.authority == "evidence_quality_only"
