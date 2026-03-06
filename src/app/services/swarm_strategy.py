from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class StrategyGenome:
    strategy_id: str
    worker_scale: float = 1.0
    sample_bias: float = 0.0
    mutation_rate: float = 0.2
    fitness: float = 0.0
    generation: int = 0
    parent_ids: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_initial_population(size: int = 4) -> List[StrategyGenome]:
    n = max(2, min(int(size or 4), 12))
    out: List[StrategyGenome] = []
    for i in range(n):
        out.append(
            StrategyGenome(
                strategy_id=f"strat_{i + 1}",
                worker_scale=round(random.uniform(0.7, 1.3), 3),
                sample_bias=round(random.uniform(-0.2, 0.2), 3),
                mutation_rate=0.2,
                fitness=0.0,
                generation=0,
                parent_ids=[],
            )
        )
    return out


def score_strategy(*, pass_rate: float, error_rate: float, avg_elapsed_ms: float, stability: float = 0.0) -> float:
    latency_penalty = min(0.35, float(avg_elapsed_ms or 0.0) / 20000.0)
    stability_bonus = max(0.0, min(0.2, float(stability or 0.0)))
    return round((float(pass_rate or 0.0) * 1.25) - (float(error_rate or 0.0) * 1.1) - latency_penalty + stability_bonus, 6)


def mutate(base: StrategyGenome, idx: int, *, generation: int | None = None) -> StrategyGenome:
    jitter = lambda s: random.uniform(-s, s)
    gen = int(generation if generation is not None else (base.generation + 1))
    return StrategyGenome(
        strategy_id=f"{base.strategy_id}_m{idx}",
        worker_scale=max(0.5, min(1.8, round(base.worker_scale + jitter(base.mutation_rate), 3))),
        sample_bias=max(-0.5, min(0.5, round(base.sample_bias + jitter(base.mutation_rate), 3))),
        mutation_rate=max(0.05, min(0.5, round(base.mutation_rate * random.uniform(0.8, 1.2), 3))),
        fitness=0.0,
        generation=gen,
        parent_ids=[str(base.strategy_id)],
    )


def crossover(a: StrategyGenome, b: StrategyGenome, idx: int, *, generation: int) -> StrategyGenome:
    mix = random.uniform(0.35, 0.65)
    child = StrategyGenome(
        strategy_id=f"cross_{generation}_{idx}",
        worker_scale=max(0.5, min(1.8, round((a.worker_scale * mix) + (b.worker_scale * (1.0 - mix)), 3))),
        sample_bias=max(-0.5, min(0.5, round((a.sample_bias * (1.0 - mix)) + (b.sample_bias * mix), 3))),
        mutation_rate=max(0.05, min(0.5, round((a.mutation_rate + b.mutation_rate) / 2.0, 3))),
        fitness=0.0,
        generation=int(generation),
        parent_ids=[str(a.strategy_id), str(b.strategy_id)],
    )
    return mutate(child, idx=idx, generation=generation)


def _tournament_select(population: List[StrategyGenome], size: int = 3) -> StrategyGenome:
    if not population:
        return StrategyGenome(strategy_id="strat_fallback")
    k = max(1, min(int(size or 3), len(population)))
    picks = random.sample(population, k=k)
    return sorted(picks, key=lambda s: float(s.fitness or 0.0), reverse=True)[0]


def _history_path() -> Path:
    raw = str(os.getenv("SWARM_STRATEGY_HISTORY_PATH", "runs/swarm_strategy_history.jsonl") or "").strip()
    return Path(raw or "runs/swarm_strategy_history.jsonl")


def persist_generation_snapshot(
    *,
    round_id: int,
    population: List[StrategyGenome],
    summary: Dict[str, Any] | None = None,
) -> None:
    payload = {
        "ts": time.time(),
        "round": int(round_id),
        "summary": dict(summary or {}),
        "population": [s.as_dict() for s in (population or [])],
    }
    path = _history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def summarize_population(population: List[StrategyGenome]) -> Dict[str, Any]:
    pop = [s for s in (population or []) if isinstance(s, StrategyGenome)]
    if not pop:
        return {"size": 0, "best_fitness": 0.0, "avg_fitness": 0.0}
    ordered = sorted(pop, key=lambda s: float(s.fitness or 0.0), reverse=True)
    avg = sum(float(s.fitness or 0.0) for s in pop) / float(len(pop))
    return {
        "size": len(pop),
        "best_strategy_id": str(ordered[0].strategy_id),
        "best_fitness": round(float(ordered[0].fitness or 0.0), 6),
        "avg_fitness": round(float(avg), 6),
        "generation": int(max(s.generation for s in pop)),
    }


def evolve_population(
    current: List[StrategyGenome],
    *,
    keep_top: int = 2,
    target_size: int = 4,
    elitism: int = 1,
    tournament_size: int = 3,
    random_immigrants: int = 1,
) -> List[StrategyGenome]:
    if not current:
        return build_initial_population(target_size)
    ordered = sorted(current, key=lambda s: float(s.fitness or 0.0), reverse=True)
    keep_n = max(1, min(int(keep_top or 2), len(ordered)))
    survivors = ordered[:keep_n]
    next_generation = int(max(int(s.generation or 0) for s in ordered) + 1)
    elite_n = max(1, min(int(elitism or 1), keep_n))

    next_gen: List[StrategyGenome] = []
    for i, s in enumerate(survivors[:elite_n], start=1):
        next_gen.append(
            StrategyGenome(
                strategy_id=f"{s.strategy_id}_elite{next_generation}_{i}",
                worker_scale=float(s.worker_scale),
                sample_bias=float(s.sample_bias),
                mutation_rate=float(s.mutation_rate),
                fitness=float(s.fitness or 0.0),
                generation=next_generation,
                parent_ids=[str(s.strategy_id)],
            )
        )

    max_size = max(2, int(target_size or 4))
    i = 0
    while len(next_gen) < max(2, max_size - max(0, int(random_immigrants or 0))):
        p1 = _tournament_select(survivors, size=tournament_size)
        p2 = _tournament_select(survivors, size=tournament_size)
        next_gen.append(crossover(p1, p2, idx=i + 1, generation=next_generation))
        i += 1

    immigrants = max(0, min(int(random_immigrants or 0), max_size))
    if immigrants > 0:
        seeds = build_initial_population(size=immigrants)
        for j, s in enumerate(seeds, start=1):
            s.strategy_id = f"immigrant_{next_generation}_{j}"
            s.generation = next_generation
            s.parent_ids = []
            next_gen.append(s)

    next_gen = sorted(next_gen, key=lambda s: float(s.fitness or 0.0), reverse=True)[:max_size]
    return next_gen

