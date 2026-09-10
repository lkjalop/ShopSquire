from copy import deepcopy

from src.app.services.structured_requirement_claims import project_structured_requirement_claims


def test_preflight_identity_cannot_overwrite_executed_provider_evidence():
    from src.app.services.structured_requirement_claims import merge_preflight_identity
    current = {'app_id': '1', 'cached': False, 'live_allowed': True,
               'minimum': {'cpu': 'Current CPU'}, 'compiled_requirements': [{'value': 32}],
               'claim_rejections': [], 'status': 'resolved'}
    fixture = {'app_id': '1', 'canonical_title': 'Canonical title', 'cached': True,
               'minimum': {'ram_gb': 8}, 'compiled_requirements': [{'value': 8}],
               'claim_rejections': [{'reason': 'old'}], 'source_url': 'old-url'}
    result = merge_preflight_identity(current, fixture)
    assert result['canonical_title'] == 'Canonical title'
    for key, value in current.items():
        assert result[key] == value
    assert 'source_url' not in result
    failed = merge_preflight_identity({'status': 'not_resolved', 'compiled_requirements': []}, fixture)
    assert failed['compiled_requirements'] == []
    assert failed['status'] == 'not_resolved'


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


def test_projection_preserves_literal_provenance_and_scope_without_aliasing():
    data = authorization()
    compiled = data["evidence"][0]["compiled_requirements"][0]
    compiled.update({
        "attribute_key": "cpu_model", "operator": "in", "unit": None,
        "value": ["CPU A", "CPU B"], "source_excerpt": "CPU A or CPU B",
        "value_spans": [[0, 5], [9, 14]], "source_revision": "document-v1",
        "compilation_scope": {"tenant_id": "demo", "manifest_revision": "v1"},
        "verification_status": "verified",
    })
    claim = project_structured_requirement_claims(data)[0]
    for key in ("source_excerpt", "value_spans", "source_revision", "compilation_scope"):
        assert claim[key] == compiled[key]
    assert claim["authority_status"] == "verified_official"
    claim["value_spans"][0][0] = 4
    claim["value"].append("invented")
    claim["compilation_scope"]["tenant_id"] = "another"
    assert compiled["value_spans"][0][0] == 0
    assert compiled["value"] == ["CPU A", "CPU B"]
    assert compiled["compilation_scope"]["tenant_id"] == "demo"


def test_claim_id_is_bound_to_manifest_and_cited_span():
    data = authorization()
    compiled = data["evidence"][0]["compiled_requirements"][0]
    compiled.update({"source_excerpt": "8 GB", "compilation_scope": {
        "tenant_id": "demo", "manifest_revision": "v1"}})
    original = project_structured_requirement_claims(data)[0]["claim_id"]
    for key, value in (("source_excerpt", "Memory: 8 GB"),
                       ("compilation_scope", {"tenant_id": "demo", "manifest_revision": "v2"})):
        changed = deepcopy(data)
        changed["evidence"][0]["compiled_requirements"][0][key] = value
        assert project_structured_requirement_claims(changed)[0]["claim_id"] != original
