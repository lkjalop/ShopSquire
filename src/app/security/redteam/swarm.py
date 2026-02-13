from __future__ import annotations

from typing import Any, Dict
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import uuid

from src.app.security.redteam.suite import run_mutation_campaign


_EXEC = ThreadPoolExecutor(max_workers=2)
_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}


def _run_swarm(job_id: str, rounds: int, max_mutations_per_case: int) -> None:
    with _LOCK:
        _JOBS[job_id]["status"] = "running"
    results = []
    for i in range(max(1, rounds)):
        campaign = run_mutation_campaign(max_mutations_per_case=max_mutations_per_case, persist=True)
        det_rate = float(campaign.get("detection_rate") or 0.0)
        adjudication = "pass" if det_rate >= 0.85 else "fail"
        results.append(
            {
                "round": i + 1,
                "run_id": campaign.get("run_id"),
                "detection_rate": det_rate,
                "adjudication": adjudication,
                "attacker_payloads": int(campaign.get("total_cases") or 0),
                "defender_detected": int(campaign.get("detected_cases") or 0),
            }
        )
    avg = sum(float(x.get("detection_rate") or 0.0) for x in results) / float(max(1, len(results)))
    with _LOCK:
        _JOBS[job_id]["status"] = "completed"
        _JOBS[job_id]["completed_at"] = int(time.time())
        _JOBS[job_id]["results"] = results
        _JOBS[job_id]["summary"] = {
            "rounds": len(results),
            "avg_detection_rate": round(float(avg), 4),
            "pass_rounds": len([x for x in results if x.get("adjudication") == "pass"]),
        }


def start_swarm(*, rounds: int = 3, max_mutations_per_case: int = 6) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    with _LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": int(time.time()),
            "results": [],
            "summary": {},
        }
    _EXEC.submit(_run_swarm, job_id, int(rounds), int(max_mutations_per_case))
    return {"job_id": job_id, "status": "queued"}


def get_swarm(job_id: str) -> Dict[str, Any]:
    with _LOCK:
        return dict(_JOBS.get(job_id) or {"job_id": job_id, "status": "not_found"})

