"""Merchant Intelligence API — user profiles, behavioral models, citation stats.

Exposes endpoints for the merchant dashboard to view returning customer data,
agent learning stats, and observation analytics.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER


router = APIRouter(prefix="/api/v1/merchant/intelligence", tags=["merchant", "intelligence"])


@router.get("/user_profiles/{user_id}")
def get_user_profile(
    user_id: str,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Retrieve a user profile for the merchant dashboard."""
    try:
        from src.app.services.episodic_memory import EpisodicMemory
        from src.app.services.memory import Memory
        from src.app.deps import get_redis

        mem = Memory(get_redis())
        em = EpisodicMemory(mem)
        profile = em.get_user_profile(user_id)
        if not profile:
            return {"user_id": user_id, "found": False}
        from dataclasses import asdict
        data = asdict(profile)
        data["found"] = True
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user_profiles/{user_id}/behavioral_model")
def get_behavioral_model(
    user_id: str,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Build and return behavioral model for a returning customer."""
    try:
        from src.app.services.episodic_memory import EpisodicMemory
        from src.app.services.memory import Memory
        from src.app.deps import get_redis

        mem = Memory(get_redis())
        em = EpisodicMemory(mem)
        return em.build_behavioral_model(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user_profiles/{user_id}/returning_boost")
def get_returning_customer_boost(
    user_id: str,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Get returning customer boost signals for a user."""
    try:
        from src.app.services.episodic_memory import EpisodicMemory
        from src.app.services.memory import Memory
        from src.app.deps import get_redis

        mem = Memory(get_redis())
        em = EpisodicMemory(mem)
        return em.get_returning_customer_boost(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/citation_memory/stats")
def citation_memory_stats(
    agent_name: str | None = Query(default=None),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Get citation memory statistics for monitoring dashboards."""
    try:
        from src.app.services.citation_memory import get_claim_stats
        return get_claim_stats(agent_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/citation_memory/trusted_claims")
def trusted_claims(
    agent_name: str,
    claim_type: str,
    min_trust: float = Query(default=0.7, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=100),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Get high-trust agent claims for transparency."""
    try:
        from src.app.services.citation_memory import get_trusted_claims
        claims = get_trusted_claims(agent_name, claim_type, min_trust=min_trust, limit=limit)
        return {"agent_name": agent_name, "claim_type": claim_type, "count": len(claims), "claims": claims}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/citation_memory/agent_trust/{agent_name}")
def agent_trust_score(
    agent_name: str,
    claim_type: str | None = Query(default=None),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Get aggregate trust score for an agent."""
    try:
        from src.app.services.citation_memory import get_agent_trust_score
        score = get_agent_trust_score(agent_name, claim_type)
        return {"agent_name": agent_name, "claim_type": claim_type, "trust_score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/observation_summary/{session_id}")
def get_observation_summary(
    session_id: str,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Get compressed observation summary for a session."""
    try:
        from src.app.services.memory import Memory
        from src.app.deps import get_redis

        mem = Memory(get_redis())
        summary = mem.get_observation_summary(session_id)
        return {"session_id": session_id, "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
