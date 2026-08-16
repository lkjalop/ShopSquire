"""Freeze the remaining direct model-network debt so it can only shrink."""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEGACY_DIRECT_MODEL_CALLERS = {
    "src/app/main.py",
    "src/app/bootstrap/runtime_lifecycle.py",
    "src/app/services/cv_vision_ollama.py",
    "src/app/services/llm_provider.py",
    "src/app/services/llm_providers.py",
    "src/app/services/model_residency.py",
    "src/app/services/nlp_contract.py",
    "src/app/services/ollama_client.py",
    "src/app/services/vision_reasoning.py",
    "src/app/workers/rq_queue.py",
}


@lru_cache(maxsize=1)
def _direct_model_callers() -> frozenset[str]:
    found: set[str] = set()
    for path in (ROOT / "src" / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8", errors="ignore")
        if "/api/generate" not in source and "chat/completions" not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_source = ast.get_source_segment(source, node) or ""
            if "/api/generate" in call_source or "chat/completions" in call_source:
                found.add(path.relative_to(ROOT).as_posix())
                break
    return frozenset(found)


def test_direct_model_network_debt_cannot_grow_or_hide():
    """Changing this set requires migrating a caller, never adding an exception."""

    assert _direct_model_callers() == LEGACY_DIRECT_MODEL_CALLERS


def test_recently_migrated_business_roles_do_not_bypass_gateway():
    direct = _direct_model_callers()
    assert not direct.intersection({
        "src/app/services/catalog_classifier.py",
        "src/app/services/llm_planner.py",
        "src/app/services/market_digest.py",
        "src/app/services/multi_intent_live.py",
        "src/app/services/open_world_query_proposal.py",
        "src/app/services/portfolio_narration_preview.py",
        "src/app/services/fulfillment/supplier_polish.py",
        "src/app/services/recommendation_core/cart_resolver.py",
        "src/app/services/recommendation_core/turn_router.py",
        "src/app/services/cv_ocr.py",
        "src/app/services/product_identity_agent.py",
        "src/app/services/recommend_intent_router.py",
    })
