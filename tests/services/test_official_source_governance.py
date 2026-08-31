from src.app.services.official_source_governance import (
    governed_sources_for_workload,
    load_official_source_manifest,
    source_governance_readiness,
)


def test_official_source_manifest_runs_reviewed_subset_without_promoting_pending_sources():
    status = source_governance_readiness()
    assert status["schema_version"] == "official-workload-sources-v2"
    assert status["valid_source_count"] == 20
    assert status["errors"] == []
    assert "docs.gns3.com" in status["domain_allowlist"]
    assert "learn.microsoft.com" in status["domain_allowlist"]
    assert "csrc.nist.gov" in status["domain_allowlist"]
    assert "attack.mitre.org" in status["domain_allowlist"]
    assert "docs.factoryio.com" in status["domain_allowlist"]
    assert "www.blender.org" in status["domain_allowlist"]
    assert "help.autodesk.com" in status["domain_allowlist"]
    assert "dev.epicgames.com" in status["domain_allowlist"]
    assert "store.sim3d.com" in status["domain_allowlist"]
    assert "baldursgate3.game" in status["domain_allowlist"]
    assert len(status["canonical_entrypoints"]) >= 18
    assert status["approved_source_count"] == 12
    assert status["pending_independent_human_review_count"] == 8
    assert status["operational_source_count"] == 12
    assert status["operationally_enrolled"] is True
    assert status["fully_reviewed"] is False


def test_every_source_has_scoped_claim_and_execution_governance():
    manifest = load_official_source_manifest()
    assert manifest["errors"] == []
    for source in manifest["sources"]:
        assert source["review_status"] in {"approved", "pending_independent_human_review"}
        assert source["forbidden_claim_types"]
        assert not set(source["allowed_claim_types"]) & set(source["forbidden_claim_types"])
        assert source["applicability"]["workloads"]
        assert source["applicability"]["resolution_owner"] == "research"
        assert source["publisher_policy"]["direct_origin_required"] is True
        assert source["publisher_policy"]["discovery_snippets_accepted"] is False
        assert source["cache_policy"]["max_age_hours"] <= source["freshness_sla_hours"]
        assert source["tenant_allowlist"]["default"] == "deny"
        assert source["parser_type"] in {"html", "pdf", "html_pdf", "structured_table"}


def test_workload_lookup_is_explicit_and_only_approved_policies_are_operational():
    approved = governed_sources_for_workload("ot_cyber_range")
    assert {source["source_id"] for source in approved} == {
        "microsoft_learn_hyperv",
        "nist_digital_twin_cybersecurity",
        "mitre_attack_ics",
        "factory_io_official_docs",
    }

    sources = governed_sources_for_workload(
        "ot_cyber_range",
        include_pending_review=True,
    )
    assert {source["source_id"] for source in sources} == {
        "microsoft_learn_hyperv",
        "nist_digital_twin_cybersecurity",
        "mitre_attack_ics",
        "factory_io_official_docs",
    }
    assert all(source["review_status"] == "approved" for source in sources)


def test_isaac_does_not_apply_to_default_ot_cyber_range():
    ot_sources = governed_sources_for_workload(
        "ot_cyber_range",
        include_pending_review=True,
    )
    assert "nvidia_omniverse_isaac_docs" not in {source["source_id"] for source in ot_sources}
    isaac_sources = governed_sources_for_workload(
        "isaac_sim",
        include_pending_review=True,
    )
    assert {source["source_id"] for source in isaac_sources} == {
        "nvidia_omniverse_isaac_docs"
    }


def test_emulate3d_source_may_be_researched_but_claim_authority_stays_pending():
    sources = governed_sources_for_workload("emulate3d")
    assert {source["source_id"] for source in sources} == {
        "rockwell_emulate3d_official_requirements"
    }
    source = sources[0]
    assert source["independent_review"]["status"].endswith("pending")
    assert source["tenant_allowlist"]["default"] == "deny"


def test_five_year_fleet_sources_are_explicit_candidates_not_blanket_authority():
    operational = governed_sources_for_workload("five_year_fleet")
    assert operational == ()
    candidates = governed_sources_for_workload(
        "five_year_fleet", include_pending_review=True,
    )
    assert {source["source_id"] for source in candidates} == {
        "ubuntu_certified_laptops",
        "lenovo_accessory_compatibility",
        "microsoft_windows_enterprise_lifecycle",
        "lenovo_product_security_advisories",
        "hp_warranty_status",
    }
    assert all(source["review_status"] == "pending_independent_human_review" for source in candidates)
    assert all("exact_product_fit" in source["forbidden_claim_types"] for source in candidates)
