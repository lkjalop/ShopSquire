from copy import deepcopy

from src.app.services.structured_requirement_claims import project_structured_requirement_claims


def authorization():
    return {"evidence": [{
        "status": "resolved", "provider_id": "steam", "app_id": "2162800",
        "source_url": "https://store.steampowered.com/app/2162800/",
        "compiled_requirements": [
            {"attribute_key": key, "operator": ">=", "value": value, "unit": "GB",
             "requirement_class": "minimum", "source_claim_ids": ["2162800"]}
            for key, value in [("ram_gb", 8), ("gpu_vram_gb", 2)]
        ],
    }]}


def test_distinct_predicates_never_share_the_provider_record_id():
    claims = project_structured_requirement_claims(authorization())
    assert len({c["claim_id"] for c in claims}) == 2
    assert [c["value"] for c in claims] == [8, 2]
    assert all(c["source_claim_ids"] == ["2162800"] for c in claims)


def test_missing_or_unverified_status_is_not_promoted_to_official():
    for status in [None, "unverified"]:
        data = authorization()
        for row in data["evidence"][0]["compiled_requirements"]:
            if status:
                row["verification_status"] = status
        assert all(c["authority_status"] == "observed_held"
                   for c in project_structured_requirement_claims(data))


def test_explicit_verification_is_preserved():
    data = authorization()
    for row in data["evidence"][0]["compiled_requirements"]:
        row["verification_status"] = "verified"
    assert all(c["authority_status"] == "verified_official"
               for c in project_structured_requirement_claims(data))


def test_claim_identity_is_stable_but_changes_with_evidence_content_or_origin():
    first = authorization()
    ids = lambda value: [c["claim_id"] for c in project_structured_requirement_claims(value)]
    assert ids(first) == ids(deepcopy(first))
    reordered = deepcopy(first)
    reordered["evidence"][0]["compiled_requirements"].reverse()
    assert ids(reordered) == list(reversed(ids(first)))
    for field, value in [("value", 16), ("requirement_class", "recommended"),
                         ("scope_caveat", "large models"), ("source_revision", "v2")]:
        changed = deepcopy(first)
        changed["evidence"][0]["compiled_requirements"][0][field] = value
        assert ids(changed)[0] != ids(first)[0]
        assert ids(changed)[1] == ids(first)[1]
    changed = deepcopy(first)
    changed["evidence"][0]["provider_id"] = "another-provider"
    assert set(ids(changed)).isdisjoint(ids(first))
