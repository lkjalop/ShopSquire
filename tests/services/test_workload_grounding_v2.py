import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.intent_resolver import resolve
from src.app.services.recommendation_core.turn_router import route_turn
from src.app.services.recommendation_core import workload_grounding as W


def test_provider_projection_preserves_categories_and_both_bounds(monkeypatch):
    from types import SimpleNamespace
    from src.app.services.recommendation_core.research_contracts import CompiledRequirement
    from src.app.services.recommendation_core.requirement_compiler import CompilationResult
    provider = SimpleNamespace(
        provider_ids_for=lambda kind: ["fixture"],
        resolve_with_trace=lambda *args, **kwargs: (
            SimpleNamespace(to_dict=lambda: {"source": "fixture"}), []),
    )
    monkeypatch.setattr("src.app.services.connectors.workload_evidence.default_registry", lambda: provider)
    claims = tuple(CompiledRequirement(
        attribute_key=key, operator=op, value=value, source_claim_ids=[f"fixture-{i}"],
    ) for i, (key, op, value) in enumerate([
        ("os", "=", "Windows 11"), ("ram_gb", ">=", 16), ("ram_gb", "<=", 32),
    ]))
    monkeypatch.setattr(W, "compile_workload_evidence_requirements",
                        lambda *args, **kwargs: CompilationResult(claims, ()))
    result = W.resolve_named_workloads([("software", "Fixture workload")], consent=False)
    assert result["requirements"] == {
        "os": [("=", "Windows 11")], "ram_gb": [(">=", 16), ("<=", 32)],
    }
    from src.app.services.recommendation_core.constraints import from_op_map
    constraints = from_op_map(result["requirements"], "fixture")
    assert constraints["ram_gb"].lower == 16
    assert constraints["ram_gb"].upper == 32


def test_translated_gpu_threshold_cannot_become_official_requirement(monkeypatch):
    monkeypatch.setattr(
        "src.app.services.gpu_translation.desktop_req_to_laptop_tier",
        lambda value: {"vram_gb_min": 4},
    )
    result = W.compile_workload_evidence_requirements({
        "source": "steam", "app_id": "test-app", "confidence": 1,
        "retrieved_at": "2026-09-07T00:00:00Z",
        "minimum": {"ram_gb": 16, "gpu": "Example GPU 6 GB"},
    }, kind="game", name="Unseen software")
    assert {row.attribute_key for row in result.requirements} == {"ram_gb"}
    rejected = next(row for row in result.rejections if row["attribute_key"] == "gpu_vram_gb")
    assert rejected["reason"] == "derived_claim_requires_policy"
    assert rejected["source_excerpt"] == "Example GPU 6 GB"


@pytest.fixture()
def db():
    session = sessionmaker(bind=create_engine("sqlite://"))()
    session.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, "
        "name TEXT NOT NULL, price_cents INT NOT NULL, currency TEXT DEFAULT 'USD', "
        "specs TEXT, brand TEXT, active INTEGER DEFAULT 1, updated_at TEXT)"))
    session.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
        "('p1','GAME-1','Gaming Laptop',199900,:specs,'Asus')"),
        {"specs": json.dumps({"ram_gb": 32, "gpu_vram_gb": 12, "storage_gb": 1024})})
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification
    add_sold_node(session, node_handle="el-6-11-2")
    upsert_classification(
        session, sku="GAME-1", node_handle="el-6-11-2",
        source="test", status="approved")
    yield session
    session.close()


def test_live_steam_requires_consent_flag_and_enrolled_source(monkeypatch):
    monkeypatch.setenv("STEAM_REQUIREMENTS_LIVE_ENABLED", "1")
    monkeypatch.setattr(
        "src.app.platform.store_profile.profile_slot",
        lambda key, default=None: ["store.steampowered.com"]
        if key == "external_research_allowlist" else default,
    )
    assert W.live_steam_allowed(consent=True) is True
    assert W.live_steam_allowed(consent=False) is False
    monkeypatch.setenv("STEAM_REQUIREMENTS_LIVE_ENABLED", "0")
    assert W.live_steam_allowed(consent=True) is False


def test_named_game_evidence_merges_minimums_not_recommended(monkeypatch):
    monkeypatch.setattr(W, "live_steam_allowed", lambda consent: bool(consent))
    monkeypatch.setattr(
        "src.app.services.connectors.steam_requirements.get_game_requirements",
        lambda title, allow_live=False: {
            "title": "Alan Wake 2",
            "appid": 1087100,
            "publisher": "Remedy Entertainment",
            "release_state": "released",
            "release_date": "2023-10-27",
            "requirements_completeness": "complete",
            "minimum": {"ram_gb": 16, "storage_gb": 90, "gpu": "RTX 2060 6GB"},
            "recommended": {"ram_gb": 32, "storage_gb": 90, "gpu": "RTX 4070 12GB"},
            "source": "steam",
            "source_url": "https://store.steampowered.com/app/1087100/",
            "retrieved_at": "2026-07-26T00:00:00+00:00",
            "cached": False,
        },
    )
    result = resolve(
        ["gaming"],
        query="laptop for Alan Wake 2",
        vertical="electronics",
        workload_entities=[("game", "Alan Wake 2")],
        external_research_consent=True,
    )
    assert result["requirements"]["ram_gb"] == [(">=", 16.0)]
    assert result["requirements"]["storage_gb"] == [(">=", 512.0)]
    assert result["requirements"]["gpu_vram_gb"][0][1] >= 4
    evidence = result["title_requirements"]["external_workload_evidence"]
    assert evidence["live_allowed"] is True
    assert evidence["consent_recorded"] is True
    assert evidence["items"][0]["source"] == "steam"
    assert evidence["items"][0]["canonical_title"] == "Alan Wake 2"
    assert evidence["items"][0]["publisher"] == "Remedy Entertainment"
    assert evidence["items"][0]["app_id"] == "1087100"
    assert evidence["items"][0]["release_state"] == "released"
    assert evidence["items"][0]["release_date"] == "2023-10-27"
    assert evidence["items"][0]["requirements_completeness"] == "complete"


def test_identity_without_material_requirements_stays_unresolved(monkeypatch):
    monkeypatch.setattr(W, "live_steam_allowed", lambda consent: bool(consent))
    monkeypatch.setattr(
        "src.app.services.connectors.steam_requirements.get_game_requirements",
        lambda title, allow_live=False: {
            "title": "Heroes of Might and Magic III Remake",
            "appid": 3809850,
            "minimum": {"ram_gb": None, "storage_gb": None, "gpu": None, "os": "Windows 11"},
            "recommended": {"ram_gb": None, "storage_gb": None, "gpu": None, "os": "Windows 11"},
            "source": "steam",
            "source_url": "https://store.steampowered.com/app/3809850/",
            "retrieved_at": "2026-08-28T00:00:00+00:00",
            "cached": False,
            "identity_resolution": {
                "requested_name": title,
                "resolved_name": "Heroes of Might and Magic III Remake",
                "authority": "identity_candidate_only",
                "confidence": 1.0,
            },
        },
    )

    result = W.resolve_named_workloads(
        [("game", "the new remastered heroes of might and magic 3")],
        consent=True,
    )

    assert result["requirements"] == {}
    assert result["evidence"][0]["status"] == "identity_resolved_requirements_incomplete"
    assert result["evidence"][0]["resolved_name"] == "Heroes of Might and Magic III Remake"
    assert result["evidence"][0]["canonical_title"] == "Heroes of Might and Magic III Remake"
    assert result["evidence"][0]["app_id"] == "3809850"
    assert result["evidence"][0]["identity_resolution"]["authority"] == "identity_candidate_only"
    assert result["evidence"][0]["compiled_requirements"] == []


def test_cited_identity_is_requeried_through_structured_provider(monkeypatch):
    """An unknown raw phrase must be retried with the cited canonical title."""

    calls = []
    monkeypatch.setattr(W, "live_steam_allowed", lambda consent: bool(consent))
    monkeypatch.setattr(
        "src.app.services.connectors.steam_requirements.get_game_requirements",
        lambda title, allow_live=False: calls.append((title, allow_live)) or {
            "title": "MIO: Memories in Orbit",
            "appid": 1672810,
            "publisher": "Focus Entertainment",
            "release_state": "released",
            "release_date": "20 Jan, 2026",
            "requirements_completeness": "minimum_and_recommended",
            "minimum": {"ram_gb": 8, "storage_gb": 15, "gpu": "GTX 960 4GB"},
            "recommended": {"ram_gb": 16, "storage_gb": 15, "gpu": "RTX 2060 6GB"},
            "source": "steam",
            "source_url": "https://store.steampowered.com/app/1672810/",
            "retrieved_at": "2026-09-02T00:00:00+00:00",
            "cached": False,
        },
    )

    result = W.resolve_canonical_workload_identity(
        {
            "status": "resolved",
            "identity": {"canonical_title": "MIO: Memories in Orbit"},
        },
        workload_kind_hints=["game"],
        consent=True,
    )

    assert calls == [("MIO: Memories in Orbit", True)]
    assert result["status"] == "resolved"
    assert result["evidence"][0]["app_id"] == "1672810"
    assert result["evidence"][0]["requirements_completeness"] == "minimum_and_recommended"
    assert result["requirements"]["ram_gb"] == [(">=", 8.0)]


def test_canonical_retry_fans_out_enrolled_provider_kinds_when_router_omits_kind(monkeypatch):
    calls = []
    monkeypatch.setattr(
        W, "resolve_named_workloads",
        lambda entities, consent, product_type: calls.append((list(entities), consent)) or {
            "requirements": {}, "evidence": [], "live_allowed": False,
        },
    )

    result = W.resolve_canonical_workload_identity(
        {"status": "resolved", "identity": {"canonical_title": "Unknown Product"}},
        workload_kind_hints=[],
        consent=True,
    )

    assert calls == [([
        ("game", "Unknown Product"), ("software", "Unknown Product"),
    ], True)]
    assert result["status"] == "not_resolved"
    assert result["failure_code"] == "structured_provider_no_authoritative_result"


def test_cited_steam_origin_supplies_provider_kind_after_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(
        W,
        "resolve_named_workloads",
        lambda entities, consent, product_type: calls.append((list(entities), consent)) or {
            "requirements": {"ram_gb": (">=", 16.0)},
            "evidence": [{
                "status": "resolved",
                "compiled_requirements": [{"attribute_key": "ram_gb"}],
            }],
            "live_allowed": True,
        },
    )

    result = W.resolve_canonical_workload_identity(
        {
            "status": "resolved",
            "identity": {"canonical_title": "The Blood of Dawnwalker"},
            "cited_rows": [{
                "url": "https://store.steampowered.com/app/3751260/",
                "registrable_domain": "store.steampowered.com",
            }],
        },
        workload_kind_hints=[],
        consent=True,
    )

    assert calls == [([("game", "The Blood of Dawnwalker")], True)]
    assert result["status"] == "resolved"


def test_canonical_retry_recovers_from_wrong_model_provider_kind(monkeypatch):
    calls = []

    def resolve(entities, consent, product_type):
        bounded = list(entities)
        calls.append((bounded, consent))
        if bounded[0][0] == "game":
            return {
                "requirements": {"ram_gb": (">=", 16.0)},
                "evidence": [{
                    "kind": "game", "status": "resolved",
                    "compiled_requirements": [{"attribute_key": "ram_gb"}],
                }],
                "live_allowed": True,
            }
        return {
            "requirements": {},
            "evidence": [{"kind": "software", "status": "not_resolved"}],
            "live_allowed": False,
        }

    monkeypatch.setattr(W, "resolve_named_workloads", resolve)
    result = W.resolve_canonical_workload_identity(
        {"status": "resolved", "identity": {"canonical_title": "Novel Product"}},
        workload_kind_hints=["software"], consent=True,
    )

    assert calls == [
        ([("software", "Novel Product")], True),
        ([("game", "Novel Product")], True),
    ]
    assert result["status"] == "resolved"
    assert result["provider_kind_fallback_used"] is True


def test_router_repairs_omitted_named_workload_without_title_rules(db):
    calls = []

    def model(prompt, _timeout):
        calls.append(prompt)
        if prompt.startswith("NAMED WORKLOAD COVERAGE REPAIR"):
            return json.dumps({
                "workload_entity": {"kind": "game", "name": "PRAGMATA"},
            })
        return json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-11-2",
            "use_cases": ["gaming"],
            "subject_role": "RUN_SUBJECT_ON_PRODUCT",
            "confidence": 0.9,
        })

    decision = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query="Could a laptop under AUD 2,500 run PRAGMATA at 1080p?",
            uid="coverage-repair-user",
        ),
        llm_fn=model,
    )

    assert len(calls) == 2
    assert decision.workload_entities == (("game", "PRAGMATA"),)
    assert decision.model_proposal["entity_frame"]["identity"] == "PRAGMATA"


def test_router_repairs_missing_entity_frame_for_literal_model_workload(db):
    def model(prompt, _timeout):
        if prompt.startswith("NAMED WORKLOAD COVERAGE REPAIR"):
            return json.dumps({
                "workload_entity": {"kind": "game", "name": "PRAGMATA"},
            })
        return json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-11-2",
            "use_cases": ["gaming"],
            "workload_entities": [{"kind": "software", "name": "PRAGMATA"}],
            "confidence": 0.9,
        })

    decision = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query="Could a laptop under AUD 2,500 run PRAGMATA at 1080p?",
            uid="coverage-frame-repair-user",
        ),
        llm_fn=model,
    )

    assert decision.workload_entities == (("game", "PRAGMATA"),)
    assert decision.model_proposal["entity_frame"]["buyer_span"] == "PRAGMATA"


def test_router_rejects_repaired_workload_not_copied_from_buyer(db):
    def model(prompt, _timeout):
        if prompt.startswith("NAMED WORKLOAD COVERAGE REPAIR"):
            return json.dumps({
                "workload_entity": {"kind": "game", "name": "Cyberpunk 2077"},
            })
        return json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-11-2",
            "use_cases": ["gaming"],
            "subject_role": "RUN_SUBJECT_ON_PRODUCT",
            "confidence": 0.9,
        })

    decision = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query="Could a laptop run a newly announced game?",
            uid="coverage-repair-reject-user",
        ),
        llm_fn=model,
    )

    assert decision.workload_entities == ()


def test_router_accepts_only_literal_workload_entities(db):
    model = {
        "lane": "SEARCH",
        "handle": "el-6-11-2",
        "use_cases": ["gaming"],
        "workload_entities": [
            {"kind": "game", "name": "Alan Wake 2"},
            {"kind": "game", "name": "Cyberpunk 2077"},
            {"kind": "url", "name": "Alan Wake 2"},
        ],
        "confidence": 0.9,
    }
    decision = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query="I need a laptop for Alan Wake 2", uid="grounding-user"),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )
    assert decision.workload_entities == (("game", "Alan Wake 2"),)
    assert decision.model_proposal["workload_entities"][1]["name"] == "Cyberpunk 2077"
    assert "workload_entities:clamped" in decision.authorization_changes


def test_model_workload_entity_suppresses_legacy_title_detector(monkeypatch):
    monkeypatch.setattr(
        "src.app.services.recommendation_core.intent_resolver._salvage_title_requirements",
        lambda _query: (_ for _ in ()).throw(AssertionError("legacy detector ran")),
    )
    monkeypatch.setattr(
        W, "resolve_named_workloads",
        lambda entities, consent, product_type: {
            "requirements": {"ram_gb": (">=", 24.0)},
            "evidence": [{"kind": "game", "status": "resolved"}],
            "live_allowed": False,
        },
    )

    result = resolve(
        ["gaming"], query="laptop for a named game",
        workload_entities=[("game", "Named Game")],
    )

    assert result["requirements"]["ram_gb"] == [(">=", 24.0)]
    assert result["title_requirements"]["resolution_mode"] == "provider_registry"


def test_unsupported_named_software_remains_explicitly_unresolved():
    result = W.resolve_named_workloads(
        [("software", "Siemens NX 2025")], consent=True,
    )

    assert result["requirements"] == {}
    evidence = result["evidence"][0]
    assert evidence == {
        "kind": "software",
        "requested_name": "Siemens NX 2025",
        "status": "not_resolved",
        "live_allowed": result["live_allowed"],
        "reason": "no_enrolled_provider_result",
            "provider_attempts": [],
            "provider_coverage": "none_for_kind",
            "enrolled_providers": [],
        }
