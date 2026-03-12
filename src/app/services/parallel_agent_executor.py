from __future__ import annotations

"""Parallel agent checks executor (CV + Fraud + Inventory).

This module provides a lightweight, safe way to run multiple agent checks
in parallel and merge their results into a unified dict suitable for
policy gating and decision traces.

Uses `concurrent.futures.ThreadPoolExecutor` to avoid blocking the event
loop and to keep integration minimal (many existing services are sync).
"""

from typing import Any, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import threading
import os

from src.app.observability.metrics import record_tool_invocation, record_cb_state, record_incident_alert
from src.app.security.tool_intent_gate import evaluate_tool_intent
try:
    from src.app.services.citation_memory import get_agent_trust_score
except Exception:
    get_agent_trust_score = None


_CB_STATE = {"cv_failures": 0, "cv_open_until": 0.0, "fraud_failures": 0, "fraud_open_until": 0.0}

_CV_QUEUE = None
_CV_QUEUE_LOCK = threading.Lock()

def _ensure_cv_queue():
    global _CV_QUEUE
    with _CV_QUEUE_LOCK:
        if _CV_QUEUE is not None:
            return _CV_QUEUE
        try:
            import queue
            _CV_QUEUE = queue.Queue(maxsize=int(os.environ.get("CV_QUEUE_MAXSIZE", "50") or 50))
            def _worker():
                while True:
                    try:
                        job = _CV_QUEUE.get()
                        if job is None:
                            break
                        fn, args, done_evt, out_ref = job
                        try:
                            out_ref[0] = fn(*args)
                        except Exception:
                            out_ref[0] = {}
                        finally:
                            try:
                                done_evt.set()
                            except Exception:
                                pass
                            _CV_QUEUE.task_done()
                    except Exception:
                        time.sleep(0.05)
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
        except Exception:
            _CV_QUEUE = None
        return _CV_QUEUE


def _run_cv(payload: Dict[str, Any], retries: int | None = None, timeout_ms: int | None = None) -> Dict[str, Any]:
    gate = evaluate_tool_intent(
        tool_name="cv_scan",
        params={"payload_keys": sorted(list((payload or {}).keys()))[:24]},
        runtime="parallel_agent_executor",
        tenant_id=(payload or {}).get("tenant_id"),
        trace_id=(payload or {}).get("trace_id"),
    )
    if not bool(gate.get("allow")):
        try:
            from src.app.services.decision_log import log_trace_event
            tid = str(payload.get("trace_id") or "")
            if tid:
                log_trace_event(
                    trace_id=tid,
                    event_type="tool_policy_denied",
                    source_type="parallel_agent_executor",
                    source_id="ToolIntentGate",
                    target_type="tool",
                    target_id="cv_scan",
                    payload=gate,
                )
        except Exception:
            pass
        return {"_blocked": True, "gate": gate}
    # Simple circuit breaker: if too many failures, skip for cooldown
    now = time.time()
    if _CB_STATE["cv_open_until"] and now < _CB_STATE["cv_open_until"]:
        try:
            record_cb_state("cv_provider", True)
            from src.app.services.decision_log import log_trace_event
            tid = str(payload.get("trace_id") or "")
            log_trace_event(trace_id=tid or None, event_type="circuit_breaker_open", source_type="cv_provider", source_id="ManagedCVProvider", target_type=None, target_id=None, payload={"open_until": _CB_STATE["cv_open_until"]})
            record_incident_alert("cv_circuit_breaker", "medium")
        except Exception:
            pass
        return {}
    # Configurable retries/timeouts via env
    retries = int(os.environ.get("CV_RETRIES", str(retries if retries is not None else 2)) or 2)
    timeout_ms = int(os.environ.get("CV_TIMEOUT_MS", str(timeout_ms if timeout_ms is not None else 4000)) or 4000)
    cooldown_sec = float(os.environ.get("CV_CB_COOLDOWN_SEC", "10.0") or 10.0)
    start = time.time()
    # Optional simple queuing to smooth spikes
    if not payload.get("_skip_queue") and os.environ.get("CV_QUEUE_ENABLED", "0") in ("1", "true", "True"):
        q = _ensure_cv_queue()
        if q is not None:
            try:
                import queue as _q
                done_evt = threading.Event()
                out_ref: list[Dict[str, Any]] = [{}]
                q.put((_run_cv, ({**payload, "_skip_queue": True}, retries, timeout_ms), done_evt, out_ref), timeout=0.1)
                # Wait with timeout
                done_evt.wait(timeout=timeout_ms / 1000.0)
                return out_ref[0]
            except Exception:
                pass
    for attempt in range(1, max(1, retries) + 1):
        try:
            from src.app.services.cv_provider import ManagedCVProvider
            from src.app.services.cv_triage_basic import BasicCVTriage
            import asyncio as _asyncio
            # Optional offload to Redis RQ background worker when enabled
            if os.getenv("CV_RQ_ENABLED", "0") in ("1", "true", "True") and not payload.get("_skip_queue"):
                try:
                    from src.app.workers.rq_queue import enqueue_cv
                    job_id = enqueue_cv(payload) or ""
                    try:
                        from src.app.services.decision_log import log_trace_event
                        tid = str(payload.get("trace_id") or "")
                        log_trace_event(trace_id=tid or None, event_type="cv_job_queued", source_type="cv_provider", source_id="rq_queue", target_type="job", target_id=job_id, payload={"job_id": job_id})
                    except Exception:
                        pass
                    # return a placeholder; downstream can poll or receive async updates via trace broker
                    return {"queued_job_id": job_id}
                except Exception:
                    pass
            images = payload.get("images") or payload.get("image_b64s") or payload.get("image_data")
            if images:
                img = images[0] if isinstance(images, list) else images
                labels, text, *_ = _asyncio.run(ManagedCVProvider().get_labels_and_text(img))
                res = _asyncio.run(BasicCVTriage().analyze(labels, text)) or {}
                # Record latency as a trace event and metrics
                try:
                    from src.app.services.decision_log import log_trace_event
                    from src.app.observability.metrics import (
                        record_cv_provider_latency,
                        record_cb_state,
                        record_cv_provider_latency_tenant,
                    )
                    tid = str(payload.get("trace_id") or "")
                    latency_ms = int((time.time() - start) * 1000)
                    log_trace_event(
                        trace_id=tid or None,
                        event_type="provider_latency",
                        source_type="cv_provider",
                        source_id="ManagedCVProvider",
                        target_type=None,
                        target_id=None,
                        payload={"latency_ms": latency_ms, "attempt": attempt},
                    )
                    record_cv_provider_latency("ManagedCVProvider", payload.get("tier"), payload.get("cv_model"), latency_ms / 1000.0)
                    try:
                        record_cv_provider_latency_tenant(
                            "ManagedCVProvider",
                            payload.get("tier"),
                            payload.get("cv_model"),
                            (payload.get("tenant_id") if isinstance(payload, dict) else None),
                            latency_ms / 1000.0,
                        )
                    except Exception:
                        pass
                    _CB_STATE["cv_failures"] = 0
                    try:
                        record_cb_state("cv_provider", False)
                    except Exception:
                        pass
                except Exception:
                    pass
                return res
        except Exception:
            _CB_STATE["cv_failures"] += 1
            if _CB_STATE["cv_failures"] >= 3:
                _CB_STATE["cv_open_until"] = time.time() + cooldown_sec
                try:
                    record_cb_state("cv_provider", True)
                except Exception:
                    pass
        # best-effort timeout check
        if (time.time() - start) * 1000 > timeout_ms:
            break
        # small delay before next attempt
        try:
            time.sleep(0.2)
        except Exception:
            pass
    return {}


def _run_inventory(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    gate = evaluate_tool_intent(
        tool_name="inventory_check",
        params={"result_count": len(results or [])},
        runtime="parallel_agent_executor",
    )
    if not bool(gate.get("allow")):
        return [{"_blocked": True, "gate": gate}]
    out: List[Dict[str, Any]] = []
    try:
        from src.app.services.inventory_agent import InventoryAgent
        inv = InventoryAgent()
        for r in results[:8]:
            stock = int(r.get("stock") or 0)
            sku_val = r.get("sku") or ""
            res = inv.evaluate_stock_rule(sku_val, {"stock": stock})
            res["available_qty"] = stock
            out.append({"sku": sku_val, **res})
    except Exception:
        pass
    return out


def _run_fraud(base_signals: Dict[str, bool], cv_summary: Dict[str, Any], payload: Dict[str, Any], retries: int | None = None, timeout_ms: int | None = None) -> Dict[str, Any]:
    gate = evaluate_tool_intent(
        tool_name="fraud_scoring",
        params={"has_cv": bool(cv_summary), "base_signals": sorted([k for k, v in (base_signals or {}).items() if v])[:16]},
        runtime="parallel_agent_executor",
        tenant_id=(payload or {}).get("tenant_id"),
        trace_id=(payload or {}).get("trace_id"),
    )
    if not bool(gate.get("allow")):
        try:
            from src.app.services.decision_log import log_trace_event
            tid = str(payload.get("trace_id") or "")
            if tid:
                log_trace_event(
                    trace_id=tid,
                    event_type="tool_policy_denied",
                    source_type="parallel_agent_executor",
                    source_id="ToolIntentGate",
                    target_type="tool",
                    target_id="fraud_scoring",
                    payload=gate,
                )
        except Exception:
            pass
        return {"_blocked": True, "gate": gate}
    # Circuit breaker for fraud provider
    now = time.time()
    if _CB_STATE["fraud_open_until"] and now < _CB_STATE["fraud_open_until"]:
        try:
            record_cb_state("fraud_provider", True)
            from src.app.services.decision_log import log_trace_event
            tid = str(payload.get("trace_id") or "")
            log_trace_event(trace_id=tid or None, event_type="circuit_breaker_open", source_type="fraud_provider", source_id="FraudScorer", target_type=None, target_id=None, payload={"open_until": _CB_STATE["fraud_open_until"]})
            record_incident_alert("fraud_circuit_breaker", "medium")
        except Exception:
            pass
        return {}
    retries = int(os.environ.get("FRAUD_RETRIES", str(retries if retries is not None else 1)) or 1)
    timeout_ms = int(os.environ.get("FRAUD_TIMEOUT_MS", str(timeout_ms if timeout_ms is not None else 2000)) or 2000)
    cooldown_sec = float(os.environ.get("FRAUD_CB_COOLDOWN_SEC", "10.0") or 10.0)
    start = time.time()
    # Optional offload to Redis RQ background worker when enabled
    try:
        if os.getenv("FRAUD_RQ_ENABLED", "0") in ("1", "true", "True") and not payload.get("_skip_queue"):
            from src.app.workers.rq_queue import enqueue_fraud
            job_id = enqueue_fraud(payload, cv_summary or {}) or ""
            try:
                from src.app.services.decision_log import log_trace_event
                tid = str(payload.get("trace_id") or "")
                log_trace_event(trace_id=tid or None, event_type="fraud_job_queued", source_type="fraud_provider", source_id="rq_queue", target_type="job", target_id=job_id, payload={"job_id": job_id})
            except Exception:
                pass
            return {"queued_job_id": job_id}
    except Exception:
        pass
    try:
        for attempt in range(1, max(1, retries) + 1):
            try:
                from src.app.services.fraud_scorer import FraudScorer
                fraud = FraudScorer()
                fraud_score, fraud_level, fraud_signals = fraud.score_with_enrichment(
                    base_signals=base_signals,
                    expected_serial=None,
                    observed_serial=cv_summary.get("serial_number") if isinstance(cv_summary, dict) else None,
                    image_phash=None,
                    session_data=payload.get("session") if isinstance(payload, dict) else None,
                    case_id=payload.get("case_id") if isinstance(payload, dict) else None,
                )
                try:
                    latency_ms = int((time.time() - start) * 1000)
                    record_tool_invocation("fraud_provider", "ok", latency_ms / 1000.0)
                    from src.app.observability.metrics import (
                        record_fraud_provider_latency,
                        record_fraud_provider_latency_tenant,
                    )
                    record_fraud_provider_latency("FraudScorer", payload.get("fraud_model"), latency_ms / 1000.0)
                    try:
                        record_fraud_provider_latency_tenant(
                            "FraudScorer",
                            payload.get("fraud_model"),
                            (payload.get("tenant_id") if isinstance(payload, dict) else None),
                            latency_ms / 1000.0,
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
                _CB_STATE["fraud_failures"] = 0
                try:
                    record_cb_state("fraud_provider", False)
                except Exception:
                    pass
                return {"score": fraud_score, "level": fraud_level, "signals": fraud_signals}
            except Exception:
                _CB_STATE["fraud_failures"] += 1
                if _CB_STATE["fraud_failures"] >= 3:
                    _CB_STATE["fraud_open_until"] = time.time() + cooldown_sec
                    try:
                        record_cb_state("fraud_provider", True)
                    except Exception:
                        pass
            if (time.time() - start) * 1000 > timeout_ms:
                break
            try:
                time.sleep(0.15)
            except Exception:
                pass
        return {}
    except Exception:
        return {}


def _agent_weight(agent_name: str) -> float:
    if callable(get_agent_trust_score):
        try:
            return max(0.05, min(2.0, float(get_agent_trust_score(agent_name))))
        except Exception:
            pass
    return 1.0


def _cv_verdict(cv: Any) -> str:
    if isinstance(cv, dict) and cv.get("_blocked"):
        return "review"
    if isinstance(cv, dict):
        risk_markers = [
            cv.get("tampered"),
            cv.get("counterfeit"),
            cv.get("suspicious"),
            (float(cv.get("manipulation_score") or 0.0) >= 0.7),
        ]
        if any(bool(x) for x in risk_markers):
            return "block"
    return "allow"


def _fraud_verdict(fraud: Any) -> str:
    if isinstance(fraud, dict) and fraud.get("_blocked"):
        return "review"
    lvl = str((fraud or {}).get("level") or "").lower() if isinstance(fraud, dict) else ""
    if lvl in ("high", "critical"):
        return "block"
    if lvl in ("medium", "elevated"):
        return "review"
    return "allow"


def _inventory_verdict(inv: Any) -> str:
    if not isinstance(inv, list) or not inv:
        return "allow"
    for row in inv:
        if not isinstance(row, dict):
            continue
        if row.get("_blocked"):
            return "review"
        try:
            if int(row.get("available_qty") or 0) <= 0:
                return "review"
        except Exception:
            continue
    return "allow"


def _build_swarm_consensus(cv: Any, fraud: Any, inventory: Any) -> Dict[str, Any]:
    votes = [
        {"agent": "CV_Label_Agent", "verdict": _cv_verdict(cv), "weight": _agent_weight("CV_Label_Agent")},
        {"agent": "Fraud_Scoring_Agent", "verdict": _fraud_verdict(fraud), "weight": _agent_weight("Fraud_Scoring_Agent")},
        {"agent": "Inventory_Agent", "verdict": _inventory_verdict(inventory), "weight": _agent_weight("Inventory_Agent")},
    ]
    totals: Dict[str, float] = {"allow": 0.0, "review": 0.0, "block": 0.0}
    for v in votes:
        verdict = str(v.get("verdict") or "review")
        totals[verdict] = totals.get(verdict, 0.0) + float(v.get("weight") or 0.0)
    severity_rank = {"allow": 0, "review": 1, "block": 2}
    consensus = sorted(totals.items(), key=lambda kv: (float(kv[1]), severity_rank.get(kv[0], 1)), reverse=True)[0][0]
    dissent = [v for v in votes if v.get("verdict") != consensus]
    return {
        "consensus": consensus,
        "weighted_votes": totals,
        "votes": votes,
        "dissent_log": dissent,
        "has_dissent": bool(dissent),
    }


def run_parallel_checks(
    payload: Dict[str, Any],
    ranked_results: List[Dict[str, Any]] | None = None,
    base_signals: Dict[str, bool] | None = None,
) -> Dict[str, Any]:
    """Run CV, Fraud, and Inventory checks in parallel and merge outputs.

    Returns a dict: {"cv": {}, "fraud": {}, "inventory": []}
    """
    base_signals = base_signals or {}
    ranked_results = ranked_results or []

    outputs: Dict[str, Any] = {"cv": None, "fraud": None, "inventory": []}
    tasks = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        tasks[ex.submit(_run_cv, payload)] = "cv"
        tasks[ex.submit(_run_inventory, ranked_results)] = "inventory"
        # Fraud depends partly on CV; we still parallelize with base signals
        tasks[ex.submit(_run_fraud, base_signals, {}, payload)] = "fraud"
        for fut in as_completed(tasks):
            kind = tasks[fut]
            try:
                res = fut.result()
            except Exception:
                res = None
            outputs[kind] = res

    # If fraud ran without CV summary, re-evaluate once CV available
    try:
        if isinstance(outputs.get("cv"), dict) and not outputs.get("fraud"):
            outputs["fraud"] = _run_fraud(base_signals, outputs.get("cv") or {}, payload)
    except Exception:
        pass

    try:
        outputs["swarm"] = _build_swarm_consensus(outputs.get("cv"), outputs.get("fraud"), outputs.get("inventory"))
    except Exception:
        outputs["swarm"] = {"consensus": "review", "weighted_votes": {}, "votes": [], "dissent_log": [], "has_dissent": False}
    return outputs
