"""Chat response streaming via Server-Sent Events.

Provides ``POST /api/v1/chat/stream`` which wraps the normal chat/recommend
pipeline and yields progress events as SSE so the frontend can display
intermediate updates (thinking, retrieval, reranking, final answer).
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from src.app.deps import get_redis
from src.app.models.db import get_db
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER

router = APIRouter(prefix="/api/v1/chat", tags=["chat-stream"])


def _sse_event(event: str, data: Any) -> str:
    """Format a single SSE frame."""
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/stream")
async def chat_stream(
    request: Request,
    payload: Dict,
    redis=Depends(get_redis),
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
):
    """SSE streaming chat endpoint.

    Emits events:
    - ``thinking`` — agent started processing
    - ``retrieval`` — products retrieved from catalog
    - ``ranking`` — reranking pass complete
    - ``answer`` — final response payload (same shape as /chat/query)
    - ``error`` — on failure
    - ``done`` — stream end sentinel
    """
    trace_id = str(payload.get("trace_id") or uuid.uuid4())

    async def _generate():
        yield _sse_event("thinking", {"trace_id": trace_id, "ts": time.time()})

        try:
            # Delegate to the normal chat query handler
            from src.app.routers.chat import chat_query
            result = await chat_query(request, payload, redis, db, role)

            # Emit intermediate signals from the result
            if isinstance(result, dict):
                agent_chain = result.get("agent_chain") or []
                if agent_chain:
                    yield _sse_event("retrieval", {
                        "agents": [a.get("agent") for a in agent_chain[:5]],
                        "ts": time.time(),
                    })

                ranked_skus = []
                proposal = result.get("proposal") or {}
                if isinstance(proposal, dict):
                    ranked_skus = proposal.get("ranked_skus") or []
                if ranked_skus:
                    yield _sse_event("ranking", {
                        "count": len(ranked_skus),
                        "top_sku": ranked_skus[0] if ranked_skus else None,
                        "ts": time.time(),
                    })

                yield _sse_event("answer", result)
            else:
                yield _sse_event("answer", {"raw": result})

        except Exception as exc:
            yield _sse_event("error", {"message": str(exc)[:500], "ts": time.time()})

        yield _sse_event("done", {"ts": time.time()})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
