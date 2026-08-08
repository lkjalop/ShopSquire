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
