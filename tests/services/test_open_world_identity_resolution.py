import json

from src.app.services.open_world_identity_resolution import (
    open_world_identity_timeout_s,
    resolve_open_world_identity,
)
from src.app.services.shopping_case_open_world_research import (
    identity_only_workload_authorization,
)


def _candidates():
    return [
        {
            "url": "https://www.factoryio.com/docs/system-requirements",
            "registrable_domain": "factoryio.com",
            "title": "Factory I/O system requirements",
            "untrusted_discovery_text": [
                "Factory I/O is a 3D factory simulation by Real Games."
            ],
            "quality_score": 32,
            "publisher_ownership_evaluation": {
                "status": "plausible_direct_origin", "confidence": 0.9,
            },
        },
        {
            "url": "https://dictionary.example/factory",
            "registrable_domain": "dictionary.example",
            "title": "Factory definition",
            "untrusted_discovery_text": ["Definition of factory."],
            "quality_score": 3,
        },
    ]


def test_model_identity_is_clamped_to_cited_candidate_rows():
    raw = json.dumps({
        "canonical_title": "Factory I/O",
        "publisher": "Real Games",
        "publisher_domain": "factoryio.com",
        "release_state": "unknown",
        "release_date": None,
        "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })

    result = resolve_open_world_identity(
        "I need Factory IO for a training lab",
        _candidates(),
        model_fn=lambda _prompt, _timeout: raw,
    )

    assert result["status"] == "resolved"
    assert result["identity"]["canonical_title"] == "Factory I/O"
    assert result["identity"]["publisher"] == "Real Games"
    assert result["identity"]["publisher_domain"] == "factoryio.com"
    assert result["identity"]["supporting_row_ids"] == ["candidate-1"]
    assert result["authority"] == "cited_candidate_rows_only"


def test_harmless_model_metadata_does_not_discard_grounded_identity():
    raw = json.dumps({
        "canonical_title": "Factory I/O",
        "publisher": "Real Games",
        "publisher_domain": "factoryio.com",
        "release_date": None,
        "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
        "confidence": 0.93,
        "reason": "title and publisher host agree",
    })
    result = resolve_open_world_identity(
        "Factory IO", _candidates(), model_fn=lambda _prompt, _timeout: raw,
    )
    assert result["status"] == "resolved"
    assert result["identity"]["release_state"] == "unknown"


def test_cited_title_resolves_without_inventing_publisher_ownership():
    candidates = [{
        "url": "https://technical.city/en/system-requirements/where-winds-meet",
        "registrable_domain": "technical.city",
        "title": "Where Winds Meet System Requirements: Can You Run It?",
        "untrusted_discovery_text": [
            "Official system requirements for PC To run Where Winds Meet."
        ],
    }]
    raw = json.dumps({
        "canonical_title": "Where Winds Meet",
        "publisher": None,
        "publisher_domain": None,
        "release_state": "unknown",
        "release_date": None,
        "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })

    result = resolve_open_world_identity(
        "What about Where Winds Meet? Has it been released?",
        candidates,
        model_fn=lambda _prompt, _timeout: raw,
    )

    assert result["status"] == "resolved"
    assert result["identity"]["canonical_title"] == "Where Winds Meet"
    assert result["identity"]["publisher_domain"] is None
    assert result["authority"] == "cited_candidate_rows_only"

    authorization = identity_only_workload_authorization(result)
    assert authorization["status"] == "blocked"
    assert authorization["evidence"][0]["canonical_title"] == "Where Winds Meet"
    assert authorization["evidence"][0]["release_state"] == "unknown"
    assert authorization["evidence"][0]["qualification_authority"] == "none"


def test_near_valid_model_schema_is_normalized_before_grounding():
    raw = json.dumps({
        "canonical_title": "Factory I/O",
        "publisher": "Real Games",
        "publisher_domain": "factoryio.com",
        "release_state": "not specified in search result",
        "release_date": None,
        "nearest_equivalent": None,
        "supporting_row_ids": "candidate-1",
    })
    result = resolve_open_world_identity(
        "Factory IO", _candidates(), model_fn=lambda _prompt, _timeout: raw,
    )
    assert result["status"] == "resolved"
    assert result["identity"]["release_state"] == "unknown"
    assert result["identity"]["supporting_row_ids"] == ["candidate-1"]


def test_model_cannot_invent_identity_or_publisher_outside_cited_rows():
    raw = json.dumps({
        "canonical_title": "Invented Suite Pro",
        "publisher": "Imaginary Corp",
        "publisher_domain": "imaginary.example",
        "release_state": "released",
        "release_date": "2026-01-01",
        "nearest_equivalent": "Factory I/O",
        "supporting_row_ids": ["candidate-1"],
    })

    result = resolve_open_world_identity(
        "tarae factory simulator",
        _candidates(),
        model_fn=lambda _prompt, _timeout: raw,
    )

    assert result["status"] == "rejected"
    assert result["failure_code"] == "identity_not_grounded_in_cited_rows"
    assert result["identity"] is None


def test_grounded_title_survives_ungrounded_optional_publisher_domain():
    raw = json.dumps({
        "canonical_title": "Factory I/O",
        "publisher": "Real Games",
        "publisher_domain": "invented-publisher.example",
        "release_state": "unknown",
        "release_date": None,
        "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })

    result = resolve_open_world_identity(
        "Factory IO", _candidates(), model_fn=lambda _prompt, _timeout: raw,
    )

    assert result["status"] == "resolved"
    assert result["identity"]["canonical_title"] == "Factory I/O"
    assert result["identity"]["publisher_domain"] is None
    assert result["authority"] == "cited_candidate_rows_only"


def test_single_token_cited_typo_requires_confirmation_without_an_alias_table():
    candidates = [{
        "url": "https://store.steampowered.com/app/1867240/WARDOGS/",
        "registrable_domain": "steampowered.com",
        "title": "Pre-purchase WARDOGS on Steam",
        "untrusted_discovery_text": ["WARDOGS is available on Steam."],
    }]
    raw = json.dumps({
        "canonical_title": "WARDOGS", "publisher": None,
        "publisher_domain": "steampowered.com", "release_state": "unknown",
        "release_date": None, "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })

    result = resolve_open_world_identity(
        "Can a laptop run WAROGS?", candidates,
        model_fn=lambda _prompt, _timeout: raw,
    )

    assert result["status"] == "confirmation_required"
    assert result["identity"]["canonical_title"] == "WARDOGS"
    assert result["identity"]["buyer_subject_match"] == {
        "basis": "cited_spelling_correction", "buyer_token": "warogs",
        "cited_title_token": "wardogs", "similarity": 0.9231,
    }
    assert result["fetch_authority"] == "none"


def test_cited_sibling_product_cannot_replace_buyer_named_subject():
    candidates = [{
        "url": "https://factory.ai/quickstart",
        "registrable_domain": "factory.ai",
        "title": "Factory App Quickstart",
        "untrusted_discovery_text": ["Factory App documentation"],
    }]
    raw = json.dumps({
        "canonical_title": "Factory App", "publisher": None,
        "publisher_domain": "factory.ai", "release_state": "unknown",
        "release_date": None, "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })
    result = resolve_open_world_identity(
        "I need a workstation that can run Factory IO locally.", candidates,
        model_fn=lambda _prompt, _timeout: raw,
    )
    assert result["status"] == "rejected"
    assert result["failure_code"] == "identity_not_grounded_in_buyer_subject"


def test_close_cited_identity_requires_confirmation_instead_of_confident_fetch():
    candidates = [{
        "url": "https://store.steampowered.com/app/2190250/",
        "registrable_domain": "steampowered.com",
        "title": "The Blood of Dawnwalker on Steam",
        "untrusted_discovery_text": [
            "The Blood of Dawnwalker is an action role-playing game."
        ],
    }]
    raw = json.dumps({
        "canonical_title": "The Blood of Dawnwalker",
        "publisher": None,
        "publisher_domain": "steampowered.com",
        "release_state": "unknown",
        "release_date": None,
        "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })

    result = resolve_open_world_identity(
        "can my kid play bloodwalker the new witcher",
        candidates,
        model_fn=lambda _prompt, _timeout: raw,
    )

    assert result["status"] == "confirmation_required"
    assert result["identity"]["canonical_title"] == "The Blood of Dawnwalker"
    assert result["failure_code"] == "low_confidence_identity_confirmation_required"
    assert result["fetch_authority"] == "none"


def test_single_token_typo_never_auto_accepts_without_confirmation():
    candidates = [{
        "url": "https://store.steampowered.com/app/2408100/",
        "registrable_domain": "steampowered.com",
        "title": "PRAGMATA on Steam",
        "untrusted_discovery_text": ["PRAGMATA is an action adventure game."],
    }]
    raw = json.dumps({
        "canonical_title": "PRAGMATA", "publisher": None,
        "publisher_domain": "steampowered.com", "release_state": "unknown",
        "release_date": None, "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })

    result = resolve_open_world_identity(
        "pragmta laptop", candidates, model_fn=lambda _prompt, _timeout: raw,
    )

    assert result["status"] == "confirmation_required"
    assert result["identity"]["canonical_title"] == "PRAGMATA"
    assert result["fetch_authority"] == "none"


def test_optional_model_embellishments_are_dropped_without_losing_grounded_identity():
    raw = json.dumps({
        "canonical_title": "Factory I/O",
        "publisher": "Real Games Incorporated",
        "publisher_domain": "factoryio.com",
        "release_state": "released",
        "release_date": "2012-01-01",
        "nearest_equivalent": "Imaginary Factory Pro",
        "supporting_row_ids": ["candidate-1"],
    })
    result = resolve_open_world_identity(
        "Factory IO", _candidates(), model_fn=lambda _prompt, _timeout: raw,
    )
    assert result["status"] == "resolved"
    assert result["identity"] == {
        "canonical_title": "Factory I/O", "publisher": None,
        "publisher_domain": "factoryio.com", "release_state": "unknown",
        "release_date": None, "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
        "buyer_subject_match": {"basis": "exact_buyer_span"},
    }


def test_identity_model_failure_remains_unresolved_without_alias_rules():
    result = resolve_open_world_identity(
        "Bloodwalker hardware",
        _candidates(),
        model_fn=lambda _prompt, _timeout: (_ for _ in ()).throw(TimeoutError()),
    )

    assert result["status"] == "unresolved"
    assert result["failure_code"] == "identity_model_timeout"
    assert result["identity"] is None


def test_invalid_identity_json_gets_one_bounded_retry():
    valid = json.dumps({
        "canonical_title": "Factory I/O", "publisher": "Real Games",
        "publisher_domain": "factoryio.com", "release_state": "unknown",
        "release_date": None, "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })
    outputs = iter(["not json", valid])

    result = resolve_open_world_identity(
        "Factory IO", _candidates(), model_fn=lambda _prompt, _timeout: next(outputs),
    )

    assert result["status"] == "resolved"
    assert result["model_calls"] == 2


def test_null_title_gets_one_bounded_semantic_repair_without_aliases():
    unresolved = json.dumps({
        "canonical_title": None, "publisher": None, "publisher_domain": None,
        "release_state": "unknown", "release_date": None,
        "nearest_equivalent": None, "supporting_row_ids": ["candidate-1"],
    })
    resolved = json.dumps({
        "canonical_title": "Factory I/O", "publisher": "Real Games",
        "publisher_domain": "factoryio.com", "release_state": "unknown",
        "release_date": None, "nearest_equivalent": None,
        "supporting_row_ids": ["candidate-1"],
    })
    outputs = iter([unresolved, resolved])

    result = resolve_open_world_identity(
        "Factory IO", _candidates(), model_fn=lambda _prompt, _timeout: next(outputs),
    )

    assert result["status"] == "resolved"
    assert result["model_calls"] == 2


def test_identity_runtime_failure_preserves_safe_component_code():
    result = resolve_open_world_identity(
        "Factory IO", _candidates(),
        model_fn=lambda _prompt, _timeout: (_ for _ in ()).throw(
            RuntimeError("model_execution_timeout")
        ),
    )
    assert result["status"] == "unresolved"
    assert result["failure_code"] == "model_execution_timeout"


def test_identity_timeout_uses_measured_p90_with_bounds(monkeypatch):
    monkeypatch.delenv("OPEN_WORLD_IDENTITY_TIMEOUT_S", raising=False)
    monkeypatch.setenv("OPEN_WORLD_IDENTITY_MIN_TIMEOUT_MS", "12000")
    monkeypatch.setenv("OPEN_WORLD_IDENTITY_LATENCY_MULTIPLIER", "1.25")
    monkeypatch.setattr(
        "src.app.services.open_world_identity_resolution.observed_model_latency_ms",
        lambda **_: 14_000,
    )
    assert open_world_identity_timeout_s() == 17.5


def test_identity_timeout_is_hard_capped(monkeypatch):
    monkeypatch.delenv("OPEN_WORLD_IDENTITY_TIMEOUT_S", raising=False)
    monkeypatch.setattr(
        "src.app.services.open_world_identity_resolution.observed_model_latency_ms",
        lambda **_: 40_000,
    )
    assert open_world_identity_timeout_s() == 20.0
