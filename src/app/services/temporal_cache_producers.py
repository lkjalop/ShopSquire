"""Concrete durable CacheRAG content producers.

A rebuild succeeds only after content is published to a shared cache backend
under the exact key derived from its sealed request and authority contract.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from src.app.services.semantic_cache import CacheContract, SemanticCache


def rebuild_agentic_rag_retrieval(
    job: dict[str, Any], *, cache: SemanticCache | None = None,
) -> dict[str, Any]:
    from src.app.services import agentic_rag_pipeline as rag

    target_cache = cache or rag._RAG_CACHE
    if not target_cache.is_shared_backend:
        raise RuntimeError("shared_cache_backend_required")
    payload = job.get("rebuild_payload")
    if not isinstance(payload, dict) or payload.get("schema_version") != "shopsquire.cache-rebuild.v1":
        raise ValueError("sealed_rebuild_payload_required")
    if payload.get("namespace") != "agentic_rag_retrieval":
        raise ValueError("cache_rebuild_namespace_mismatch")
    request = payload.get("request")
    contract_payload = payload.get("contract")
    if not isinstance(request, dict) or not isinstance(contract_payload, dict):
        raise ValueError("cache_rebuild_contract_required")
    contract = CacheContract(**contract_payload)
    if contract.tenant_id != str(job.get("tenant_id") or ""):
        raise PermissionError("cache_rebuild_tenant_mismatch")
    if contract.corpus_version != str(job.get("source_version") or ""):
        raise ValueError("cache_rebuild_source_version_mismatch")
    expected_key = contract.cache_key("agentic_rag_retrieval", request)
    if expected_key != str(job.get("cache_key") or ""):
        raise ValueError("cache_rebuild_key_mismatch")
    plan = rag.PlanOutput.model_validate(request)
    value = rag._retrieve(plan).model_dump()
    storage_key = target_cache.set_versioned(
        namespace="agentic_rag_retrieval",
        request=request,
        contract=contract,
        value=value,
        source_id="faq_bank",
        trust_score=0.78,
    )
    published = target_cache.get_versioned(
        namespace="agentic_rag_retrieval",
        request=request,
        contract=contract,
        min_trust=0.7,
    )
    if not isinstance(published, dict):
        raise RuntimeError("cache_rebuild_publish_verification_failed")
    content_hash = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"storage_key": storage_key, "content_hash": content_hash, "published": True}


def default_rebuild_handler(namespace: str):
    if str(namespace).lower() == "agentic_rag_retrieval":
        return rebuild_agentic_rag_retrieval
    return None
