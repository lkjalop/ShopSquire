from __future__ import annotations

import random
from dataclasses import dataclass, asdict
from typing import Any, Dict, List


@dataclass
class StrategyGenome:
    strategy_id: str
    worker_scale: float = 1.0
    sample_bias: float = 0.0
    mutation_rate: float = 0.2
    fitness: float = 0.0

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
            )
        )
    return out


def score_strategy(*, pass_rate: float, error_rate: float, avg_elapsed_ms: float) -> float:
    latency_penalty = min(0.35, float(avg_elapsed_ms or 0.0) / 20000.0)
    return round((float(pass_rate or 0.0) * 1.25) - (float(error_rate or 0.0) * 1.1) - latency_penalty, 6)


def mutate(base: StrategyGenome, idx: int) -> StrategyGenome:
    jitter = lambda s: random.uniform(-s, s)
    return StrategyGenome(
        strategy_id=f"{base.strategy_id}_m{idx}",
        worker_scale=max(0.5, min(1.8, round(base.worker_scale + jitter(base.mutation_rate), 3))),
        sample_bias=max(-0.5, min(0.5, round(base.sample_bias + jitter(base.mutation_rate), 3))),
        mutation_rate=max(0.05, min(0.5, round(base.mutation_rate * random.uniform(0.8, 1.2), 3))),
        fitness=0.0,
    )


def evolve_population(current: List[StrategyGenome], *, keep_top: int = 2, target_size: int = 4) -> List[StrategyGenome]:
    if not current:
        return build_initial_population(target_size)
    ordered = sorted(current, key=lambda s: float(s.fitness or 0.0), reverse=True)
    keep_n = max(1, min(int(keep_top or 2), len(ordered)))
    survivors = ordered[:keep_n]
    next_gen: List[StrategyGenome] = [StrategyGenome(**s.as_dict()) for s in survivors]
    i = 0
    while len(next_gen) < max(2, int(target_size or 4)):
        parent = survivors[i % len(survivors)]
        next_gen.append(mutate(parent, i + 1))
        i += 1
    return next_gen

