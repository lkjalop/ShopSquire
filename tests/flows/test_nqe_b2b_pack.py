"""#7 — B2B procurement NQE pack (profile-driven, electronics adapter).

A bulk/fleet query should surface B2B procurement clarifiers (workload, OS/image, warranty-SLA,
manageability, docking, deployment) rather than only a consumer use-case question. The pack lives in
electronics.json (adapter) so the core NQE mechanism stays agnostic.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.app.flows.nqe import _load_nqe_question_packs


def _pack():
    packs = _load_nqe_question_packs()
    return packs.get("ask_b2b_procurement")


def test_b2b_pack_present_with_procurement_options():
    p = _pack()
    assert p, "ask_b2b_procurement must exist in the electronics profile"
    assert p.get("trigger_quantity_min") == 5
    values = {o["value"] for o in p.get("options", [])}
    # the procurement dimensions GPT-5.5 asked for
    assert {"workload", "os_standard", "warranty_sla", "manageability", "docking", "deployment"} <= values


def test_b2b_pack_triggers_on_fleet_language_not_personal():
    p = _pack()
    kws = [k.lower() for k in p.get("trigger_query_keywords", [])]
    assert any("fleet" in k or "for our team" in k or "procurement" in k for k in kws)
    skips = [k.lower() for k in p.get("skip_if_query_contains", [])]
    assert any("just me" in k or "for myself" in k or "personal" in k for k in skips)


def test_b2b_pack_keyword_matches_bulk_query():
    p = _pack()
    q = "i need ten work laptops for our team".lower()
    assert any(kw in q for kw in p.get("trigger_query_keywords", []))


def test_electronics_json_still_valid():
    json.loads(Path("config/store_profiles/electronics.json").read_text(encoding="utf-8"))


# ── propose-level: intent-aware firing + procurement-first prioritization ─────
def _engine():
    from src.app.flows.nqe import NextQuestionEngine
    from src.app.rag.retrieve import Retriever
    from src.app.flows.catalog import QuestionTemplateCatalog
    return NextQuestionEngine(Retriever(), QuestionTemplateCatalog())


def _ids(query, *, quantity=None, use_case=None):
    from src.app.flows.nqe import NQEInput
    inp = NQEInput(query=query, intent="recommend", product_category="laptop",
                   detected_use_case=use_case, order_quantity=quantity, answered_fields={})
    return [q.id for q in _engine().propose(inp)]


def test_b2b_intent_leads_procurement_question():
    ids = _ids("10 laptops for the company under $1500", quantity=10)
    assert ids and ids[0] == "ask_b2b_procurement"  # procurement leads over consumer questions


def test_ambiguous_bulk_also_surfaces_procurement():
    ids = _ids("I want 10 laptops", quantity=10)
    assert "ask_b2b_procurement" in ids


def test_b2b_clarification_survives_generic_convergence():
    from src.app.flows.nqe import NQEInput

    inp = NQEInput(
        query="I am thinking to buy 10 laptops for work in 2 weeks",
        intent="recommend",
        product_category="laptop",
        detected_use_case="office_general",
        order_quantity=10,
        missing_fields=["brand_preference", "b2b_requirements"],
        answered_fields={
            "budget_min": 1300,
            "budget_max": 1500,
            "use_case": "office_general",
        },
    )
    ids = [question.id for question in _engine().propose(inp)]
    assert "ask_b2b_procurement" in ids


def test_personal_multibuy_has_no_procurement_question():
    ids = _ids("3 laptops for my family", quantity=3)
    assert "ask_b2b_procurement" not in ids


def test_single_consumer_has_no_procurement_question():
    ids = _ids("a gaming laptop", quantity=1, use_case="gaming")
    assert "ask_b2b_procurement" not in ids
