import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.intent_resolver import resolve
from src.app.services.recommendation_core.turn_router import route_turn
from src.app.services.recommendation_core import workload_grounding as W


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
    assert result["evidence"][0]["identity_resolution"]["authority"] == "identity_candidate_only"
    assert result["evidence"][0]["compiled_requirements"] == []


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
        lambda entities, consent: {
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
