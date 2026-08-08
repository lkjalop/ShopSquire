from src.app.services.official_workload_research import (
    compile_source_claims,
    ranking_delta,
)


def test_factory_io_parser_compiles_only_recognized_official_statements() -> None:
    claims, context = compile_source_claims(
        "factory_io_official_docs",
        b"<html><body>Operating System Windows 7 SP1+ or higher "
        b"CPU with SSE2 instruction set support Graphics API DX10, DX11, DX12 capable</body></html>",
        observed_at="2026-08-08T00:00:00Z",
        citation_url="https://docs.factoryio.com/manual/system-requirements/",
    )
    assert context == []
    assert {row["attribute"] for row in claims} == {
        "operating_system", "cpu_instruction_set", "graphics_api",
    }
    assert all(row["authority_status"] == "verified_official" for row in claims)
    assert not any(row["attribute"] in {"ram_gb", "gpu_vram_gb"} for row in claims)


def test_hyperv_parser_keeps_host_floor_separate_from_buyer_vm_scale() -> None:
    claims, _ = compile_source_claims(
        "microsoft_learn_hyperv",
        b"<p>Windows 11 Professional or Enterprise. A 64-bit processor with "
        b"second-level address translation. VM Monitor Mode Extensions. "
        b"Data Execution Prevention. Plan for at least 4 GB of RAM. "
        b"You need enough memory for all virtual machines.</p>",
        observed_at="2026-08-08T00:00:00Z",
        citation_url="https://learn.microsoft.com/hyper-v",
    )
    by_attribute = {row["attribute"]: row for row in claims}
    assert by_attribute["ram_gb"]["value"] == 4
    assert by_attribute["operating_system"]["operator"] == "one_of"
    assert "vm_count" not in by_attribute


def test_nist_scope_never_becomes_a_hardware_floor() -> None:
    claims, context = compile_source_claims(
        "nist_digital_twin_cybersecurity", b"<p>Digital Twin Technology</p>",
        observed_at="2026-08-08T00:00:00Z", citation_url="https://csrc.nist.gov/x",
    )
    assert claims == []
    assert context[0]["claim_type"] == "workload_scope"
    assert "does not establish a hardware floor" in context[0]["statement"]


def test_application_parsers_do_not_share_claims_across_publishers() -> None:
    observed_at = "2026-08-08T00:00:00Z"
    blender, _ = compile_source_claims(
        "blender_official_requirements", b"Recommended 32 GB RAM and 8 GB VRAM",
        observed_at=observed_at, citation_url="https://www.blender.org/download/requirements/",
    )
    epic, _ = compile_source_claims(
        "epic_unreal_engine_requirements",
        b"Recommended hardware: 32 GB RAM, 8 GB or more Graphics RAM, DirectX 12",
        observed_at=observed_at, citation_url="https://dev.epicgames.com/documentation/x",
    )
    autocad, _ = compile_source_claims(
        "autodesk_autocad_requirements", b"Recommended 32 GB RAM; DirectX 12 capable GPU",
        observed_at=observed_at, citation_url="https://help.autodesk.com/view/ACD/2026/ENU/",
    )
    assert {row["attribute"] for row in blender} == {"ram_gb", "gpu_vram_gb"}
    assert {row["attribute"] for row in epic} == {"ram_gb", "gpu_vram_gb", "graphics_api"}
    assert {row["attribute"] for row in autocad} == {"ram_gb", "graphics_api"}
    assert all(row["source_id"] == "blender_official_requirements" for row in blender)
    assert all(row["source_id"] == "epic_unreal_engine_requirements" for row in epic)
    assert all(row["source_id"] == "autodesk_autocad_requirements" for row in autocad)


def test_unregistered_source_parser_cannot_create_claims() -> None:
    claims, context = compile_source_claims(
        "search_snippet", b"32 GB RAM and 16 GB VRAM is perfect",
        observed_at="2026-08-08T00:00:00Z", citation_url="https://search.invalid/",
    )
    assert claims == []
    assert context == []


def test_autocad_point_cloud_tier_keeps_scope_and_workstation_requirement() -> None:
    claims, _ = compile_source_claims(
        "autodesk_autocad_requirements",
        b"Additional Requirements for large datasets, point clouds, and 3D modeling. "
        b"Memory 32 GB RAM or more. Display Card 12 GB VRAM or greater; "
        b"DirectX-capable workstation class graphics card.",
        observed_at="2026-08-08T00:00:00Z",
        citation_url="https://www.autodesk.com/support/technical/article/point-cloud",
    )
    by_attribute = {row["attribute"]: row for row in claims}
    assert by_attribute["gpu_vram_gb"]["value"] == 12
    assert by_attribute["gpu_vram_gb"]["condition"] == (
        "large datasets, point clouds, or 3D modelling"
    )
    assert by_attribute["gpu_class"]["value"] == "workstation"
    assert by_attribute["gpu_class"]["requirement_class"] == "target"


def test_ranking_delta_reports_movement_without_inventing_a_reason() -> None:
    before = {"shelves": [{"shelf_id": "shared", "initial": [
        {"product": {"sku": "A"}}, {"product": {"sku": "B"}},
    ], "next_page": []}]}
    after = {"shelves": [{"shelf_id": "shared", "initial": [
        {"product": {"sku": "B"}}, {"product": {"sku": "A"}},
    ], "next_page": []}]}
    rows = ranking_delta(before, after)
    assert {(row["sku"], row["before"], row["after"]) for row in rows} == {
        ("A", 1, 2), ("B", 2, 1),
    }
