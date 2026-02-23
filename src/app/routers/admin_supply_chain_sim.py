"""API router for supply-chain attack simulation.

Provides:
- GET  /scenarios                 – list available scenarios
- GET  /scenarios/{id}            – scenario detail
- POST /run                       – run a single scenario  (JSON result)
- POST /run-all                   – run all scenarios       (JSON result)
- GET  /run/{id}/stream           – SSE: run scenario with real-time agent steps
- GET  /run-all/stream            – SSE: run all scenarios with real-time steps
- POST /swarm                     – parallel agent swarm run (background job)
- GET  /swarm/{job_id}            – poll swarm job status

All endpoints require owner or developer role.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_OWNER

router = APIRouter(
    prefix="/api/v1/admin/supply-chain-sim",
    tags=["supply-chain-simulation"],
)

_SWARM_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sc_swarm")
_SWARM_JOBS: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _serialise(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Scenario catalogue
# ---------------------------------------------------------------------------

@router.get("/scenarios")
def list_scenarios(role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    from src.app.security.supply_chain_scenarios import list_scenarios as _ls
    return {"scenarios": _ls()}


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    from src.app.security.supply_chain_scenarios import get_scenario as _gs
    try:
        return _gs(scenario_id)
    except (KeyError, ValueError):
        raise HTTPException(404, f"Unknown scenario: {scenario_id}")


# ---------------------------------------------------------------------------
# Synchronous runs (JSON)
# ---------------------------------------------------------------------------

@router.post("/run")
def run_single(
    scenario_id: str = Query(...),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    from src.app.security.supply_chain_harness import run_scenario
    try:
        result = run_scenario(scenario_id)
        return asdict(result)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc))


@router.post("/run-all")
def run_all_sync(role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    from src.app.security.supply_chain_harness import run_all, format_report
    results = run_all()
    return {
        "results": [asdict(r) for r in results],
        "summary": {
            "total": len(results),
            "pass": sum(1 for r in results if r.pass_fail == "PASS"),
            "partial": sum(1 for r in results if r.pass_fail == "PARTIAL"),
            "fail": sum(1 for r in results if r.pass_fail == "FAIL"),
        },
        "report_text": format_report(results),
    }


# ---------------------------------------------------------------------------
# SSE streaming runs
# ---------------------------------------------------------------------------

def _sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {_serialise(data)}\n\n"


def _stream_scenario(scenario_id: str):
    """Generator that yields SSE events as each agent step completes."""
    from src.app.security.supply_chain_harness import run_scenario
    yield _sse_event("start", {"scenario_id": scenario_id, "ts": time.time()})
    try:
        result = run_scenario(scenario_id)
        rd = asdict(result)
        # Emit each thinking step individually for real-time UX
        for step in rd.get("thinking_steps", []):
            yield _sse_event("agent_step", step)
        yield _sse_event("result", rd)
    except Exception as exc:
        yield _sse_event("error", {"scenario_id": scenario_id, "error": str(exc)})
    yield _sse_event("done", {"scenario_id": scenario_id})


@router.get("/run/{scenario_id}/stream")
def stream_scenario(scenario_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    from src.app.security.supply_chain_scenarios import get_scenario as _gs
    try:
        _gs(scenario_id)
    except (KeyError, ValueError):
        raise HTTPException(404, f"Unknown scenario: {scenario_id}")
    return StreamingResponse(
        _stream_scenario(scenario_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stream_all():
    from src.app.security.supply_chain_scenarios import list_scenarios as _ls
    from src.app.security.supply_chain_harness import run_scenario, format_report
    scenarios = _ls()
    yield _sse_event("start", {"total": len(scenarios), "ts": time.time()})
    results = []
    for sc in scenarios:
        sid = sc["scenario_id"]
        yield _sse_event("scenario_start", {"scenario_id": sid, "name": sc["name"]})
        try:
            r = run_scenario(sid)
            rd = asdict(r)
            for step in rd.get("thinking_steps", []):
                yield _sse_event("agent_step", {**step, "scenario_id": sid})
            yield _sse_event("scenario_result", rd)
            results.append(r)
        except Exception as exc:
            yield _sse_event("error", {"scenario_id": sid, "error": str(exc)})
    summary = {
        "total": len(results),
        "pass": sum(1 for r in results if r.pass_fail == "PASS"),
        "partial": sum(1 for r in results if r.pass_fail == "PARTIAL"),
        "fail": sum(1 for r in results if r.pass_fail == "FAIL"),
    }
    yield _sse_event("summary", summary)
    yield _sse_event("done", {"ts": time.time()})


@router.get("/run-all/stream")
def stream_all(role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    return StreamingResponse(
        _stream_all(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Parallel agent swarm (background job) - Celery-backed
# ---------------------------------------------------------------------------

from src.app.workers.celery_app import celery_app  # noqa: E402
from src.app.tasks.swarm_tasks import run_swarm  # noqa: E402
from src.app.services.swarm_store import set_job, get_job  # noqa: E402


@router.post("/swarm")
def start_swarm(
    rounds: int = Query(1, ge=1, le=10),
    scenario_ids: str | None = Query(None, description="Comma-sep scenario IDs or omit for all"),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    job_id = str(uuid.uuid4())
    ids = [s.strip() for s in scenario_ids.split(",") if s.strip()] if scenario_ids else None
    # initialize job in Redis
    set_job(job_id, {"job_id": job_id, "status": "queued", "created_at": time.time(), "rounds": []})
    # enqueue Celery task (task id == job_id so clients can correlate)
    run_swarm.apply_async(args=(job_id, int(rounds), ids), task_id=job_id)
    return {"job_id": job_id, "status": "queued"}


@router.get("/swarm/{job_id}")
def get_swarm(job_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
