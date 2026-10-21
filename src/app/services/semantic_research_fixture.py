"""Versioned, simulation-only concept research fixtures.

Fixtures exercise the complete provenance and trace contract without external credentials.  They
never impersonate live search or independent source approval, and therefore cannot grant catalog
or commercial authority unless a separately reviewed source policy replaces the pending policy.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "config" / "research_fixtures"


@lru_cache(maxsize=16)
def _load_fixture(fixture_id: str) -> dict[str, Any] | None:
    safe_id = "".join(char for char in str(fixture_id or "") if char.isalnum() or char in "-_" )
    if not safe_id:
        return None
    path = (_FIXTURE_ROOT / f"{safe_id}.json").resolve()
    if path.parent != _FIXTURE_ROOT.resolve() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def resolve_fixture(concept: str, *, authorized: bool = False, tenant_id: str | None = None) -> dict[str, Any] | None:
    enabled = str(os.getenv("SEMANTIC_RESEARCH_FIXTURES_ENABLED", "")).lower() in {
        "1", "true", "yes", "on",
    }
    fixture_id = str(os.getenv("SEMANTIC_RESEARCH_FIXTURE_ID", "")).strip()
    if not enabled or not fixture_id:
        return None
    if str(os.getenv('APP_ENV','local')).lower() not in {'local','dev','development','test','testing'}:
        return None
    runtime_path = os.getenv('SEMANTIC_RESEARCH_FIXTURE_PATH')
    if runtime_path:
        # Deployment-selected fixture file, never a path from chat or a source.
        try:
            path=Path(runtime_path)
            if path.stat().st_size>128_000:return None
            fixture=json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(fixture,dict) or fixture.get('simulation_only') is not True:
            return None
        if not fixture.get('tenant_ids') or fixture.get('requires_explicit_consent') is not True:
            return None
    else:
        fixture = _load_fixture(fixture_id)
    if not fixture:
        return None
    if fixture.get('tenant_ids') and tenant_id not in fixture['tenant_ids']:
        return None
    if fixture.get("requires_explicit_consent") is True and not authorized:
        return None
    normalized = " ".join(str(concept or "").lower().split())
    triggers = [" ".join(str(item).lower().split()) for item in fixture.get("concept_triggers") or []]
    if triggers and not any(trigger and trigger in normalized for trigger in triggers):
        return None
    query_template = str(fixture.get("query_template") or "{concept} requirements compatibility")
    query = query_template.format(concept=str(concept or "").strip()[:120])[:300]
    items = [dict(item) for item in fixture.get("sources") or [] if isinstance(item, dict)][:6]
    return {
        "status": "simulation_fixture",
        "concept": str(concept or "")[:120],
        "query": query,
        "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
        "provider_id": f"deterministic_fixture:{fixture_id}",
        "provider_run_status": "fixture_replay",
        "cache_status": "versioned_fixture",
        "source_status": {
            "status": "simulation_only",
            "hit_count": len(items),
            "fixture_version": fixture.get("fixture_version"),
            "latency_ms": 0,
        },
        "items": items,
        "claims": [dict(item,simulation_only=True) for item in fixture.get('claims') or []
                   if isinstance(item,dict)][:64],
        "normalized_evidence": [
            dict(item) for item in fixture.get("normalized_evidence") or []
            if isinstance(item, dict)
        ][:12],
        "catalog_qualifications": [
            dict(item) for item in fixture.get("catalog_qualifications") or []
            if isinstance(item, dict)
        ][:100],
        "authority": str(fixture.get("result_authority") or "simulation_candidate_only"),
        "simulation_only": True,
    }
