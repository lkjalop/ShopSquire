from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
import logging
import os

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.models.init_db import ensure_metadata
from src.app.services.policy_evaluator import PolicyEvaluator
from src.app.deps import redact_for_trace, security_sanitize
from src.app.security.pii_ner import redact_free_text_pii_ner
from src.app.services.confidence_calibration import calibrate_confidence
import asyncio
import threading
from collections import defaultdict
from src.app.services.trace_broker import publish as _publish_trace
from src.app.services.trace_taxonomy import normalize_trace_event_type
from src.app.services.trace_contracts import apply_trace_contract
from src.app.observability.telemetry import telemetry_emit
from src.app.observability.metrics import record_decision_trace_write_failure
import urllib.request
import urllib.error
try:
    from src.app.services.trace_broker import publish_sync as _publish_sync
except Exception:
    _publish_sync = None
try:
    from src.app.services.webhook_dispatcher import enqueue_webhook as _enqueue_webhook
except Exception:
    _enqueue_webhook = None

_DECISION_LOG_COL_CACHE: dict[str, list[str]] = {}
_TRACE_TABLE_ENSURED = False
_OUTBOX_TABLE_ENSURED = False
_TRACE_EVENT_CACHE: dict[str, list[dict[str, Any]]] = defaultdict(list)
_TRACE_EVENT_CACHE_LOCK = threading.Lock()
_TRACE_EVENT_CACHE_MAX_PER_TRACE = 256

_DECISION_LOG_INSERT_EXTENDED = text(
    """
    INSERT INTO decision_logs (
        id, tenant_id, actor_id, actor_role, event_type, agent_name, valid_from, valid_to, system_from, system_to,
        input_data, retrieved_context, agent_reasoning, proposed_action,
        policy_version, approval_required, execution_status
    ) VALUES (
        :id, :tenant_id, :actor_id, :actor_role, :event_type, :agent_name, :valid_from, :valid_to, :system_from, :system_to,
        :input_data, :retrieved_context, :agent_reasoning, :proposed_action,
        :policy_version, :approval_required, :execution_status
    )
    """
)

_DECISION_LOG_INSERT_MINIMAL = text(
    """
    INSERT INTO decision_logs (
        id, agent_name, valid_from, input_data, proposed_action, policy_version, approval_required, execution_status
    ) VALUES (
        :id, :agent_name, :valid_from, :input_data, :proposed_action, :policy_version, :approval_required, :execution_status
    )
    """
)

_DECISION_LOG_INSERT_CONTEXT = text(
    """
    INSERT INTO decision_logs (
        id, agent_name, valid_from, valid_to, system_from, system_to,
        input_data, retrieved_context, agent_reasoning, proposed_action,
        policy_version, approval_required, execution_status
    ) VALUES (
        :id, :agent_name, :valid_from, :valid_to, :system_from, :system_to,
        :input_data, :retrieved_context, :agent_reasoning, :proposed_action,
        :policy_version, :approval_required, :execution_status
    )
    """
)

_DECISION_LOG_INSERT_CONTEXT_TENANT = text(
    """
    INSERT INTO decision_logs (
        id, tenant_id, actor_id, actor_role, event_type, agent_name,
        valid_from, valid_to, system_from, system_to,
        input_data, retrieved_context, agent_reasoning, proposed_action,
        policy_version, approval_required, execution_status
    ) VALUES (
        :id, :tenant_id, :actor_id, :actor_role, :event_type, :agent_name,
        :valid_from, :valid_to, :system_from, :system_to,
        :input_data, :retrieved_context, :agent_reasoning, :proposed_action,
        :policy_version, :approval_required, :execution_status
    )
    """
)

_DECISION_LOG_INSERT_CONTEXT_WITH_TENANT = text(
    """
    INSERT INTO decision_logs (
        id, tenant_id, agent_name, valid_from, valid_to, system_from, system_to,
        input_data, retrieved_context, agent_reasoning, proposed_action,
        policy_version, approval_required, execution_status
    ) VALUES (
        :id, :tenant_id, :agent_name, :valid_from, :valid_to, :system_from, :system_to,
        :input_data, :retrieved_context, :agent_reasoning, :proposed_action,
        :policy_version, :approval_required, :execution_status
    )
    """
)


def _exec_decision_log_insert_mapped(db, cols: list[str], payload: Dict[str, Any]) -> bool:
    colset = set(str(c) for c in (cols or []))
    full_cols = {
        "id", "tenant_id", "actor_id", "actor_role", "event_type", "agent_name", "valid_from", "valid_to",
        "system_from", "system_to", "input_data", "retrieved_context", "agent_reasoning", "proposed_action",
        "policy_version", "approval_required", "execution_status",
    }
    minimal_cols = {
        "id", "agent_name", "valid_from", "input_data", "proposed_action", "policy_version", "approval_required", "execution_status",
    }
    context_cols = {
        "id", "agent_name", "valid_from", "valid_to", "system_from", "system_to",
        "input_data", "retrieved_context", "agent_reasoning", "proposed_action",
        "policy_version", "approval_required", "execution_status",
    }
    context_with_tenant_cols = {
        "id", "tenant_id", "agent_name", "valid_from", "valid_to", "system_from", "system_to",
        "input_data", "retrieved_context", "agent_reasoning", "proposed_action",
        "policy_version", "approval_required", "execution_status",
    }
    context_tenant_cols = {
        "id", "tenant_id", "actor_id", "actor_role", "event_type", "agent_name",
        "valid_from", "valid_to", "system_from", "system_to",
        "input_data", "retrieved_context", "agent_reasoning", "proposed_action",
        "policy_version", "approval_required", "execution_status",
    }
    if full_cols.issubset(colset):
        db.execute(_DECISION_LOG_INSERT_EXTENDED, payload)
        return True
    if context_tenant_cols.issubset(colset):
        db.execute(_DECISION_LOG_INSERT_CONTEXT_TENANT, payload)
        return True
    if context_with_tenant_cols.issubset(colset):
        db.execute(_DECISION_LOG_INSERT_CONTEXT_WITH_TENANT, payload)
        return True
    if context_cols.issubset(colset):
        db.execute(_DECISION_LOG_INSERT_CONTEXT, payload)
        return True
    if minimal_cols.issubset(colset):
        db.execute(_DECISION_LOG_INSERT_MINIMAL, payload)
        return True
    return False


def _cache_trace_event(trace_id: str, event: Dict[str, Any]) -> None:
    try:
        with _TRACE_EVENT_CACHE_LOCK:
            arr = _TRACE_EVENT_CACHE[trace_id]
            arr.append(event)
            if len(arr) > _TRACE_EVENT_CACHE_MAX_PER_TRACE:
                del arr[: len(arr) - _TRACE_EVENT_CACHE_MAX_PER_TRACE]
    except Exception:
        pass


def get_cached_trace_events(trace_id: str) -> list[dict[str, Any]]:
    try:
        with _TRACE_EVENT_CACHE_LOCK:
            return list(_TRACE_EVENT_CACHE.get(trace_id, []))
    except Exception:
        return []


def _derive_decision_tags(
    input_data: Dict[str, Any],
    retrieved_context: Dict[str, Any],
    proposed_action: Dict[str, Any],
) -> list[str]:
    tags: list[str] = []
    try:
        if isinstance(input_data, dict):
            q = str(input_data.get("query") or input_data.get("user_query") or "")
            if q:
                tags.append("has_query")
            if input_data.get("images") or input_data.get("image_data"):
                tags.append("has_images")
        if isinstance(retrieved_context, dict):
            if retrieved_context.get("security") is not None:
                tags.append("security_context")
            if retrieved_context.get("candidates") is not None:
                tags.append("candidate_context")
            if retrieved_context.get("forecast") is not None:
                tags.append("forecast_context")
        if isinstance(proposed_action, dict):
            if proposed_action.get("reorder"):
                tags.append("inventory_reorder")
            if proposed_action.get("ranked_skus"):
                tags.append("ranked_output")
            if proposed_action.get("policy_gate"):
                tags.append("policy_gate")
            if proposed_action.get("reason") or proposed_action.get("reasons"):
                tags.append("has_reasons")
    except Exception:
        pass
    # deterministic and bounded
    uniq = sorted(list(dict.fromkeys([str(t) for t in tags if t])))
    return uniq[:24]


def _redis_stream_enabled_by_env() -> bool:
    raw = os.getenv("TRACE_BROKER_REDIS_STREAM_ENABLED")
    if raw is not None:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    app_env = str(os.getenv("APP_ENV", "local") or "local").lower()
    if app_env in ("local", "dev", "development", "test", "testing"):
        return False
    return bool(os.getenv("REDIS_URL"))


def _trace_outbox_enabled() -> bool:
    raw = os.getenv("TRACE_EVENT_OUTBOX_ENABLED")
    if raw is not None:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    app_env = str(os.getenv("APP_ENV", "local") or "local").lower()
    return app_env not in ("test", "testing")


def _decision_log_columns(db) -> list[str]:
    try:
        bind = getattr(db, "get_bind", lambda: None)()
    except Exception:
        bind = None
    key = ""
    try:
        key = str(getattr(bind, "url", "")) if bind is not None else ""
    except Exception:
        key = ""
    if key in _DECISION_LOG_COL_CACHE:
        return _DECISION_LOG_COL_CACHE[key]
    cols: list[str] = []
    dialect = ""
    try:
        dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    except Exception:
        dialect = ""

    if dialect == "sqlite":
        try:
            rows = db.execute(text("PRAGMA table_info(decision_logs)")).fetchall()
            cols = [r[1] for r in rows or [] if len(r) > 1]
        except Exception:
            cols = []
    else:
        try:
            rows = db.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'decision_logs'
                      AND table_schema IN (current_schema(), 'public')
                    """
                )
            ).fetchall()
            cols = [r[0] for r in rows or []]
        except Exception:
            cols = []

    if not cols:
        try:
            db.rollback()
        except Exception:
            pass
    # SQLite schemas are frequently recreated in tests under the same URL;
    # avoid stale schema cache entries that can misroute insert mapping.
    if dialect != "sqlite":
        _DECISION_LOG_COL_CACHE[key] = cols
    return cols


def close_decision_validity(
    decision_id: str,
    *,
    valid_to: str | None = None,
    system_to: str | None = None,
) -> bool:
    """Close open-ended bitemporal ranges for a decision id."""
    if not decision_id:
        return False
    now_ts = __import__("datetime").datetime.utcnow().isoformat()
    vt = valid_to or now_ts
    st = system_to or now_ts
    try:
        with db_session() as db:
            rowcount = db.execute(
                text(
                    """
                    UPDATE decision_logs
                    SET valid_to = :valid_to, system_to = :system_to
                    WHERE id = :id
                      AND (valid_to IS NULL OR valid_to = 'infinity')
                      AND (system_to IS NULL OR system_to = 'infinity')
                    """
                ),
                {"id": decision_id, "valid_to": vt, "system_to": st},
            ).rowcount
            try:
                db.commit()
            except Exception:
                pass
            return bool(int(rowcount or 0) > 0)
    except Exception:
        return False


def log_decision(
    agent_name: str,
    input_data: Dict[str, Any],
    retrieved_context: Dict[str, Any],
    proposed_action: Dict[str, Any],
    agent_reasoning: Optional[str] = None,
    policy_version: str = "v1",
    approval_required: bool = False,
    execution_status: str = "planned",
    decision_id: str | None = None,
    tenant_id: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    event_type: str | None = None,
    supersedes_decision_id: str | None = None,
 ) -> str | None:
    """Persist an evidence-based agent decision with context and action.

    Returns the decision id or None on failure.
    """
    now_ts = __import__("datetime").datetime.utcnow().isoformat()
    dec_id = decision_id or str(uuid.uuid4())
    try:
        if supersedes_decision_id:
            try:
                close_decision_validity(supersedes_decision_id, valid_to=now_ts, system_to=now_ts)
            except Exception:
                pass
        with db_session() as db:
            safe_input = redact_for_trace(security_sanitize(input_data or {}))
            safe_context = redact_for_trace(security_sanitize(retrieved_context or {}))
            safe_action = redact_for_trace(security_sanitize(proposed_action or {}))
            if isinstance(safe_action, dict) and not safe_action.get("decision_tags"):
                safe_action["decision_tags"] = _derive_decision_tags(safe_input, safe_context, safe_action)
            safe_context, safe_action, approval_required, execution_status = _apply_decision_quality_controls(
                safe_context,
                safe_action,
                policy_version=policy_version,
                approval_required=approval_required,
                execution_status=execution_status,
                agent_name=agent_name,
            )
            payload = {
                "id": dec_id,
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "actor_role": actor_role,
                "event_type": event_type,
                "agent_name": agent_name,
                "valid_from": now_ts,
                "valid_to": "infinity",
                "system_from": now_ts,
                "system_to": "infinity",
                "input_data": json.dumps(safe_input, ensure_ascii=False, separators=(",", ":")),
                "retrieved_context": json.dumps(safe_context, ensure_ascii=False, separators=(",", ":")),
                "agent_reasoning": redact_free_text_pii_ner(agent_reasoning or ""),
                "proposed_action": json.dumps(safe_action, ensure_ascii=False, separators=(",", ":")),
                "policy_version": policy_version,
                "approval_required": approval_required,
                "execution_status": execution_status,
            }
            cols = _decision_log_columns(db)
            if not cols:
                try:
                    ensure_metadata()
                except Exception:
                    pass
                cols = _decision_log_columns(db)
            try:
                if cols:
                    if not _exec_decision_log_insert_mapped(db, cols, payload):
                        raise RuntimeError("decision_logs columns not available")
                else:
                    # Fall back to extended insert if we cannot introspect columns
                    db.execute(_DECISION_LOG_INSERT_EXTENDED, payload)
            except Exception:
                logging.exception("decision_logs insert failed; falling back to minimal schema")
                try:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    db.execute(_DECISION_LOG_INSERT_MINIMAL, payload)
                except Exception:
                    logging.exception("decision_logs minimal insert failed")
            try:
                db.commit()
            except Exception:
                logging.exception("Failed to commit decision_logs insert")

        # Evaluate PolicyGraph controls best-effort
        try:
            evaluator = PolicyEvaluator()
            try:
                import inspect
                sig = inspect.signature(evaluator.evaluate_and_persist)
                kwargs = {
                    "decision_id": dec_id,
                    "agent_name": agent_name,
                    "input_data": safe_input,
                    "retrieved_context": safe_context,
                    "proposed_action": safe_action,
                }
                if "tenant_id" in sig.parameters:
                    kwargs["tenant_id"] = tenant_id
                evaluator.evaluate_and_persist(**kwargs)
            except Exception:
                evaluator.evaluate_and_persist(
                    decision_id=dec_id,
                    agent_name=agent_name,
                    input_data=safe_input,
                    retrieved_context=safe_context,
                    proposed_action=safe_action,
                )
        except Exception:
            logging.exception("PolicyEvaluator.evaluate_and_persist failed")

        # Optional RAGAS evaluation on decision write (production path).
        try:
            ragas_enabled = str(os.getenv("RAGAS_EVAL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
            if ragas_enabled:
                try:
                    from src.app.services.ragas_eval import evaluate_and_persist as _ragas_eval

                    _ragas_eval(dec_id)
                except Exception:
                    logging.exception("ragas_eval.evaluate_and_persist failed")
        except Exception:
            pass

        # Best-effort emit a telemetry event for the stored decision
        try:
            try:
                telemetry_emit(
                    {
                        "decision_id": dec_id,
                        "agent_name": agent_name,
                        "tenant_id": tenant_id,
                        "actor_id": actor_id,
                        "actor_role": actor_role,
                        "event_type": event_type,
                        "execution_status": execution_status,
                    },
                    severity="info",
                    sourcetype="shopsquire:decision",
                )
            except Exception:
                logging.exception("telemetry_emit in log_decision failed")
        except Exception:
            pass

        # Best-effort webhook for human escalation events (non-blocking)
        try:
            should_alert = False
            try:
                if approval_required and execution_status and str(execution_status).lower() in ("review_required", "review_pending", "review"):
                    should_alert = True
            except Exception:
                should_alert = False
            try:
                req_actions = []
                if isinstance(safe_action, dict):
                    req_actions = safe_action.get("required_actions") or []
                if any(a in ("human_review", "policy_escalation", "manual_approval", "nonce_live_capture") for a in (req_actions or [])):
                    should_alert = True
            except Exception:
                pass

            if should_alert:
                webhook_url = os.getenv("HUMAN_ESCALATION_WEBHOOK_URL")
                if webhook_url:
                    payload = {
                        "decision_id": dec_id,
                        "agent_name": agent_name,
                        "event_type": event_type,
                        "execution_status": execution_status,
                        "approval_required": approval_required,
                        "proposed_action": safe_action,
                        "retrieved_context": safe_context,
                        "input_data": safe_input,
                    }

                    def _dispatch(p, url):
                        try:
                            data = json.dumps(p, ensure_ascii=False).encode("utf-8")
                            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                            urllib.request.urlopen(req, timeout=3)
                        except Exception:
                            logging.exception("human escalation webhook dispatch failed")

                    try:
                        threading.Thread(target=_dispatch, args=(payload, webhook_url), daemon=True).start()
                    except Exception:
                        try:
                            _dispatch(payload, webhook_url)
                        except Exception:
                            pass
        except Exception:
            logging.exception("human escalation webhook flow failed")

        return dec_id
    except Exception:
        logging.exception("log_decision failed")
        return None


def _extract_raw_confidence(ctx: Dict[str, Any], action: Dict[str, Any]) -> Optional[float]:
    candidates = []
    try:
        if isinstance(action, dict):
            candidates.append(action.get("confidence"))
            if isinstance(action.get("analysis"), dict):
                candidates.append(action.get("analysis", {}).get("confidence"))
    except Exception:
        pass
    try:
        if isinstance(ctx, dict):
            candidates.append(ctx.get("confidence"))
            rq = ctx.get("risk_quantification")
            if isinstance(rq, dict):
                candidates.append(rq.get("confidence"))
    except Exception:
        pass
    for v in candidates:
        if v is None:
            continue
        try:
            fv = float(v)
            if 0.0 <= fv <= 1.0:
                return fv
        except Exception:
            continue
    return None


def _derive_evidence_items(ctx: Dict[str, Any], action: Dict[str, Any]) -> list[dict]:
    items: list[dict] = []
    try:
        existing = action.get("evidence_items")
        if isinstance(existing, list):
            return [x for x in existing if isinstance(x, dict)][:12]
    except Exception:
        pass
    try:
        cands = (ctx.get("candidates") if isinstance(ctx, dict) else None) or []
        for c in cands[:5]:
            if isinstance(c, dict):
                items.append({"type": "candidate", "id": c.get("sku") or c.get("id"), "score": c.get("score")})
    except Exception:
        pass
    try:
        if isinstance(ctx, dict) and isinstance(ctx.get("agent_chain"), list):
            for a in ctx.get("agent_chain")[:4]:
                if isinstance(a, dict):
                    items.append({"type": "agent_step", "id": a.get("agent"), "score": a.get("confidence")})
    except Exception:
        pass
    try:
        if isinstance(ctx, dict) and isinstance(ctx.get("evidence_bundle"), dict):
            items.append({"type": "evidence_bundle", "id": "bundle", "score": 1.0})
    except Exception:
        pass
    return items[:12]


def _apply_decision_quality_controls(
    ctx: Dict[str, Any],
    action: Dict[str, Any],
    *,
    policy_version: str,
    approval_required: bool,
    execution_status: str,
    agent_name: str,
) -> tuple[Dict[str, Any], Dict[str, Any], bool, str]:
    if not isinstance(ctx, dict):
        ctx = {}
    if not isinstance(action, dict):
        action = {"result": action}

    # Enforce evidence contract defaults on every decision payload.
    evidence_items = _derive_evidence_items(ctx, action)
    action.setdefault("evidence_items", evidence_items)
    action.setdefault("evidence_weighting", {"retrieval": 0.45, "rules": 0.35, "policy": 0.20})
    action.setdefault(
        "counterfactual",
        "Decision may change with stronger contradictory evidence, policy override, or materially different constraints.",
    )

    raw_conf = _extract_raw_confidence(ctx, action)
    cal_conf = None
    if raw_conf is not None:
        try:
            cal_conf = calibrate_confidence(raw_conf, agent_type=agent_name)
        except Exception:
            cal_conf = raw_conf
    if cal_conf is not None:
        action["confidence_calibrated"] = float(max(0.0, min(1.0, cal_conf)))
    else:
        action.setdefault("confidence_calibrated", 0.0)

    def _fact_valid(ctx: Dict[str, Any], act: Dict[str, Any]) -> bool:
        if act.get("evidence_items"):
            return True
        # Accept minimal evidence if candidates or dependency health are present
        try:
            if isinstance(ctx, dict) and (ctx.get("candidates") or ctx.get("dependency_health") or ctx.get("agent_chain")):
                return True
        except Exception:
            pass
        return False

    def _policy_valid(version: str) -> bool:
        if not version or not isinstance(version, str):
            return False
        try:
            allowed = {os.getenv("POLICY_VERSION", "v1"), "v1", "v2"}
        except Exception:
            allowed = {"v1", "v2"}
        return version in allowed

    def _output_valid(act: Dict[str, Any]) -> tuple[bool, list[str]]:
        errs: list[str] = []
        if not isinstance(act, dict):
            return False, ["not_dict"]
        # Recognized keys: decision_mode, ranked_skus/results OR action fields like po_created/ticket_id
        has_mode = isinstance(act.get("decision_mode"), (str, type(None)))
        has_results = isinstance(act.get("results"), list) or isinstance(act.get("ranked_skus"), list)
        has_action = any(k in act for k in ("po_created", "ticket_id", "action", "auto_decision"))
        if not (has_results or has_action):
            errs.append("missing_results_or_action")
        if has_results:
            # ensure each result minimally has sku/name
            try:
                res = act.get("results") or []
                if res and isinstance(res, list):
                    for r in res[:5]:
                        if not isinstance(r, dict) or (not r.get("sku") and not r.get("name")):
                            errs.append("invalid_result_item")
                            break
            except Exception:
                errs.append("invalid_results")
        return len(errs) == 0 and has_mode, errs

    verifier_chain = []
    fact_ok = _fact_valid(ctx, action)
    policy_ok = _policy_valid(policy_version)
    out_ok, out_errs = _output_valid(action)
    verifier_chain.append({"name": "fact_verifier", "status": "pass" if fact_ok else "fail"})
    verifier_chain.append({"name": "policy_verifier", "status": "pass" if policy_ok else "fail"})
    verifier_chain.append({"name": "output_validator", "status": "pass" if out_ok else "fail", "errors": out_errs})
    ctx["verifier_chain"] = verifier_chain
    ctx["verifier_chain_enforced"] = True

    # Calibrated abstain policy.
    abstain_threshold = float(os.getenv("DECISION_ABSTAIN_THRESHOLD", "0.45") or 0.45)
    if cal_conf is not None and float(cal_conf) < abstain_threshold:
        action["abstained"] = True
        action["abstain_reason"] = "calibrated_confidence_below_threshold"
        approval_required = True
        execution_status = "review_required"

    strict = str(os.getenv("DECISION_VERIFIER_STRICT", "1")).strip().lower() in ("1", "true", "yes", "on")
    if strict and not (fact_ok and policy_ok and out_ok):
        approval_required = True
        execution_status = "review_required"
        action["verifier_failure"] = [v["name"] for v in verifier_chain if v["status"] != "pass"]
    return ctx, action, approval_required, execution_status


def log_trace_event(
    trace_id: str | None,
    event_type: str,
    source_type: str,
    source_id: str | None,
    target_type: str | None,
    target_id: str | None,
    payload: Dict[str, Any],
    durable: bool = True,
) -> None:
    global _TRACE_TABLE_ENSURED, _OUTBOX_TABLE_ENSURED
    if not trace_id:
        return
    now_ts = __import__("datetime").datetime.utcnow().isoformat()
    event_id = str(uuid.uuid4())
    try:
        canonical_type, original_type = normalize_trace_event_type(event_type)
        event_type = canonical_type
        if not _TRACE_TABLE_ENSURED:
            try:
                from src.app.models.decision_trace_events import ensure_decision_trace_events_table
                ensure_decision_trace_events_table()
                _TRACE_TABLE_ENSURED = True
            except Exception:
                pass
        original_payload = payload or {}
        idempotency_key = None
        try:
            if isinstance(original_payload, dict):
                idempotency_key = original_payload.get("idempotency_key")
        except Exception:
            idempotency_key = None
        if idempotency_key:
            try:
                import hashlib
                event_id = hashlib.sha256(
                    f"{trace_id}:{event_type}:{idempotency_key}".encode("utf-8")
                ).hexdigest()[:32]
            except Exception:
                pass

        contracted_payload = apply_trace_contract(
            event_type=event_type,
            payload=(original_payload if isinstance(original_payload, dict) else {"data": original_payload}),
            source_id=source_id,
            now_ts=now_ts,
        )
        safe_payload = redact_for_trace(security_sanitize(contracted_payload))
        if not isinstance(safe_payload, dict):
            safe_payload = {"data": safe_payload}
        if original_type:
            safe_payload.setdefault("_original_event_type", original_type)
        safe_payload.setdefault("_schema_version", "1.0")
        safe_payload.setdefault("_producer", source_id or source_type or "unknown")
        safe_payload.setdefault("_event_type", event_type)
        broker_payload = {
            "id": event_id,
            "trace_id": trace_id,
            "event_type": event_type,
            "source_type": source_type,
            "source_id": source_id,
            "target_type": target_type,
            "target_id": target_id,
            "payload": safe_payload,
            "created_at": now_ts,
        }
        # Always keep a lightweight in-process copy so readers can recover even
        # when transient DB writes fail under SQLite contention.
        _cache_trace_event(trace_id, broker_payload)
        if not durable:
            try:
                if _publish_sync is not None and not _redis_stream_enabled_by_env():
                    _publish_sync(trace_id, broker_payload)
            except Exception:
                pass
            return
        # Load/smoke mode: when recommendation observer paths are explicitly
        # skipped, avoid expensive durable trace writes for high-throughput
        # benchmark tests.
        try:
            skipped = str(os.getenv("SKIP_OBSERVER_ENDPOINTS", "") or "")
            if "/api/v1/recommend" in skipped:
                return
        except Exception:
            pass

        # Try to persist to DB, but never block broker publication on DB availability.
        try:
            with db_session() as db:
                try:
                    db.execute(
                        text(
                            """
                            INSERT INTO decision_trace_events (
                                id, trace_id, event_type, source_type, source_id,
                                target_type, target_id, payload, created_at
                            ) VALUES (
                                :id, :trace_id, :event_type, :source_type, :source_id,
                                :target_type, :target_id, :payload, :created_at
                            )
                            """
                        ),
                        {
                            "id": event_id,
                            "trace_id": trace_id,
                            "event_type": event_type,
                            "source_type": source_type,
                            "source_id": source_id,
                            "target_type": target_type,
                            "target_id": target_id,
                            "payload": json.dumps(safe_payload, ensure_ascii=False),
                            "created_at": now_ts,
                        },
                    )
                    try:
                        db.commit()
                    except Exception:
                        logging.exception("Failed to commit decision_trace_events insert")
                except Exception as e:
                    # Table/schema may be missing in lightweight test DBs; don't treat as fatal.
                    logging.info("Skipping decision_trace_events DB insert: %s", str(e))
                    # Best-effort fallback: direct engine-level insert for SQLite-heavy
                    # test runs where session-level write may transiently fail.
                    try:
                        from src.app.models.db import get_engine

                        eng = get_engine()
                        with eng.connect() as conn:
                            conn.execute(
                                text(
                                    """
                                    INSERT OR REPLACE INTO decision_trace_events (
                                        id, trace_id, event_type, source_type, source_id,
                                        target_type, target_id, payload, created_at
                                    ) VALUES (
                                        :id, :trace_id, :event_type, :source_type, :source_id,
                                        :target_type, :target_id, :payload, :created_at
                                    )
                                    """
                                ),
                                {
                                    "id": event_id,
                                    "trace_id": trace_id,
                                    "event_type": event_type,
                                    "source_type": source_type,
                                    "source_id": source_id,
                                    "target_type": target_type,
                                    "target_id": target_id,
                                    "payload": json.dumps(safe_payload, ensure_ascii=False),
                                    "created_at": now_ts,
                                },
                            )
                            try:
                                conn.commit()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        record_decision_trace_write_failure("db_insert")
                    except Exception:
                        pass
        except Exception as e:
            # DB session itself may fail (e.g., DB down).
            logging.info("Skipping decision_trace_events DB session: %s", str(e))
            try:
                record_decision_trace_write_failure("db_session")
            except Exception:
                pass

        # Outbox entry for async downstream delivery (CDC/outbox style).
        if _trace_outbox_enabled():
            try:
                if not _OUTBOX_TABLE_ENSURED:
                    try:
                        from src.app.models.event_log import ensure_event_log_table
                        ensure_event_log_table()
                        _OUTBOX_TABLE_ENSURED = True
                    except Exception:
                        pass
                with db_session() as db2:
                    try:
                        db2.execute(
                            text(
                                """
                                INSERT INTO event_log (id, type, payload, status, delivery_url, created_at)
                                VALUES (:id, :type, :payload, 'pending', NULL, :created_at)
                                """
                            ),
                            {
                                "id": f"trace:{event_id}",
                                "type": "decision_trace_event",
                                "payload": json.dumps(broker_payload, ensure_ascii=False),
                                "created_at": now_ts,
                            },
                        )
                        try:
                            db2.commit()
                        except Exception:
                            logging.exception("Failed to commit event_log outbox insert")
                    except Exception:
                        # best-effort only
                        try:
                            record_decision_trace_write_failure("outbox_insert")
                        except Exception:
                            pass
                        pass
            except Exception:
                try:
                    record_decision_trace_write_failure("outbox_session")
                except Exception:
                    pass
                pass

        # Publish trace event to in-process broker for realtime UIs (best-effort)
        try:
            try:
                    loop = asyncio.get_event_loop()
                    redis_stream_enabled = _redis_stream_enabled_by_env()
                    # Fast path in high-throughput local/test mode: synchronous publish
                    # avoids scheduling thousands of tiny asyncio tasks.
                    if _publish_sync is not None and not redis_stream_enabled:
                        _publish_sync(trace_id, broker_payload)
                    elif loop.is_running():
                        loop.create_task(_publish_trace(trace_id, broker_payload))
                    else:
                        if _publish_sync is not None and not redis_stream_enabled:
                            try:
                                _publish_sync(trace_id, broker_payload)
                            except Exception:
                                pass
                        else:
                            # Fallback: spawn a single background thread for async run
                            def _run():
                                try:
                                    asyncio.run(_publish_trace(trace_id, broker_payload))
                                except Exception:
                                    logging.exception("_publish_trace failed in background thread (inner)")

                            t = threading.Thread(target=_run, daemon=True)
                            t.start()
            except Exception:
                # fallback: try cached sync publish helper
                if _publish_sync is not None:
                    try:
                        _publish_sync(trace_id, broker_payload)
                    except Exception:
                        pass
                else:
                    def _run2():
                        try:
                            asyncio.run(_publish_trace(trace_id, broker_payload))
                        except Exception:
                            logging.exception("_publish_trace final fallback failed (inner)")

                    threading.Thread(target=_run2, daemon=True).start()
        except Exception:
            logging.exception("Failed to publish trace event to broker")
        # Non-fatal: return even if DB insert failed
        return
    except Exception:
        logging.exception("log_trace_event failed")
        try:
            record_decision_trace_write_failure("unexpected")
        except Exception:
            pass
        return


# ── Commerce outcome feedback ─────────────────────────────────────────────

def record_commerce_outcome(
    decision_id: str,
    *,
    upsell_clicked: Optional[bool] = None,
    bundle_purchased: Optional[bool] = None,
    coupon_redeemed: Optional[bool] = None,
    fraud_review_triggered: Optional[bool] = None,
    aov_delta_cents: Optional[int] = None,
    conversion: Optional[bool] = None,
    abandonment: Optional[bool] = None,
    coupon_risk_score: Optional[float] = None,
    abuse_signals: Optional[Dict[str, Any]] = None,
    intervention_type: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str | None:
    """Write a commerce-outcome record that supersedes (closes) the original decision.

    Creates a new decision_log entry of event_type ``commerce_outcome`` linked
    to the original via ``supersedes_decision_id``, and closes the original's
    bitemporal validity window.  Returns the new outcome decision_id or None
    on failure.
    """
    if not decision_id:
        return None

    outcome_payload: Dict[str, Any] = {}
    if upsell_clicked is not None:
        outcome_payload["upsell_clicked"] = upsell_clicked
    if bundle_purchased is not None:
        outcome_payload["bundle_purchased"] = bundle_purchased
    if coupon_redeemed is not None:
        outcome_payload["coupon_redeemed"] = coupon_redeemed
    if fraud_review_triggered is not None:
        outcome_payload["fraud_review_triggered"] = fraud_review_triggered
    if aov_delta_cents is not None:
        outcome_payload["aov_delta_cents"] = int(aov_delta_cents)
    if conversion is not None:
        outcome_payload["conversion"] = conversion
    if abandonment is not None:
        outcome_payload["abandonment"] = abandonment
    if coupon_risk_score is not None:
        outcome_payload["coupon_risk_score"] = round(float(coupon_risk_score), 4)
    if abuse_signals is not None:
        outcome_payload["abuse_signals"] = abuse_signals
    if intervention_type is not None:
        outcome_payload["intervention_type"] = str(intervention_type)
    if extra and isinstance(extra, dict):
        outcome_payload.update(extra)

    try:
        return log_decision(
            agent_name="commerce_outcome_writer",
            input_data={"original_decision_id": decision_id},
            retrieved_context={"outcome": outcome_payload},
            proposed_action={"decision_mode": "outcome_feedback", "action": "record_outcome", **outcome_payload},
            event_type="commerce_outcome",
            execution_status="completed",
            supersedes_decision_id=decision_id,
        )
    except Exception:
        logging.exception("record_commerce_outcome failed for decision_id=%s", decision_id)
        return None
