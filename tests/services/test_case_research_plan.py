from src.app.services.case_research_plan import (
    approved_sources_for_plan,
    build_case_research_plan,
)


def _source(source_id, workloads, artefacts, *, approved=True):
    return {
        "source_id": source_id, "publisher": source_id,
        "artefact_patterns": artefacts,
        "applicability": {
            "workloads": workloads, "scope": " ".join([*workloads, *artefacts]),
            "resolution_owner": "research",
        },
        "review_status": "approved" if approved else "pending_independent_human_review",
    }


def _manifest():
    return {"sources": [
        _source("ot", ["ot_cyber_range", "plc_simulation"], ["Factory I/O"]),
        _source("cgi", ["cgi", "blender_rendering"], ["Blender"], approved=False),
        _source("cad", ["large_3d_models", "point_cloud"], ["AutoCAD"], approved=False),
        _source("bim", ["bim", "large_bim_models"], ["Revit"], approved=False),
        _source("unreal", ["unreal_engine", "nanite", "lumen"], ["Unreal Engine"], approved=False),
    ]}


def test_planner_is_manifest_driven_and_makes_no_external_call():
    prompts = [
        "I do CGI; I don't want renders taking all night.",
        "I need CAD for very large 3D models and point-cloud work.",
        "I'm an architect working with large BIM models and real-time walkthroughs.",
        "I build Unreal Engine games with Nanite and Lumen.",
    ]
    expected = ["cgi", "cad", "bim", "unreal"]
    for prompt, source_id in zip(prompts, expected, strict=True):
        plan = build_case_research_plan(prompt, manifest=_manifest())
        assert plan is not None
        assert source_id in plan.source_candidate_ids
        assert plan.external_calls == 0
        assert plan.authority == "proposal_only"
        assert any(row.resolution_owner == "tenant_policy" for row in plan.obligations)


def test_approved_execution_sources_are_a_strict_subset_of_proposed_candidates():
    plan = build_case_research_plan(
        "PLC factory cyber simulation with CGI output", manifest=_manifest(),
    )
    assert plan is not None
    assert {row["source_id"] for row in approved_sources_for_plan(plan, manifest=_manifest())} == {"ot"}


def test_unrelated_normal_persona_does_not_open_external_research():
    assert build_case_research_plan(
        "I need a lightweight laptop for email and spreadsheets", manifest=_manifest(),
    ) is None


def test_plan_id_is_stable_and_case_content_bound():
    first = build_case_research_plan("Unreal Engine Nanite", manifest=_manifest())
    second = build_case_research_plan("Unreal Engine Nanite", manifest=_manifest())
    changed = build_case_research_plan("Unreal Engine Lumen", manifest=_manifest())
    assert first is not None and second is not None and changed is not None
    assert first.plan_id == second.plan_id
    assert first.plan_id != changed.plan_id
