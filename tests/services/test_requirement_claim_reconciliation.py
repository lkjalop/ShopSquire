from src.app.services.requirement_claim_reconciliation import reconcile_requirement_claims


def test_reconciliation_is_exhaustive_and_does_not_promote_a_weaker_floor():
    rows = reconcile_requirement_claims(
        [
            {"claim_id": "ram", "attribute": "ram_gb", "operator": ">=", "value": 32, "requirement_class": "minimum"},
            {"claim_id": "vram", "attribute": "gpu_vram_gb", "operator": ">=", "value": 12, "requirement_class": "recommended"},
            {"claim_id": "os", "attribute": "operating_system", "operator": "one_of", "value": ["Windows 11 Pro"], "requirement_class": "minimum"},
            {"claim_id": "nic", "attribute": "network_interface", "operator": "=", "value": "RJ45", "requirement_class": "minimum"},
        ],
        [
            {"claim_id": "official-ram", "attribute": "ram_gb", "operator": ">=", "value": 4},
            {"claim_id": "official-os", "attribute": "operating_system", "operator": "one_of", "value": ["Windows 11 Pro", "Windows 11 Enterprise"]},
        ],
    )

    assert {row.buyer_claim_id: row.status for row in rows} == {
        "ram": "unresolved",
        "vram": "preference_only",
        "os": "corroborated",
        "nic": "unresolved",
    }


def test_mutually_exclusive_official_value_is_a_contradiction():
    [row] = reconcile_requirement_claims(
        [{"claim_id": "os", "attribute": "operating_system", "operator": "=", "value": "Linux", "requirement_class": "minimum"}],
        [{"claim_id": "official-os", "attribute": "operating_system", "operator": "one_of", "value": ["Windows 11 Pro"]}],
    )
    assert row.status == "contradicted"
    assert row.official_claim_ids == ["official-os"]


def test_stricter_official_floor_corroborates_buyer_floor():
    [row] = reconcile_requirement_claims(
        [{"claim_id": "ram", "attribute": "ram_gb", "operator": ">=", "value": 16, "requirement_class": "minimum"}],
        [{"claim_id": "official-ram", "attribute": "ram_gb", "operator": ">=", "value": 32}],
    )
    assert row.status == "corroborated"
