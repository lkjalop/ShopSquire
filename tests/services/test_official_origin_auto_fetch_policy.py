from src.app.services.shopping_case_open_world_research import (
    official_origin_auto_fetch_eligible,
)


def _candidate():
    return {
        "title": "Factory I/O system requirements",
        "registrable_domain": "factoryio.com",
        "publisher_ownership_evaluation": {
            "status": "plausible_direct_origin", "confidence": 0.91,
        },
    }


def test_demo_policy_can_fetch_only_when_cited_identity_and_origin_agree():
    resolution = {
        "status": "resolved",
        "identity": {
            "canonical_title": "Factory I/O", "publisher_domain": "factoryio.com",
        },
    }
    assert official_origin_auto_fetch_eligible(
        identity_resolution=resolution,
        candidate=_candidate(),
        policy={"authorized": True},
    ) is True


def test_auto_fetch_rejects_domain_mismatch_non_direct_or_disabled_policy():
    resolution = {
        "status": "resolved",
        "identity": {
            "canonical_title": "Factory I/O", "publisher_domain": "wrong.example",
        },
    }
    assert not official_origin_auto_fetch_eligible(
        identity_resolution=resolution, candidate=_candidate(), policy={"authorized": True},
    )
    resolution["identity"]["publisher_domain"] = "factoryio.com"
    candidate = _candidate()
    candidate["publisher_ownership_evaluation"]["status"] = "plausible_documentation_origin"
    assert not official_origin_auto_fetch_eligible(
        identity_resolution=resolution, candidate=candidate, policy={"authorized": True},
    )
    assert not official_origin_auto_fetch_eligible(
        identity_resolution=resolution, candidate=_candidate(), policy={"authorized": False},
    )


def test_cited_top_direct_origin_does_not_require_model_to_repeat_domain():
    resolution = {
        "status": "resolved",
        "identity": {
            "canonical_title": "Factory I/O",
            "publisher_domain": None,
            "supporting_row_ids": ["candidate-1"],
        },
    }
    assert official_origin_auto_fetch_eligible(
        identity_resolution=resolution,
        candidate=_candidate(),
        policy={"authorized": True},
    )

    resolution["identity"]["supporting_row_ids"] = ["candidate-2"]
    assert not official_origin_auto_fetch_eligible(
        identity_resolution=resolution,
        candidate=_candidate(),
        policy={"authorized": True},
    )
