from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from src.app.workers.celery_app import celery_app
from src.app.services.swarm_store import set_job
from src.app.observability.swarm_metrics import SWARM_TASKS_STARTED, SWARM_TASKS_COMPLETED, SWARM_TASK_DURATION


@celery_app.task(bind=True)
def run_swarm(self, job_id: str, rounds: int, scenario_ids: List[str] | None = None) -> Dict[str, Any]:
    from src.app.security.supply_chain_harness import run_scenario
    from src.app.security.supply_chain_scenarios import list_scenarios as _ls

    set_job(job_id, {"job_id": job_id, "status": "running", "created_at": time.time(), "rounds": []})
    SWARM_TASKS_STARTED.inc()
    start_ts = time.time()
    ids = scenario_ids or [s["scenario_id"] for s in _ls()]
    all_round_results = []

    for rnd in range(1, max(1, int(rounds)) + 1):
        round_results = []
        with ThreadPoolExecutor(max_workers=min(len(ids), 6)) as pool:
            futures = {pool.submit(run_scenario, sid): sid for sid in ids}
            for fut in as_completed(futures):
                sid = futures[fut]
                try:
                    r = fut.result(timeout=120)
                    round_results.append({
                        "scenario_id": sid,
                        "pass_fail": r.pass_fail,
                        "severity": r.severity,
                        "signals": r.signals_detected,
                        "escalated": r.human_escalation_triggered,
                        "elapsed_ms": r.elapsed_ms,
                        "trace_id": r.trace_id,
                    })
                except Exception as exc:
                    round_results.append({"scenario_id": sid, "pass_fail": "ERROR", "error": str(exc)})
        all_round_results.append({"round": rnd, "results": round_results})
        # update partial progress
        set_job(job_id, {"job_id": job_id, "status": "running", "rounds": all_round_results, "updated_at": time.time()})

    total = sum(len(rnd["results"]) for rnd in all_round_results)
    pass_total = sum(1 for rnd in all_round_results for r in rnd["results"] if r.get("pass_fail") == "PASS")
    summary = {"total_runs": total, "pass_rate": round(pass_total / max(1, total), 4), "rounds_completed": len(all_round_results)}
    set_job(job_id, {"job_id": job_id, "status": "completed", "rounds": all_round_results, "summary": summary, "completed_at": time.time()})
    SWARM_TASKS_COMPLETED.inc()
    SWARM_TASK_DURATION.observe(time.time() - start_ts)
    return {"job_id": job_id, "summary": summary}
