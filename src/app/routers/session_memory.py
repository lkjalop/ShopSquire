from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Query

from src.app.deps import get_redis
from src.app.services.memory import Memory
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER

router = APIRouter(prefix="/api/v1/session", tags=["session-memory"])


@router.get("/{uid}/memory")
def get_memory(uid: str, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    mem = Memory(redis)
    return mem.get_context(uid)


@router.get("/{uid}/summary")
def get_summary(uid: str, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    mem = Memory(redis)
    ctx = mem.get_context(uid)
    summary = ctx.get("summary") or {}
    kv = ctx.get("kv") or {}
    return {
        "summary_text": summary.get("summary_text", ""),
        "utterances_count": len(summary.get("utterances", [])),
        "retrieval_ranks": kv.get("retrieval_ranks", []),
    }


@router.post("/{uid}/memory/update")
def update_memory(uid: str, utterance: str, retrieval_ranks: Optional[List[str]] = Query(default=None), redis=Depends(get_redis), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    mem = Memory(redis)
    ctx = mem.get_context(uid)
    utterances = (ctx.get("summary", {}) or {}).get("utterances", [])
    utterances.append(utterance)
    # naive summary: truncate and join
    summary_text = "; ".join(utterances[-10:])
    new_summary = {"utterances": utterances[-50:], "summary_text": summary_text}
    if retrieval_ranks:
        # Be tolerant: accept JSON string or comma-separated values
        try:
            if isinstance(retrieval_ranks, str):
                import json as _json
                try:
                    parsed = _json.loads(retrieval_ranks)
                    retrieval_ranks = parsed if isinstance(parsed, list) else [retrieval_ranks]
                except Exception:
                    retrieval_ranks = [retrieval_ranks]
        except Exception:
            pass
        kv = ctx.get("kv", {}) or {}
        kv.update({"retrieval_ranks": retrieval_ranks})
        mem.set_kv(uid, kv)
    mem.set_summary(uid, new_summary)
    return {"updated": True, "summary": new_summary}
