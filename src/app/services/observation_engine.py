"""Layer 2: Observer + Reflector — observation logging and compression.

Observer: Logs raw agent events (NQE fires, debates, model selections, tier routing)
          into the session's observation log via Memory.append_observation().

Reflector: When the observation log exceeds a token budget (default 5K-8K tokens
           for e-commerce sessions), compresses it into a summary and stores it
           via Memory.set_observation_summary().

Token budget rationale: Mastra's default is 30K but e-commerce sessions are
shorter-lived (5-15 turns). 5K-8K tokens captures the useful signal without
bloating context windows or Redis memory.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.app.services.memory import Memory


# ── Configuration ──
_TOKEN_BUDGET_LOW = 5000   # compress when log exceeds this
_TOKEN_BUDGET_HIGH = 8000  # hard cap for summary output
_APPROX_CHARS_PER_TOKEN = 4  # rough estimate for English text


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)


# ── Observer: log raw events ──

class Observer:
    """Logs raw agent events into the observation log."""

    def __init__(self, memory: Memory):
        self.memory = memory

    def log_nqe_fire(self, uid: str, *, questions_proposed: List[str], answered_fields: Dict[str, Any],
                     convergence_hit: bool = False, trace_id: str | None = None) -> None:
        self.memory.append_observation(uid, {
            "type": "nqe_fire",
            "questions_proposed": questions_proposed[:10],
            "answered_count": len(answered_fields),
            "convergence_hit": convergence_hit,
            "trace_id": trace_id,
        })

    def log_debate(self, uid: str, *, scenario: str, judge_decision: str, confidence: float,
                   risks: List[str] | None = None, trace_id: str | None = None) -> None:
        self.memory.append_observation(uid, {
            "type": "debate",
            "scenario": scenario,
            "judge_decision": judge_decision,
            "confidence": round(confidence, 3),
            "risks": (risks or [])[:5],
            "trace_id": trace_id,
        })

    def log_model_selection(self, uid: str, *, model: str, tier: str, complexity_score: float,
                            trace_id: str | None = None) -> None:
        self.memory.append_observation(uid, {
            "type": "model_selection",
            "model": model,
            "tier": tier,
            "complexity_score": round(complexity_score, 3),
            "trace_id": trace_id,
        })

    def log_recommendation(self, uid: str, *, skus: List[str], scores: List[float] | None = None,
                           source: str = "pipeline", trace_id: str | None = None) -> None:
        self.memory.append_observation(uid, {
            "type": "recommendation",
            "skus": skus[:12],
            "top_score": round(scores[0], 3) if scores else None,
            "count": len(skus),
            "source": source,
            "trace_id": trace_id,
        })

    def log_tier_routing(self, uid: str, *, selected_tier: str, reason: str,
                         trace_id: str | None = None) -> None:
        self.memory.append_observation(uid, {
            "type": "tier_routing",
            "selected_tier": selected_tier,
            "reason": reason[:100],
            "trace_id": trace_id,
        })

    def log_generic(self, uid: str, event_type: str, payload: Dict[str, Any] | None = None,
                    trace_id: str | None = None) -> None:
        obs: Dict[str, Any] = {"type": event_type, "trace_id": trace_id}
        if payload:
            for k, v in list(payload.items())[:15]:
                obs[k] = v
        self.memory.append_observation(uid, obs)


# ── Reflector: compress observations when they exceed token budget ──

class Reflector:
    """Compresses the observation log into a summary when it exceeds the token budget."""

    def __init__(self, memory: Memory, token_budget: int = _TOKEN_BUDGET_LOW):
        self.memory = memory
        self.token_budget = token_budget

    def should_compress(self, uid: str) -> bool:
        """Check if the observation log exceeds the token budget."""
        log = self.memory.get_observation_log(uid)
        if not log:
            return False
        import json
        raw = json.dumps(log)
        return _estimate_tokens(raw) > self.token_budget

    def compress(self, uid: str) -> Dict[str, Any]:
        """Compress the observation log into a structured summary.

        Groups events by type, counts occurrences, extracts key patterns,
        and produces a compact summary within the token budget.
        """
        log = self.memory.get_observation_log(uid)
        if not log:
            return {}

        # Group by event type
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for entry in log:
            t = entry.get("type", "unknown")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(entry)

        summary: Dict[str, Any] = {
            "compressed_at": time.time(),
            "total_events": len(log),
            "event_types": {},
        }

        for event_type, entries in by_type.items():
            type_summary: Dict[str, Any] = {"count": len(entries)}

            if event_type == "nqe_fire":
                all_qs = []
                convergences = sum(1 for e in entries if e.get("convergence_hit"))
                for e in entries:
                    all_qs.extend(e.get("questions_proposed", []))
                type_summary["total_questions_proposed"] = len(all_qs)
                type_summary["convergence_hits"] = convergences
                type_summary["unique_questions"] = list(set(all_qs))[:10]

            elif event_type == "debate":
                decisions = [e.get("judge_decision") for e in entries]
                type_summary["decisions"] = {d: decisions.count(d) for d in set(decisions) if d}
                type_summary["avg_confidence"] = round(
                    sum(e.get("confidence", 0) for e in entries) / max(1, len(entries)), 3
                )
                all_risks = []
                for e in entries:
                    all_risks.extend(e.get("risks") or [])
                type_summary["top_risks"] = list(set(all_risks))[:8]

            elif event_type == "model_selection":
                models = [e.get("model") for e in entries if e.get("model")]
                type_summary["models_used"] = {m: models.count(m) for m in set(models)}
                type_summary["avg_complexity"] = round(
                    sum(e.get("complexity_score", 0) for e in entries) / max(1, len(entries)), 3
                )

            elif event_type == "recommendation":
                all_skus: List[str] = []
                for e in entries:
                    all_skus.extend(e.get("skus") or [])
                # Most frequently recommended SKUs
                sku_counts: Dict[str, int] = {}
                for s in all_skus:
                    sku_counts[s] = sku_counts.get(s, 0) + 1
                top_skus = sorted(sku_counts.items(), key=lambda x: x[1], reverse=True)[:8]
                type_summary["top_recommended_skus"] = [s for s, _ in top_skus]
                type_summary["total_recommendations"] = len(entries)

            elif event_type == "tier_routing":
                tiers = [e.get("selected_tier") for e in entries if e.get("selected_tier")]
                type_summary["tier_distribution"] = {t: tiers.count(t) for t in set(tiers)}

            summary["event_types"][event_type] = type_summary

        # Store the compressed summary
        self.memory.set_observation_summary(uid, summary)

        return summary

    def maybe_compress(self, uid: str) -> Optional[Dict[str, Any]]:
        """Compress only if the log exceeds the token budget."""
        if self.should_compress(uid):
            return self.compress(uid)
        return None
