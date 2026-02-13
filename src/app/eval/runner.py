from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Any, List

from src.app.services.recommendations import RecommendationService


@dataclass
class EvalCase:
    query: str
    expected_intents: List[str]
    expected_slots: Dict[str, Any]


def load_cases(path: str) -> List[EvalCase]:
    cases: List[EvalCase] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            cases.append(
                EvalCase(
                    query=row["query"],
                    expected_intents=list(row.get("expected_intents") or []),
                    expected_slots=row.get("expected_slots") or {},
                )
            )
    return cases


def run_intent_slot_eval(cases: List[EvalCase]) -> Dict[str, Any]:
    svc = RecommendationService()
    intent_hits = 0
    slot_hits = 0
    total_slots = 0

    for case in cases:
        nlp = svc.analyze_query(case.query)
        intents = [i.get("intent") for i in nlp.get("intent_chain", [])]
        if any(i in intents for i in case.expected_intents):
            intent_hits += 1
        slots = nlp.get("slots") or {}
        for k, v in case.expected_slots.items():
            total_slots += 1
            if slots.get(k) == v:
                slot_hits += 1

    intent_acc = intent_hits / max(len(cases), 1)
    slot_acc = slot_hits / max(total_slots, 1)
    return {
        "cases": len(cases),
        "intent_accuracy": round(intent_acc, 3),
        "slot_accuracy": round(slot_acc, 3),
        "intent_hits": intent_hits,
        "slot_hits": slot_hits,
        "total_slots": total_slots,
    }
