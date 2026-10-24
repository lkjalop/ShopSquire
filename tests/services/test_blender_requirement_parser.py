from src.app.services.official_workload_research import compile_source_claims
from src.app.services.recommendation_core.requirement_scope import accepted_requirement_gaps


def parse(content):
    return compile_source_claims(
        "blender_official_requirements", content.encode(),
        observed_at="2026-09-25T00:00:00Z",
        citation_url="https://www.blender.org/download/requirements/",
    )[0]


def table(platform, rows):
    return (f"<details><summary>{platform}</summary><table>"
            "<tr><th></th><th>Minimum</th><th>Recommended</th></tr>"
            + rows + "</table></details>")


def test_table_keeps_ram_label_tiers_platforms_and_exact_excerpt():
    rows = "<tr><td>RAM</td><td>8 GB</td><td>32 GB</td></tr>"
    claims = parse(table("Windows", rows) + table("macOS", rows))
    assert len({row["claim_id"] for row in claims}) == 4
    assert [(r["platform"], r["requirement_class"], r["value"]) for r in claims] == [
        ("Windows", "minimum", 8), ("Windows", "recommended", 32),
        ("macOS", "minimum", 8), ("macOS", "recommended", 32),
    ]
    assert claims[1]["source_excerpt"] == "32 GB"
    assert claims[1]["page_section"] == "Windows / recommended / RAM"
    assert claims[1]["artefact_version"] is None
    assert accepted_requirement_gaps(claims, tenant_id="default") == ["manifest_scope_missing"]


def test_numeric_memory_does_not_invent_graphics_or_instruction_compatibility():
    claims = parse(table("Windows", """
        <tr><td>CPU</td><td>4 cores with SSE4.2 support</td><td>8 cores</td></tr>
        <tr><td>GPU</td><td>2 GB VRAM with <strong>OpenGL 4.3</strong>, Vulkan 1.3</td><td>8 GB VRAM</td></tr>
    """))
    assert {r["attribute"] for r in claims} == {"cpu_cores", "gpu_vram_gb"}
    assert "SSE4.2" in claims[0]["source_excerpt"]
    assert "OpenGL 4.3" in claims[2]["source_excerpt"]


def test_unscoped_prose_unknown_platform_or_changed_table_schema_abstains():
    assert parse("Recommended 32 GB RAM and 8 GB VRAM") == []
    rows = "<tr><td>RAM</td><td>8 GB</td><td>32 GB</td></tr>"
    assert parse(table("Unreviewed platform", rows)) == []
    assert parse(table("Windows", rows).replace("Recommended", "Maximum")) == []


def test_platform_does_not_leak_to_a_later_unscoped_table():
    scoped = table("Windows", "<tr><td>RAM</td><td>8 GB</td><td>32 GB</td></tr>")
    unscoped = "<table><tr><th></th><th>Minimum</th><th>Recommended</th></tr><tr><td>RAM</td><td>64 GB</td><td>128 GB</td></tr></table>"
    assert len(parse(scoped + unscoped)) == 2
