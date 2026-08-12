from src.app.services.case_research_plan import (
    approved_sources_for_plan,
    build_case_research_plan,
)


def test_adjacent_enrolled_applications_become_open_world_not_false_authority():
    plan = build_case_research_plan(
        "I need a laptop for drone photogrammetry, GIS and very large 3D models.",
    )

    assert plan is not None
    assert plan.publisher_status == "unresolved"
    assert plan.source_candidate_ids == []
    assert [row.hypothesis_id for row in plan.hypotheses] == ["open_world_workload"]


def test_named_application_keeps_its_enrolled_publisher_scope():
    plan = build_case_research_plan(
        "I need a laptop for Blender rendering and large scenes.",
    )

    assert plan is not None
    assert plan.publisher_status == "resolved_enrolled"
    assert "blender_official_requirements" in plan.source_candidate_ids


def test_real_manifest_preserves_governed_scope_hypotheses_for_six_prompt_matrix():
    expected = {
        "I do CGI; I don't want renders taking all night.": {"blender_official_requirements"},
        "I need CAD for very large 3D models and point-cloud work.": {"autodesk_autocad_requirements"},
        "I'm an architect working with large BIM models and real-time walkthroughs.": {"autodesk_revit_requirements"},
        "I need to simulate a PLC-controlled factory and cyberattacks against the OT network.": {
            "factory_io_official_docs", "mitre_attack_ics",
        },
    }
    for prompt, required_sources in expected.items():
        plan = build_case_research_plan(prompt)
        assert plan is not None
        assert plan.publisher_status == "resolved_enrolled"
        assert required_sources <= set(plan.source_candidate_ids)


def test_scope_aliases_are_manifest_governed_and_paraphrase_stable():
    prompts = (
        "Recommend portable hardware for computer-generated imagery and 3D rendering.",
        "I work on point cloud datasets in CAD and need a mobile computer.",
        "Need a notebook for building information modelling on large projects.",
    )
    expected = (
        "blender_official_requirements",
        "autodesk_autocad_requirements",
        "autodesk_revit_requirements",
    )
    for prompt, source_id in zip(prompts, expected, strict=True):
        plan = build_case_research_plan(prompt)
        assert plan is not None
        assert source_id in plan.source_candidate_ids


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


def test_open_world_plan_has_no_invented_publisher_and_bounded_query_axes():
    plan = build_case_research_plan(
        "I need vendor-certified hardware for a novel multiphysics solver",
        manifest=_manifest(),
        allow_open_world=True,
    )
    assert plan is not None
    assert plan.publisher_status == "unresolved"
    assert plan.source_candidate_ids == []
    assert plan.hypotheses[0].source_ids == []
    assert 2 <= len(plan.discovery_queries) <= 3
    assert len({row.axis for row in plan.discovery_queries}) == len(plan.discovery_queries)
    assert all(row.query for row in plan.discovery_queries)
    assert all("I need" not in row.query for row in plan.discovery_queries)
    assert any(row.resolution_owner == "research" for row in plan.obligations)


def test_open_world_queries_drop_negated_preferences_and_buyer_filler():
    plan = build_case_research_plan(
        "I edit 8K RAW video and do colour-critical grading. "
        "I do not care about gaming FPS. Which laptop should I buy?",
        manifest=_manifest(),
        allow_open_world=True,
    )
    assert plan is not None
    queries = " ".join(row.query.lower() for row in plan.discovery_queries)
    assert "8k" in queries
    assert "raw" in queries
    assert "colour" in queries
    assert "gaming" not in queries
    assert "fps" not in queries
    assert "should" not in queries
    assert " buy " not in f" {queries} "


def test_generic_requirements_phrase_cannot_invent_an_unrelated_workload():
    manifest = {"sources": [
        _source("factory", ["factory_io", "plc_simulation"], ["Factory I/O", "System Requirements"]),
        _source("blender", ["cgi", "blender_rendering"], ["Blender", "System Requirements"]),
    ]}
    plan = build_case_research_plan(
        "I need a laptop that meets Factory I/O system requirements",
        manifest=manifest,
    )
    assert plan is not None
    assert plan.source_candidate_ids == ["factory"]
    assert [row.source_ids for row in plan.hypotheses] == [["factory"]]


def test_plan_id_is_stable_and_case_content_bound():
    first = build_case_research_plan("Unreal Engine Nanite", manifest=_manifest())
    second = build_case_research_plan("Unreal Engine Nanite", manifest=_manifest())
    changed = build_case_research_plan("Unreal Engine Lumen", manifest=_manifest())
    assert first is not None and second is not None and changed is not None
    assert first.plan_id == second.plan_id
    assert first.plan_id != changed.plan_id


def test_source_activation_policy_prevents_digital_twin_from_inventing_cyber_scope():
    manifest = {"sources": [
        {
            **_source("context", ["digital_twin", "ot_cyber_range"], ["Digital Twins"]),
            "applicability": {
                "workloads": ["digital_twin", "ot_cyber_range"],
                "scope": "Digital-twin concept and cybersecurity context",
                "resolution_owner": "research",
            },
            "activation_policy": {
                "required_any_terms": ["cyber", "cybersecurity", "security", "attack"],
            },
        },
        _source(
            "manufacturing", ["manufacturing_digital_twin", "predictive_maintenance"],
            ["Digital Twins", "predictive maintenance"],
        ),
    ]}
    predictive = build_case_research_plan(
        "Digital-twin simulation of factory equipment and predicting breakdowns",
        manifest=manifest,
    )
    assert predictive is not None
    assert predictive.source_candidate_ids == ["manufacturing"]

    cyber = build_case_research_plan(
        "Digital-twin OT cyber attack simulation", manifest=manifest,
    )
    assert cyber is not None
    assert "context" in cyber.source_candidate_ids
