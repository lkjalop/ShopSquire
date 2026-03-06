from __future__ import annotations

import random

from src.app.services.swarm_strategy import (
    StrategyGenome,
    build_initial_population,
    evolve_population,
    persist_generation_snapshot,
    summarize_population,
)


def test_evolve_population_keeps_elites_and_target_size():
    random.seed(7)
    pop = build_initial_population(size=5)
    for idx, s in enumerate(pop):
        s.fitness = float(5 - idx)
    nxt = evolve_population(pop, keep_top=3, target_size=6, elitism=2, tournament_size=3, random_immigrants=1)
    assert len(nxt) == 6
    assert any("elite" in str(s.strategy_id) for s in nxt)
    assert summarize_population(nxt).get("size") == 6


def test_persist_generation_snapshot_writes_history(monkeypatch, tmp_path):
    path = tmp_path / "swarm_strategy_history.jsonl"
    monkeypatch.setenv("SWARM_STRATEGY_HISTORY_PATH", str(path))
    population = [
        StrategyGenome(strategy_id="s1", worker_scale=1.1, sample_bias=0.1, mutation_rate=0.2, fitness=0.8, generation=2),
        StrategyGenome(strategy_id="s2", worker_scale=0.9, sample_bias=-0.1, mutation_rate=0.2, fitness=0.4, generation=2),
    ]
    persist_generation_snapshot(round_id=3, population=population, summary={"pass_rate": 0.67})
    assert path.exists()
    txt = path.read_text(encoding="utf-8")
    assert "\"round\": 3" in txt
    assert "\"strategy_id\": \"s1\"" in txt

