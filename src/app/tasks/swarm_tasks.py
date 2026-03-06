from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from src.app.workers.celery_app import celery_app
from src.app.services.swarm_store import set_job
from src.app.services.swarm_strategy import (
    StrategyGenome,
    build_initial_population,
    evolve_population,
    persist_generation_snapshot,
    score_strategy,
    summarize_population,
)
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
    population: List[StrategyGenome] = build_initial_population(size=6)

    for rnd in range(1, max(1, int(rounds)) + 1):
        ordered = sorted(population, key=lambda s: float(s.fitness or 0.0), reverse=True)
        if not ordered:
            ordered = [StrategyGenome(strategy_id=f"strat_r{rnd}")]
        # Exploit top strategy most rounds, explore runner-up every 3rd round.
        active_strategy = ordered[1] if (len(ordered) > 1 and rnd % 3 == 0) else ordered[0]
        max_workers = max(1, min(len(ids), int(round(6 * float(active_strategy.worker_scale or 1.0)))))
        round_results = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
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
        run_total = len(round_results or [])
        pass_count = sum(1 for x in round_results if str(x.get("pass_fail")) == "PASS")
        err_count = sum(1 for x in round_results if str(x.get("pass_fail")) == "ERROR")
        avg_elapsed = sum(float(x.get("elapsed_ms") or 0.0) for x in round_results) / float(max(1, run_total))
        active_strategy.fitness = score_strategy(
            pass_rate=(pass_count / float(max(1, run_total))),
            error_rate=(err_count / float(max(1, run_total))),
            avg_elapsed_ms=avg_elapsed,
            stability=min(1.0, float(active_strategy.fitness or 0.0) if active_strategy.fitness > 0 else 0.0),
        )
        # Mild fitness decay for inactive genomes to preserve selection pressure.
        for g in population:
            if str(g.strategy_id) == str(active_strategy.strategy_id):
                continue
            g.fitness = round(float(g.fitness or 0.0) * 0.98, 6)
        all_round_results.append({"round": rnd, "results": round_results})
        all_round_results[-1]["strategy"] = active_strategy.as_dict()
        round_summary = {
            "round": rnd,
            "active_strategy_id": str(active_strategy.strategy_id),
            "pass_rate": round(pass_count / float(max(1, run_total)), 4),
            "error_rate": round(err_count / float(max(1, run_total)), 4),
            "avg_elapsed_ms": round(float(avg_elapsed), 3),
        }
        try:
            persist_generation_snapshot(round_id=rnd, population=population, summary=round_summary)
        except Exception:
            pass
        population = evolve_population(
            population,
            keep_top=3,
            target_size=6,
            elitism=2,
            tournament_size=3,
            random_immigrants=1,
        )
        # update partial progress
        set_job(
            job_id,
            {
                "job_id": job_id,
                "status": "running",
                "rounds": all_round_results,
                "population": [s.as_dict() for s in population],
                "population_summary": summarize_population(population),
                "updated_at": time.time(),
            },
        )

    total = sum(len(rnd["results"]) for rnd in all_round_results)
    pass_total = sum(1 for rnd in all_round_results for r in rnd["results"] if r.get("pass_fail") == "PASS")
    summary = {"total_runs": total, "pass_rate": round(pass_total / max(1, total), 4), "rounds_completed": len(all_round_results)}
    set_job(
        job_id,
        {
            "job_id": job_id,
            "status": "completed",
            "rounds": all_round_results,
            "population": [s.as_dict() for s in population],
            "population_summary": summarize_population(population),
            "summary": summary,
            "completed_at": time.time(),
        },
    )
    SWARM_TASKS_COMPLETED.inc()
    SWARM_TASK_DURATION.observe(time.time() - start_ts)
    return {"job_id": job_id, "summary": summary}
