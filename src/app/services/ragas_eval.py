from __future__ import annotations

import json
from typing import Dict, Any, List, Tuple

from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.observability.metrics import record_ragas_eval, set_ragas_baseline, set_ragas_quality_avg
from src.app.observability.telemetry import telemetry_emit


def _safe_len(x: Any) -> int:
    try:
        return len(str(x or ""))
    except Exception:
        return 0


def _compute_ragas_like(input_data: Any, context: Any, answer: Any) -> Dict[str, float]:
    # Attempt true ragas integration; otherwise use naive fallback
    try:
        from ragas.metrics import (
            faithfulness as m_faithfulness,
            answer_relevancy as m_answer_relevancy,
            context_precision as m_context_precision,
            context_recall as m_context_recall,
        )
        from ragas import evaluate
        from datasets import Dataset

        samples = Dataset.from_list(
            [
                {
                    "question": json.dumps(input_data, ensure_ascii=False),
                    "answer": json.dumps(answer, ensure_ascii=False),
                    "contexts": [json.dumps(context, ensure_ascii=False)],
                }
            ]
        )
        results = evaluate(samples, metrics=[m_faithfulness, m_answer_relevancy, m_context_precision, m_context_recall])
        return {
            "faithfulness": float(results["faithfulness"][0]),
            "answer_relevance": float(results["answer_relevancy"][0]),
            "context_precision": float(results["context_precision"][0]),
            "context_recall": float(results["context_recall"][0]),
        }
    except Exception:
        # Naive fallback metrics
        faithfulness = round(min(_safe_len(answer) / max(_safe_len(context), 1), 1.0), 2)
        answer_relevance = round(min(_safe_len(answer) / max(_safe_len(input_data), 1), 1.0), 2)
        context_precision = round(0.8 if context else 0.2, 2)
        context_recall = round(0.7 if (context and "order" in (context or {})) else 0.3, 2)
        return {
            "faithfulness": float(faithfulness),
            "answer_relevance": float(answer_relevance),
            "context_precision": float(context_precision),
            "context_recall": float(context_recall),
        }


def evaluate_and_persist(decision_id: str) -> Dict[str, Any]:
    """Evaluate one decision and persist per-metric scores with model/version.

    Uses ragas if available; otherwise falls back to deterministic heuristics.
    """
    with db_session() as db:
        row = db.execute(
            sql_text("SELECT id, input_data, retrieved_context, proposed_action, evaluator_model FROM decision_logs WHERE id = :id"),
            {"id": decision_id},
        ).fetchone()
        if not row:
            return {"evaluated": False, "error": "decision_not_found"}
        try:
            input_data = json.loads(row[1] or "{}")
        except Exception:
            input_data = {}
        try:
            ctx = json.loads(row[2] or "{}")
        except Exception:
            ctx = {}
        try:
            action = json.loads(row[3] or "{}") if isinstance(row[3], str) else (row[3] or {})
        except Exception:
            action = {}
        model = row[4] if len(row) > 4 else "unknown"

        metrics = _compute_ragas_like(input_data, ctx, action)

        db.execute(
            sql_text(
                "INSERT INTO ragas_eval_results (eval_id, decision_log_id, faithfulness, answer_relevance, context_precision, context_recall, evaluator_model) "
                "VALUES (:eid, :did, :f, :ar, :cp, :cr, :model)"
            ),
            {
                "eid": __import__("uuid").uuid4().hex,
                "did": decision_id,
                "f": metrics["faithfulness"],
                "ar": metrics["answer_relevance"],
                "cp": metrics["context_precision"],
                "cr": metrics["context_recall"],
                "model": str(model or "unknown"),
            },
        )
        try:
            db.commit()
            record_ragas_eval("ok")
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

        # Refresh gauges: baseline and moving average (recent window)
        try:
            rows = db.execute(
                sql_text(
                    "SELECT faithfulness, context_recall FROM ragas_eval_results ORDER BY created_at DESC LIMIT :window"
                ),
                {"window": 200},
            ).fetchall()
            if rows:
                vals = [(float(r[0] or 0.0), float(r[1] or 0.0)) for r in rows]
                avg = sum((f + c) / 2.0 for (f, c) in vals) / max(len(vals), 1)
                set_ragas_quality_avg(avg)
            base_row = db.execute(sql_text("SELECT baseline_score FROM ragas_baseline WHERE id = 'default'"))
            base = base_row.scalar() if base_row is not None else None
            if base is None and rows:
                # Initialize baseline if missing
                db.execute(
                    sql_text(
                        "INSERT INTO ragas_baseline (id, baseline_score) VALUES ('default', :s)"
                        " ON CONFLICT (id) DO UPDATE SET baseline_score = EXCLUDED.baseline_score, updated_at = CURRENT_TIMESTAMP"
                    ),
                    {"s": avg},
                )
                try:
                    db.commit()
                except Exception:
                    pass
                set_ragas_baseline(avg)
            elif base is not None:
                set_ragas_baseline(float(base))

            # Quality-drop alerting: trigger when moving average drops materially
            # against baseline over a minimum sample size.
            try:
                min_samples = int(__import__("os").getenv("RAGAS_ALERT_MIN_SAMPLES", "40") or 40)
                drop_pct = float(__import__("os").getenv("RAGAS_ALERT_DROP_PCT", "0.15") or 0.15)
                if base is not None and rows and len(rows) >= min_samples:
                    baseline = float(base)
                    if baseline > 0 and avg < (1.0 - drop_pct) * baseline:
                        telemetry_emit(
                            {
                                "component": "ragas_eval",
                                "event": "ragas_quality_drop",
                                "decision_id": decision_id,
                                "moving_avg": round(float(avg), 4),
                                "baseline": round(float(baseline), 4),
                                "drop_pct": round((baseline - float(avg)) / baseline, 4),
                                "window": len(rows),
                                "mitre_atlas": ["AML.0005"],
                            },
                            severity="warning",
                            sourcetype="shopsquire:quality",
                        )
            except Exception:
                pass
        except Exception:
            pass

        return {"evaluated": True, "decision_id": decision_id, "metrics": metrics}


def run_sampling(sample_rate: float = 0.1, limit: int = 200) -> Dict[str, Any]:
    """Sample recent decisions and evaluate a subset nightly or on demand.

    Persists results and returns a small summary. Controlled by sample_rate (0..1).
    """
    import random

    evaluated = 0
    with db_session() as db:
        rows = db.execute(
            sql_text("SELECT id FROM decision_logs ORDER BY created_at DESC LIMIT :limit"),
            {"limit": int(limit)},
        ).fetchall()
        for (did,) in rows:
            if random.random() <= float(sample_rate):
                try:
                    evaluate_and_persist(did)
                    evaluated += 1
                except Exception:
                    record_ragas_eval("error")
                    continue
    return {"evaluated": evaluated, "sampled": len(rows), "sample_rate": sample_rate}


def thresholds_to_confidence(metrics: Dict[str, float], faith_min: float = 0.75, recall_min: float = 0.6) -> Tuple[bool, float]:
    """Return (ok, modifier) where ok indicates sufficient quality, otherwise reduce confidence.

    If faithfulness or context recall below thresholds, reduce confidence by 0.2 by default.
    """
    ok = (metrics.get("faithfulness", 0.0) >= faith_min) and (metrics.get("context_recall", 0.0) >= recall_min)
    return ok, (1.0 if ok else 0.8)


def ci_guard_check(window: int = 200, drop_pct: float = 0.1) -> Dict[str, Any]:
    """CI guard: Fail deploy if moving average drops > X% vs baseline.

    Returns a report with `ok` flag; integrate this in CI pipeline as needed.
    """
    with db_session() as db:
        rows = db.execute(
            sql_text(
                "SELECT faithfulness, context_recall FROM ragas_eval_results ORDER BY created_at DESC LIMIT :window"
            ),
            {"window": int(window)},
        ).fetchall()
        if not rows:
            return {"ok": True, "reason": "no_data"}
        vals = [(float(r[0] or 0.0), float(r[1] or 0.0)) for r in rows]
        avg = sum((f + c) / 2.0 for (f, c) in vals) / max(len(vals), 1)
        # Fetch baseline
        base_row = db.execute(sql_text("SELECT baseline_score FROM ragas_baseline WHERE id = 'default'"))
        base = base_row.scalar() if base_row is not None else None
        if base is None:
            # Initialize baseline on first run
            db.execute(
                sql_text(
                    "INSERT INTO ragas_baseline (id, baseline_score) VALUES ('default', :s)"
                    " ON CONFLICT (id) DO UPDATE SET baseline_score = EXCLUDED.baseline_score, updated_at = CURRENT_TIMESTAMP"
                ),
                {"s": avg},
            )
            try:
                db.commit()
            except Exception:
                pass
            try:
                set_ragas_baseline(avg)
                set_ragas_quality_avg(avg)
            except Exception:
                pass
            return {"ok": True, "reason": "baseline_initialized", "baseline": avg}
        try:
            set_ragas_baseline(float(base))
            set_ragas_quality_avg(avg)
        except Exception:
            pass
        if avg < (1.0 - float(drop_pct)) * float(base):
            return {"ok": False, "reason": "moving_avg_drop", "avg": avg, "baseline": float(base)}
        return {"ok": True, "avg": avg, "baseline": float(base)}
