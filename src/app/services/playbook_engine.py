from __future__ import annotations

import copy
import difflib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from src.app.deps import redact_for_trace, security_sanitize
from src.app.models.db import db_session
from src.app.services.playbook_action_adapters import email_action, erp_action, shipping_action, ip_block_action, rate_limit_action
from src.app.services.decision_log import log_trace_event


DEFAULT_RISK_ORDER = ["low", "medium", "high", "critical"]
DEFAULT_TRIGGER_LOGIC = "any"
DEFAULT_PLAYBOOK_DOMAIN = "security"
SUPPORTED_TRIGGER_LOGIC = {"any", "all"}
SUPPORTED_RUN_STATUS = {"started", "running", "completed", "failed", "cancelled"}

_CFG_CACHE_LOCK = threading.Lock()
_CFG_CACHE: Dict[str, Any] = {"mtime": None, "payload": None}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _playbooks_path() -> Path:
    return Path("config") / "security" / "cv_playbooks.json"


def _playbook_versions_path() -> Path:
    return Path("config") / "security" / "versions" / "playbooks"


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _coerce_playbook(entry: Dict[str, Any], *, default_version: str = "1.0.0") -> Dict[str, Any]:
    pb = copy.deepcopy(entry or {})
    pb.setdefault("domain", DEFAULT_PLAYBOOK_DOMAIN)
    pb.setdefault("priority", 100)
    pb.setdefault("enabled", True)
    pb.setdefault("version", default_version)
    pb.setdefault("trigger_logic", DEFAULT_TRIGGER_LOGIC)
    pb.setdefault("entry_conditions", {})
    pb.setdefault("actions", [])
    pb.setdefault("sla_minutes", 60)
    pb.setdefault("rollback", {"enabled": False, "strategy": "manual"})
    pb.setdefault("requires_approval_roles", [])
    pb.setdefault("risk_band_min", "low")
    pb.setdefault("checks", [])
    pb.setdefault("owners", [])
    pb.setdefault("closure_criteria", [])
    if "severity" not in pb:
        pb["severity"] = "medium"
    return pb


def _coerce_config(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    base = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {
        "schema_version": str(base.get("schema_version") or "2.0"),
        "published_at": base.get("published_at") or _utc_now(),
        "risk_band_order": base.get("risk_band_order") if isinstance(base.get("risk_band_order"), list) else list(DEFAULT_RISK_ORDER),
        "playbooks": [],
        "signal_map": base.get("signal_map") if isinstance(base.get("signal_map"), dict) else {},
        "tag_map": base.get("tag_map") if isinstance(base.get("tag_map"), dict) else {},
    }
    playbooks = base.get("playbooks") if isinstance(base.get("playbooks"), list) else []
    for item in playbooks:
        if isinstance(item, dict):
            out["playbooks"].append(_coerce_playbook(item))
    return out


def _get_risk_rank(band: str | None, order: List[str]) -> int:
    if not band:
        return 0
    try:
        return order.index(str(band).lower())
    except Exception:
        return 0


def _load_config_uncached() -> Dict[str, Any]:
    path = _playbooks_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = {
            "schema_version": "2.0",
            "risk_band_order": list(DEFAULT_RISK_ORDER),
            "playbooks": [],
            "signal_map": {},
            "tag_map": {},
        }
    return _coerce_config(raw)


def load_playbook_config(*, force_reload: bool = False) -> Dict[str, Any]:
    path = _playbooks_path()
    with _CFG_CACHE_LOCK:
        current_mtime = None
        try:
            current_mtime = path.stat().st_mtime
        except Exception:
            current_mtime = None
        if not force_reload and _CFG_CACHE.get("payload") is not None and _CFG_CACHE.get("mtime") == current_mtime:
            return copy.deepcopy(_CFG_CACHE["payload"])
        cfg = _load_config_uncached()
        _CFG_CACHE["mtime"] = current_mtime
        _CFG_CACHE["payload"] = cfg
        return copy.deepcopy(cfg)


def validate_playbook_config(config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    cfg = _coerce_config(config)
    ids: set[str] = set()
    pb_by_id: Dict[str, Dict[str, Any]] = {}
    order = cfg.get("risk_band_order") if isinstance(cfg.get("risk_band_order"), list) else list(DEFAULT_RISK_ORDER)

    for idx, pb in enumerate(cfg.get("playbooks") or []):
        pbid = str(pb.get("id") or "").strip()
        if not pbid:
            errors.append(f"playbooks[{idx}].id missing")
            continue
        if not pbid.startswith("PB-"):
            errors.append(f"playbooks[{idx}].id must start with PB-")
        if pbid in ids:
            errors.append(f"duplicate playbook id: {pbid}")
        ids.add(pbid)
        pb_by_id[pbid] = pb
        trig_logic = str(pb.get("trigger_logic") or DEFAULT_TRIGGER_LOGIC).lower()
        if trig_logic not in SUPPORTED_TRIGGER_LOGIC:
            errors.append(f"{pbid}.trigger_logic must be one of {sorted(SUPPORTED_TRIGGER_LOGIC)}")
        if _get_risk_rank(pb.get("risk_band_min"), order) < 0:
            errors.append(f"{pbid}.risk_band_min invalid")
        try:
            int(pb.get("priority") or 100)
        except Exception:
            errors.append(f"{pbid}.priority must be int")
        try:
            int(pb.get("sla_minutes") or 0)
        except Exception:
            errors.append(f"{pbid}.sla_minutes must be int")
        actions = pb.get("actions")
        if not isinstance(actions, list):
            errors.append(f"{pbid}.actions must be list")
        else:
            for a_idx, action in enumerate(actions):
                if isinstance(action, str):
                    continue
                if not isinstance(action, dict):
                    errors.append(f"{pbid}.actions[{a_idx}] must be object")
                    continue
                if not action.get("type"):
                    errors.append(f"{pbid}.actions[{a_idx}].type missing")

    for map_name in ("signal_map", "tag_map"):
        mapping = cfg.get(map_name)
        if not isinstance(mapping, dict):
            errors.append(f"{map_name} must be object")
            continue
        for key, pb_ids in mapping.items():
            if not isinstance(pb_ids, list):
                errors.append(f"{map_name}.{key} must be list")
                continue
            for pbid in pb_ids:
                if pbid not in pb_by_id:
                    errors.append(f"{map_name}.{key} references unknown playbook: {pbid}")

    return (len(errors) == 0, errors)


def _is_entry_condition_match(playbook: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    entry = playbook.get("entry_conditions")
    if not isinstance(entry, dict) or not entry:
        return True
    tenant = str(ctx.get("tenant_id") or "")
    channel = str(ctx.get("channel") or "")
    signal = str(ctx.get("signal") or "")
    min_score = entry.get("min_score")
    tenant_allow = entry.get("tenant_allowlist")
    channels = entry.get("channels")
    signals = entry.get("signals")
    current_score = ctx.get("score")
    if isinstance(tenant_allow, list) and tenant_allow and tenant not in [str(x) for x in tenant_allow]:
        return False
    # Treat missing context as unknown, not a hard mismatch. This keeps
    # tag-driven selection usable in low-context paths (e.g., tests/demo drilldown).
    if isinstance(channels, list) and channels and channel and channel not in [str(x) for x in channels]:
        return False
    if isinstance(signals, list) and signals and signal and signal not in [str(x) for x in signals]:
        return False
    if min_score is not None and current_score is not None:
        try:
            if float(current_score) < float(min_score):
                return False
        except Exception:
            return False
    return True


def select_playbook_from_tags(
    evidence_tags: List[str],
    risk_band: str | None,
    *,
    context: Optional[Dict[str, Any]] = None,
    include_disabled: bool = False,
) -> Optional[Dict[str, Any]]:
    cfg = load_playbook_config()
    tag_map = cfg.get("tag_map") if isinstance(cfg.get("tag_map"), dict) else {}
    playbooks = cfg.get("playbooks") if isinstance(cfg.get("playbooks"), list) else []
    risk_order = cfg.get("risk_band_order") if isinstance(cfg.get("risk_band_order"), list) else list(DEFAULT_RISK_ORDER)
    if not evidence_tags:
        return None
    tag_set = {str(t) for t in evidence_tags if t}
    if not tag_set:
        return None

    candidate_ids: set[str] = set()
    for tag in tag_set:
        ids = tag_map.get(tag) if isinstance(tag_map.get(tag), list) else []
        for pid in ids:
            if pid:
                candidate_ids.add(str(pid))

    candidates: List[Tuple[int, int, str, Dict[str, Any], List[str]]] = []
    ctx = context or {}
    for pb in playbooks:
        pbid = str(pb.get("id") or "")
        if pbid not in candidate_ids:
            continue
        if not include_disabled and not bool(pb.get("enabled", True)):
            continue
        min_band = pb.get("risk_band_min") or "low"
        if _get_risk_rank(risk_band, risk_order) < _get_risk_rank(min_band, risk_order):
            continue
        if not _is_entry_condition_match(pb, ctx):
            continue
        pb_tags = [t for t in tag_set if pbid in (tag_map.get(t) or [])]
        trig_logic = str(pb.get("trigger_logic") or DEFAULT_TRIGGER_LOGIC).lower()
        required_tags = pb.get("required_tags") if isinstance(pb.get("required_tags"), list) else []
        if trig_logic == "all" and required_tags:
            req = {str(t) for t in required_tags if t}
            if not req.issubset(tag_set):
                continue
        priority = int(pb.get("priority") or 100)
        risk_rank = _get_risk_rank(pb.get("risk_band_min"), risk_order)
        candidates.append((risk_rank, -priority, pbid, pb, pb_tags))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    chosen = candidates[0]
    return {
        "playbook": chosen[3],
        "triggered_by": chosen[4],
        "risk_band": risk_band,
    }


def list_playbooks(*, include_disabled: bool = True, domain: str | None = None) -> List[Dict[str, Any]]:
    cfg = load_playbook_config()
    out: List[Dict[str, Any]] = []
    for pb in cfg.get("playbooks") or []:
        if not include_disabled and not bool(pb.get("enabled", True)):
            continue
        if domain and str(pb.get("domain") or "").lower() != str(domain).lower():
            continue
        out.append(pb)
    out.sort(key=lambda p: (str(p.get("domain") or ""), int(p.get("priority") or 100), str(p.get("id") or "")))
    return out


def get_playbook_by_id(playbook_id: str | None) -> Optional[Dict[str, Any]]:
    if not playbook_id:
        return None
    for pb in list_playbooks(include_disabled=True):
        if str(pb.get("id")) == str(playbook_id):
            return pb
    return None


def dry_run_playbook_selection(
    *,
    tags: List[str],
    risk_band: str | None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    sel = select_playbook_from_tags(tags, risk_band, context=context)
    return {
        "input": {"tags": tags, "risk_band": risk_band, "context": context or {}},
        "selection": sel,
        "matched": bool(sel),
    }


def _next_semver(prev: str | None) -> str:
    if not prev:
        return "1.0.0"
    parts = str(prev).split(".")
    if len(parts) != 3:
        return "1.0.0"
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{major}.{minor}.{patch + 1}"
    except Exception:
        return "1.0.0"


def publish_playbook_update(
    *,
    playbook_id: str,
    updates: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    cfg = load_playbook_config(force_reload=True)
    found = False
    before: Optional[Dict[str, Any]] = None
    for idx, pb in enumerate(cfg.get("playbooks") or []):
        if str(pb.get("id")) != str(playbook_id):
            continue
        found = True
        before = copy.deepcopy(pb)
        merged = copy.deepcopy(pb)
        for key, value in (updates or {}).items():
            if key == "id":
                continue
            merged[key] = value
        merged["version"] = _next_semver(before.get("version"))
        merged["updated_by"] = actor
        merged["updated_at"] = _utc_now()
        cfg["playbooks"][idx] = _coerce_playbook(merged, default_version=merged["version"])
        break
    if not found:
        raise ValueError("playbook_not_found")
    ok, errs = validate_playbook_config(cfg)
    if not ok:
        raise ValueError("invalid_config: " + "; ".join(errs))
    cfg["published_at"] = _utc_now()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    versions_path = _playbook_versions_path()
    versions_path.mkdir(parents=True, exist_ok=True)
    snapshot_name = f"{stamp}_{playbook_id}_{(before or {}).get('version','0')}_to_{cfg['playbooks'][idx].get('version')}.json"
    snapshot_path = versions_path / snapshot_name
    snapshot_payload = {
        "snapshot_at": _utc_now(),
        "actor": actor,
        "playbook_id": playbook_id,
        "before": before,
        "after": cfg["playbooks"][idx],
    }
    _atomic_write_json(snapshot_path, snapshot_payload)
    _atomic_write_json(_playbooks_path(), cfg)
    load_playbook_config(force_reload=True)
    return {"playbook_id": playbook_id, "snapshot": str(snapshot_path), "before": before, "after": cfg["playbooks"][idx]}


def rollback_playbook_version(*, playbook_id: str, target_version: str, actor: str) -> Dict[str, Any]:
    cfg = load_playbook_config(force_reload=True)
    versions_dir = _playbook_versions_path()
    if not versions_dir.exists():
        raise ValueError("version_history_not_found")
    target_pb: Optional[Dict[str, Any]] = None
    for snapshot in sorted(versions_dir.glob("*.json"), reverse=True):
        try:
            content = json.loads(snapshot.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(content.get("playbook_id")) != str(playbook_id):
            continue
        for side in ("after", "before"):
            candidate = content.get(side)
            if isinstance(candidate, dict) and str(candidate.get("version")) == str(target_version):
                target_pb = copy.deepcopy(candidate)
                break
        if target_pb is not None:
            break
    if target_pb is None:
        raise ValueError("target_version_not_found")

    replaced = False
    previous: Optional[Dict[str, Any]] = None
    for i, pb in enumerate(cfg.get("playbooks") or []):
        if str(pb.get("id")) == str(playbook_id):
            previous = copy.deepcopy(pb)
            target_pb["updated_by"] = actor
            target_pb["updated_at"] = _utc_now()
            cfg["playbooks"][i] = _coerce_playbook(target_pb, default_version=str(target_pb.get("version") or "1.0.0"))
            replaced = True
            break
    if not replaced:
        raise ValueError("playbook_not_found")
    ok, errs = validate_playbook_config(cfg)
    if not ok:
        raise ValueError("invalid_config: " + "; ".join(errs))
    cfg["published_at"] = _utc_now()
    _atomic_write_json(_playbooks_path(), cfg)
    load_playbook_config(force_reload=True)
    return {"playbook_id": playbook_id, "before": previous, "after": target_pb}


def diff_playbook_versions(*, playbook_id: str, from_version: str, to_version: str) -> Dict[str, Any]:
    versions_dir = _playbook_versions_path()
    if not versions_dir.exists():
        return {"playbook_id": playbook_id, "from_version": from_version, "to_version": to_version, "diff": []}
    objs: Dict[str, Dict[str, Any]] = {}
    for snapshot in sorted(versions_dir.glob("*.json")):
        try:
            content = json.loads(snapshot.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(content.get("playbook_id")) != str(playbook_id):
            continue
        for side in ("before", "after"):
            pb = content.get(side)
            if isinstance(pb, dict) and pb.get("version"):
                objs[str(pb.get("version"))] = pb
    if from_version not in objs or to_version not in objs:
        return {"playbook_id": playbook_id, "from_version": from_version, "to_version": to_version, "diff": []}
    from_text = json.dumps(objs[from_version], indent=2, sort_keys=True).splitlines()
    to_text = json.dumps(objs[to_version], indent=2, sort_keys=True).splitlines()
    diff = list(difflib.unified_diff(from_text, to_text, fromfile=from_version, tofile=to_version, lineterm=""))
    return {"playbook_id": playbook_id, "from_version": from_version, "to_version": to_version, "diff": diff}


def ensure_playbook_run_tables() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS playbook_runs (
                        id TEXT PRIMARY KEY,
                        trace_id TEXT,
                        decision_id TEXT,
                        tenant_id TEXT,
                        playbook_id TEXT NOT NULL,
                        playbook_version TEXT NOT NULL,
                        owner TEXT,
                        status TEXT NOT NULL,
                        outcome TEXT,
                        posthoc_outcome_id TEXT,
                        metadata_json TEXT,
                        started_at TEXT NOT NULL,
                        ended_at TEXT
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS playbook_run_steps (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        step_index INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        evidence_json TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS playbook_action_executions (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        step_index INTEGER NOT NULL,
                        action_type TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        attempt INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        result_json TEXT,
                        error TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS playbook_action_dlq (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        step_index INTEGER NOT NULL,
                        action_type TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        last_error TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            )
            try:
                db.execute(text("CREATE INDEX IF NOT EXISTS idx_playbook_runs_trace ON playbook_runs(trace_id)"))
                db.execute(text("CREATE INDEX IF NOT EXISTS idx_playbook_runs_playbook ON playbook_runs(playbook_id, playbook_version)"))
                db.execute(text("CREATE INDEX IF NOT EXISTS idx_playbook_run_steps_run ON playbook_run_steps(run_id, step_index)"))
                db.execute(text("CREATE INDEX IF NOT EXISTS idx_playbook_action_exec_idem ON playbook_action_executions(idempotency_key)"))
                db.execute(text("CREATE INDEX IF NOT EXISTS idx_playbook_action_dlq_run ON playbook_action_dlq(run_id, step_index)"))
            except Exception:
                pass
            try:
                db.commit()
            except Exception:
                pass
    except Exception:
        pass


def start_playbook_run(
    *,
    trace_id: str | None,
    decision_id: str | None,
    tenant_id: str | None,
    playbook: Dict[str, Any],
    owner: str | None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    ensure_playbook_run_tables()
    run_id = str(uuid.uuid4())
    started = _utc_now()
    safe_meta = redact_for_trace(security_sanitize(metadata or {}))
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO playbook_runs (
                        id, trace_id, decision_id, tenant_id, playbook_id, playbook_version,
                        owner, status, outcome, metadata_json, started_at
                    ) VALUES (
                        :id, :trace_id, :decision_id, :tenant_id, :playbook_id, :playbook_version,
                        :owner, :status, :outcome, :metadata_json, :started_at
                    )
                    """
                ),
                {
                    "id": run_id,
                    "trace_id": trace_id,
                    "decision_id": decision_id,
                    "tenant_id": tenant_id,
                    "playbook_id": str(playbook.get("id") or ""),
                    "playbook_version": str(playbook.get("version") or "1.0.0"),
                    "owner": owner,
                    "status": "started",
                    "outcome": None,
                    "metadata_json": json.dumps(safe_meta, ensure_ascii=False),
                    "started_at": started,
                },
            )
            db.commit()
        try:
            # Emit a decision trace event so runs are visible in bitemporal trace streams
            trace_or_decision = trace_id or decision_id
            if trace_or_decision:
                payload = {
                    "playbook_id": str(playbook.get("id") or ""),
                    "version": str(playbook.get("version") or "1.0.0"),
                    "owner": owner,
                    "metadata": safe_meta,
                }
                # Best-effort taxonomy fields if present in config
                try:
                    if isinstance(playbook, dict):
                        mitre = playbook.get("mitre_techniques") or playbook.get("mitre_atlas")
                        owasp = playbook.get("owasp_llm_top10") or playbook.get("owasp_categories")
                        stride = playbook.get("stride_categories")
                        pasta = playbook.get("pasta_stage")
                        if mitre:
                            payload["mitre"] = mitre
                        if owasp:
                            payload["owasp"] = owasp
                        if stride:
                            payload["stride"] = stride
                        if pasta:
                            payload["pasta_stage"] = pasta
                except Exception:
                    pass
                log_trace_event(
                    trace_id=trace_or_decision,
                    event_type="playbook_run_started",
                    source_type="agent",
                    source_id="Playbook_Engine",
                    target_type="playbook",
                    target_id=str(playbook.get("id") or ""),
                    payload=payload,
                )
        except Exception:
            pass
        return run_id
    except Exception:
        return None


def append_playbook_step(
    *,
    run_id: str,
    event_type: str,
    status: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    ensure_playbook_run_tables()
    step_id = str(uuid.uuid4())
    safe_ev = redact_for_trace(security_sanitize(evidence or {}))
    try:
        with db_session() as db:
            row = db.execute(
                text("SELECT COALESCE(MAX(step_index), -1) FROM playbook_run_steps WHERE run_id = :rid"),
                {"rid": run_id},
            ).fetchone()
            next_idx = int(row[0] or -1) + 1 if row else 0
            db.execute(
                text(
                    """
                    INSERT INTO playbook_run_steps (
                        id, run_id, step_index, event_type, status, evidence_json, created_at
                    ) VALUES (
                        :id, :run_id, :step_index, :event_type, :status, :evidence_json, :created_at
                    )
                    """
                ),
                {
                    "id": step_id,
                    "run_id": run_id,
                    "step_index": next_idx,
                    "event_type": event_type,
                    "status": status,
                    "evidence_json": json.dumps(safe_ev, ensure_ascii=False),
                    "created_at": _utc_now(),
                },
            )
            db.execute(text("UPDATE playbook_runs SET status = :status WHERE id = :rid"), {"status": "running", "rid": run_id})
            db.commit()
        try:
            # Emit step-level trace event for UI correlation
            trace_or_decision = _get_trace_for_run(run_id)
            if trace_or_decision:
                log_trace_event(
                    trace_id=trace_or_decision,
                    event_type="playbook_step",
                    source_type="agent",
                    source_id="Playbook_Engine",
                    target_type="playbook",
                    target_id=run_id,
                    payload={
                        "run_id": run_id,
                        "step_index": next_idx,
                        "event_type": event_type,
                        "status": status,
                        "evidence": safe_ev,
                    },
                )
        except Exception:
            pass
        return step_id
    except Exception:
        return None


def complete_playbook_run(
    *,
    run_id: str,
    status: str,
    outcome: str | None,
    posthoc_outcome_id: str | None = None,
) -> bool:
    ensure_playbook_run_tables()
    st = str(status or "completed").lower()
    if st not in SUPPORTED_RUN_STATUS:
        st = "completed"
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    UPDATE playbook_runs
                    SET status = :status,
                        outcome = :outcome,
                        posthoc_outcome_id = COALESCE(:posthoc_outcome_id, posthoc_outcome_id),
                        ended_at = :ended_at
                    WHERE id = :id
                    """
                ),
                {
                    "status": st,
                    "outcome": outcome,
                    "posthoc_outcome_id": posthoc_outcome_id,
                    "ended_at": _utc_now(),
                    "id": run_id,
                },
            )
            db.commit()
        try:
            trace_or_decision = _get_trace_for_run(run_id)
            if trace_or_decision:
                log_trace_event(
                    trace_id=trace_or_decision,
                    event_type="playbook_run_completed",
                    source_type="agent",
                    source_id="Playbook_Engine",
                    target_type="playbook",
                    target_id=run_id,
                    payload={"run_id": run_id, "status": st, "outcome": outcome, "posthoc_outcome_id": posthoc_outcome_id},
                )
        except Exception:
            pass
        return True
    except Exception:
        return False


def link_posthoc_to_run(*, decision_id: str, posthoc_outcome_id: str, outcome_value: str | None) -> None:
    ensure_playbook_run_tables()
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT id
                    FROM playbook_runs
                    WHERE decision_id = :decision_id OR trace_id = :decision_id
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                ),
                {"decision_id": decision_id},
            ).fetchone()
            if not row:
                return
            run_id = str(row[0])
            db.execute(
                text(
                    """
                    UPDATE playbook_runs
                    SET posthoc_outcome_id = :posthoc_outcome_id,
                        outcome = COALESCE(:outcome, outcome)
                    WHERE id = :run_id
                    """
                ),
                {"posthoc_outcome_id": posthoc_outcome_id, "outcome": outcome_value, "run_id": run_id},
            )
            db.commit()
    except Exception:
        pass


def get_playbook_kpis(*, days: int = 30) -> Dict[str, Any]:
    ensure_playbook_run_tables()
    days = max(1, min(int(days or 30), 365))
    out: Dict[str, Any] = {"days": days, "by_playbook": [], "totals": {}}
    try:
        with db_session() as db:
            dialect = ""
            try:
                bind = getattr(db, "bind", None) or getattr(db, "get_bind", lambda: None)()
                dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
            except Exception:
                dialect = ""
            if dialect.startswith("postgres"):
                kpi_sql = """
                    SELECT
                        playbook_id,
                        COUNT(*) AS total_runs,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_runs,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
                        SUM(CASE WHEN outcome IN ('true_positive','success','effective') THEN 1 ELSE 0 END) AS positives,
                        SUM(CASE WHEN outcome IN ('false_positive','incorrect') THEN 1 ELSE 0 END) AS false_positives,
                        AVG(
                            CASE
                                WHEN ended_at IS NOT NULL THEN
                                    EXTRACT(EPOCH FROM ((ended_at)::timestamptz - (started_at)::timestamptz)) / 60.0
                                ELSE NULL
                            END
                        ) AS mean_time_to_close_min
                    FROM playbook_runs
                    WHERE (started_at)::timestamptz >= NOW() - (:days * INTERVAL '1 day')
                    GROUP BY playbook_id
                    ORDER BY total_runs DESC
                """
                params = {"days": days}
            else:
                kpi_sql = """
                    SELECT
                        playbook_id,
                        COUNT(*) AS total_runs,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_runs,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
                        SUM(CASE WHEN outcome IN ('true_positive','success','effective') THEN 1 ELSE 0 END) AS positives,
                        SUM(CASE WHEN outcome IN ('false_positive','incorrect') THEN 1 ELSE 0 END) AS false_positives,
                        AVG(
                            CASE
                                WHEN ended_at IS NOT NULL THEN
                                    (julianday(ended_at) - julianday(started_at)) * 1440.0
                                ELSE NULL
                            END
                        ) AS mean_time_to_close_min
                    FROM playbook_runs
                    WHERE started_at >= datetime('now', :window)
                    GROUP BY playbook_id
                    ORDER BY total_runs DESC
                """
                params = {"window": f"-{days} day"}
            rows = db.execute(
                text(kpi_sql),
                params,
            ).fetchall()
            by_playbook = []
            total_runs = 0
            total_fp = 0
            total_pos = 0
            for r in rows or []:
                runs = int(r[1] or 0)
                fp = int(r[5] or 0)
                pos = int(r[4] or 0)
                precision = (float(pos) / float(max(pos + fp, 1))) if (pos + fp) > 0 else None
                total_runs += runs
                total_fp += fp
                total_pos += pos
                by_playbook.append(
                    {
                        "playbook_id": r[0],
                        "total_runs": runs,
                        "completed_runs": int(r[2] or 0),
                        "failed_runs": int(r[3] or 0),
                        "positives": pos,
                        "false_positives": fp,
                        "trigger_precision": precision,
                        "mean_time_to_close_min": float(r[6]) if r[6] is not None else None,
                    }
                )
            out["by_playbook"] = by_playbook
            out["totals"] = {
                "total_runs": total_runs,
                "positives": total_pos,
                "false_positives": total_fp,
                "trigger_precision": (float(total_pos) / float(max(total_pos + total_fp, 1))) if (total_pos + total_fp) > 0 else None,
            }
    except Exception:
        pass
    return out


def get_playbook_action_reliability(*, days: int = 30) -> Dict[str, Any]:
    ensure_playbook_run_tables()
    days = max(1, min(int(days or 30), 365))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()
    out: Dict[str, Any] = {
        "days": days,
        "totals": {
            "attempts": 0,
            "completed": 0,
            "failed": 0,
            "dlq": 0,
            "completion_rate": None,
        },
        "by_action": [],
        "by_provider": [],
    }
    try:
        with db_session() as db:
            attempts_rows = db.execute(
                text(
                    """
                    SELECT action_type,
                           COUNT(*) AS attempts,
                           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                           SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
                    FROM playbook_action_executions
                    WHERE created_at >= :cutoff
                    GROUP BY action_type
                    ORDER BY attempts DESC
                    """
                ),
                {"cutoff": cutoff_iso},
            ).fetchall()
            dlq_rows = db.execute(
                text(
                    """
                    SELECT action_type, COUNT(*) AS dlq_count
                    FROM playbook_action_dlq
                    WHERE created_at >= :cutoff
                    GROUP BY action_type
                    """
                ),
                {"cutoff": cutoff_iso},
            ).fetchall()
            provider_rows = db.execute(
                text(
                    """
                    SELECT status, result_json
                    FROM playbook_action_executions
                    WHERE created_at >= :cutoff
                    """
                ),
                {"cutoff": cutoff_iso},
            ).fetchall()
        dlq_by_action = {str(r[0] or ""): int(r[1] or 0) for r in dlq_rows or []}
        provider_acc: Dict[str, Dict[str, Any]] = {}
        total_attempts = 0
        total_completed = 0
        total_failed = 0
        total_dlq = 0
        for r in attempts_rows or []:
            action_type = str(r[0] or "")
            attempts = int(r[1] or 0)
            completed = int(r[2] or 0)
            failed = int(r[3] or 0)
            dlq = int(dlq_by_action.get(action_type, 0))
            total_attempts += attempts
            total_completed += completed
            total_failed += failed
            total_dlq += dlq
            out["by_action"].append(
                {
                    "action_type": action_type,
                    "attempts": attempts,
                    "completed": completed,
                    "failed": failed,
                    "dlq": dlq,
                    "completion_rate": (float(completed) / float(max(attempts, 1))) if attempts > 0 else None,
                }
            )
        for r in provider_rows or []:
            status = str(r[0] or "")
            provider = "unknown"
            backoff_ms = 0
            retry_events = 0
            try:
                payload = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
                if isinstance(payload, dict):
                    provider = str(payload.get("provider") or payload.get("provider_name") or "unknown")
                    backoff_raw = payload.get("backoff_ms")
                    if isinstance(backoff_raw, (int, float)):
                        backoff_ms = int(backoff_raw)
                    elif isinstance(backoff_raw, str):
                        try:
                            backoff_ms = int(float(backoff_raw))
                        except Exception:
                            backoff_ms = 0
                    retry_raw = payload.get("retry_events")
                    if isinstance(retry_raw, (int, float)):
                        retry_events = int(retry_raw)
                    elif status == "failed":
                        retry_events = 1
            except Exception:
                provider = "unknown"
            bucket = provider_acc.setdefault(
                provider,
                {"provider": provider, "attempts": 0, "completed": 0, "failed": 0, "retry_events": 0, "backoff_total_ms": 0, "backoff_max_ms": 0},
            )
            bucket["attempts"] += 1
            if status == "completed":
                bucket["completed"] += 1
            if status == "failed":
                bucket["failed"] += 1
            bucket["retry_events"] += retry_events
            bucket["backoff_total_ms"] += max(0, backoff_ms)
            bucket["backoff_max_ms"] = max(int(bucket["backoff_max_ms"]), max(0, backoff_ms))
        out["totals"] = {
            "attempts": total_attempts,
            "completed": total_completed,
            "failed": total_failed,
            "dlq": total_dlq,
            "completion_rate": (float(total_completed) / float(max(total_attempts, 1))) if total_attempts > 0 else None,
        }
        out["by_provider"] = sorted(
            [
                {
                    "provider": k,
                    "attempts": int(v["attempts"]),
                    "completed": int(v["completed"]),
                    "failed": int(v["failed"]),
                    "retry_events": int(v["retry_events"]),
                    "avg_backoff_ms": (float(v["backoff_total_ms"]) / float(max(int(v["attempts"]), 1))) if int(v["attempts"]) > 0 else 0.0,
                    "max_backoff_ms": int(v["backoff_max_ms"]),
                }
                for k, v in provider_acc.items()
            ],
            key=lambda x: x["attempts"],
            reverse=True,
        )
    except Exception:
        pass
    return out


def _record_action_attempt(
    *,
    run_id: str,
    step_index: int,
    action_type: str,
    idempotency_key: str,
    attempt: int,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error: str | None = None,
) -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO playbook_action_executions (
                        id, run_id, step_index, action_type, idempotency_key, attempt, status, result_json, error, created_at
                    ) VALUES (
                        :id, :run_id, :step_index, :action_type, :idempotency_key, :attempt, :status, :result_json, :error, :created_at
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "step_index": step_index,
                    "action_type": action_type,
                    "idempotency_key": idempotency_key,
                    "attempt": attempt,
                    "status": status,
                    "result_json": json.dumps(result or {}, ensure_ascii=False),
                    "error": error,
                    "created_at": _utc_now(),
                },
            )
            db.commit()
        try:
            trace_or_decision = _get_trace_for_run(run_id)
            if trace_or_decision:
                log_trace_event(
                    trace_id=trace_or_decision,
                    event_type="playbook_action",
                    source_type="agent",
                    source_id="Playbook_Engine",
                    target_type="playbook",
                    target_id=run_id,
                    payload={
                        "run_id": run_id,
                        "step_index": step_index,
                        "action_type": action_type,
                        "idempotency_key": idempotency_key,
                        "attempt": attempt,
                        "status": status,
                        "result": result,
                        "error": error,
                    },
                )
        except Exception:
            pass
    except Exception:
        pass


def _action_already_done(idempotency_key: str) -> bool:
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT 1 FROM playbook_action_executions
                    WHERE idempotency_key = :k AND status = 'completed'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"k": idempotency_key},
            ).fetchone()
            return bool(row)
    except Exception:
        return False


def _send_to_dlq(*, run_id: str, step_index: int, action_type: str, idempotency_key: str, payload: Dict[str, Any], last_error: str | None) -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO playbook_action_dlq (
                        id, run_id, step_index, action_type, idempotency_key, payload_json, last_error, created_at
                    ) VALUES (
                        :id, :run_id, :step_index, :action_type, :idempotency_key, :payload_json, :last_error, :created_at
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "step_index": step_index,
                    "action_type": action_type,
                    "idempotency_key": idempotency_key,
                    "payload_json": json.dumps(payload or {}, ensure_ascii=False),
                    "last_error": last_error,
                    "created_at": _utc_now(),
                },
            )
            db.commit()
    except Exception:
        pass


def _execute_action(action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    action_type = str(action.get("type") or "unknown")
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    if action_type in {"send_email", "send_notification_email", "email"}:
        return email_action(action, context)
    if action_type in {"create_return_label", "shipping_label", "shipping"}:
        return shipping_action(action, context)
    if action_type in {"erp_sync", "erp_signal_check", "erp"}:
        return erp_action(action, context)
    # Deterministic typed action stubs; wire real integrations per action type incrementally.
    if action_type in {"create_ticket", "create_incident", "escalate_ticket"}:
        return {"ok": True, "ticket_id": f"TKT-{uuid.uuid4().hex[:10]}", "action_type": action_type}
    if action_type in {"hold_payment", "apply_compensation", "offer_discount"}:
        return {"ok": True, "amount": params.get("max_amount"), "action_type": action_type}
    if action_type in {"notify_ops", "notify_stakeholders", "send_message"}:
        return {"ok": True, "channel": params.get("channel"), "action_type": action_type}
    if action_type in {"step_up_auth", "session_revoke", "inject_recommendations", "track_experiment"}:
        return {"ok": True, "action_type": action_type}
    if action_type in {"ip_block", "block_ip"}:
        res = ip_block_action(action, context)
        res["action_type"] = "ip_block"
        return res
    if action_type in {"rate_limit", "api_rate_limit"}:
        res = rate_limit_action(action, context)
        res["action_type"] = "rate_limit"
        return res
    if action_type in {"suspend_account", "account_suspend"}:
        acct = params.get("account_id") or context.get("account_id")
        return {"ok": True, "account_id": acct, "action_type": "suspend_account"}
    # fallback noop for unknown action type (do not fail the entire flow)
    return {"ok": True, "action_type": action_type, "noop": True}

def _get_trace_for_run(run_id: str) -> Optional[str]:
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT COALESCE(trace_id, decision_id)
                    FROM playbook_runs
                    WHERE id = :rid
                    """
                ),
                {"rid": run_id},
            ).fetchone()
            if not row:
                return None
            val = row[0]
            return str(val) if val else None
    except Exception:
        return None


def execute_typed_actions(
    *,
    run_id: str,
    actions: List[Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_playbook_run_tables()
    ctx = context or {}
    max_retries = max(0, int(os.getenv("PLAYBOOK_ACTION_MAX_RETRIES", "2") or 2))
    out = {"executed": [], "failed": [], "skipped": []}
    for idx, raw_action in enumerate(actions or []):
        if not isinstance(raw_action, dict):
            out["skipped"].append({"step_index": idx, "reason": "non_typed_action"})
            continue
        mode = str(raw_action.get("mode") or "automatic").lower()
        if mode not in ("automatic", "manual_approval"):
            mode = "automatic"
        if mode == "manual_approval":
            out["skipped"].append({"step_index": idx, "reason": "manual_approval_required", "action": raw_action})
            continue
        action_type = str(raw_action.get("type") or "unknown")
        idempotency_key = f"{run_id}:{idx}:{action_type}"
        if _action_already_done(idempotency_key):
            out["skipped"].append({"step_index": idx, "reason": "idempotent_already_completed", "action_type": action_type})
            continue
        last_err = None
        completed = False
        for attempt in range(1, max_retries + 2):
            try:
                result = _execute_action(raw_action, ctx)
                _record_action_attempt(
                    run_id=run_id,
                    step_index=idx,
                    action_type=action_type,
                    idempotency_key=idempotency_key,
                    attempt=attempt,
                    status="completed",
                    result=result,
                )
                out["executed"].append({"step_index": idx, "action_type": action_type, "result": result})
                completed = True
                break
            except Exception as exc:
                last_err = str(exc)
                _record_action_attempt(
                    run_id=run_id,
                    step_index=idx,
                    action_type=action_type,
                    idempotency_key=idempotency_key,
                    attempt=attempt,
                    status="failed",
                    result=None,
                    error=last_err,
                )
        if not completed:
            _send_to_dlq(
                run_id=run_id,
                step_index=idx,
                action_type=action_type,
                idempotency_key=idempotency_key,
                payload=raw_action,
                last_error=last_err,
            )
            out["failed"].append({"step_index": idx, "action_type": action_type, "error": last_err})
    return out


def list_playbook_dlq(*, limit: int = 100) -> Dict[str, Any]:
    ensure_playbook_run_tables()
    limit = max(1, min(int(limit or 100), 500))
    rows_out: List[Dict[str, Any]] = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, run_id, step_index, action_type, idempotency_key, payload_json, last_error, created_at
                    FROM playbook_action_dlq
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()
        for r in rows or []:
            payload = {}
            try:
                payload = json.loads(r[5]) if r[5] else {}
            except Exception:
                payload = {"raw": r[5]}
            rows_out.append(
                {
                    "id": r[0],
                    "run_id": r[1],
                    "step_index": int(r[2] or 0),
                    "action_type": r[3],
                    "idempotency_key": r[4],
                    "payload": payload,
                    "last_error": r[6],
                    "created_at": r[7],
                }
            )
    except Exception:
        pass
    return {"items": rows_out, "count": len(rows_out)}


def reprocess_playbook_dlq(*, limit: int = 50) -> Dict[str, Any]:
    ensure_playbook_run_tables()
    limit = max(1, min(int(limit or 50), 200))
    out = {"picked": 0, "reprocessed": 0, "failed": 0, "details": []}
    rows = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, run_id, step_index, action_type, idempotency_key, payload_json
                    FROM playbook_action_dlq
                    ORDER BY created_at ASC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()
        out["picked"] = len(rows or [])
    except Exception:
        return out

    for r in rows or []:
        dlq_id = str(r[0])
        run_id = str(r[1])
        step_index = int(r[2] or 0)
        action_type = str(r[3] or "unknown")
        idempotency_key = str(r[4] or "")
        try:
            payload = json.loads(r[5]) if r[5] else {}
        except Exception:
            payload = {}
        action = payload if isinstance(payload, dict) else {"type": action_type, "params": {}}
        if not action.get("type"):
            action["type"] = action_type
        try:
            if _action_already_done(idempotency_key):
                with db_session() as db:
                    db.execute(text("DELETE FROM playbook_action_dlq WHERE id = :id"), {"id": dlq_id})
                    db.commit()
                out["reprocessed"] += 1
                out["details"].append({"id": dlq_id, "status": "already_completed"})
                try:
                    trace_or_decision = _get_trace_for_run(run_id)
                    if trace_or_decision:
                        log_trace_event(
                            trace_id=trace_or_decision,
                            event_type="playbook_action_reprocess",
                            source_type="agent",
                            source_id="Playbook_Engine",
                            target_type="playbook",
                            target_id=run_id,
                            payload={
                                "run_id": run_id,
                                "step_index": step_index,
                                "action_type": action_type,
                                "idempotency_key": idempotency_key,
                                "status": "already_completed",
                            },
                        )
                except Exception:
                    pass
                continue
            max_retries = max(0, int(os.getenv("PLAYBOOK_ACTION_MAX_RETRIES", "2") or 2))
            last_err = None
            done = False
            for attempt in range(1, max_retries + 2):
                try:
                    result = _execute_action(action, {"run_id": run_id, "reprocess": True})
                    _record_action_attempt(
                        run_id=run_id,
                        step_index=step_index,
                        action_type=action_type,
                        idempotency_key=idempotency_key,
                        attempt=attempt,
                        status="completed",
                        result=result,
                    )
                    with db_session() as db:
                        db.execute(text("DELETE FROM playbook_action_dlq WHERE id = :id"), {"id": dlq_id})
                        db.commit()
                    out["reprocessed"] += 1
                    out["details"].append({"id": dlq_id, "status": "completed", "result": result})
                    try:
                        trace_or_decision = _get_trace_for_run(run_id)
                        if trace_or_decision:
                            log_trace_event(
                                trace_id=trace_or_decision,
                                event_type="playbook_action_reprocess",
                                source_type="agent",
                                source_id="Playbook_Engine",
                                target_type="playbook",
                                target_id=run_id,
                                payload={
                                    "run_id": run_id,
                                    "step_index": step_index,
                                    "action_type": action_type,
                                    "idempotency_key": idempotency_key,
                                    "attempt": attempt,
                                    "status": "completed",
                                    "result": result,
                                },
                            )
                    except Exception:
                        pass
                    done = True
                    break
                except Exception as exc:
                    last_err = str(exc)
                    _record_action_attempt(
                        run_id=run_id,
                        step_index=step_index,
                        action_type=action_type,
                        idempotency_key=idempotency_key,
                        attempt=attempt,
                        status="failed",
                        result=None,
                        error=last_err,
                    )
            if not done:
                out["failed"] += 1
                out["details"].append({"id": dlq_id, "status": "failed", "error": last_err})
                try:
                    trace_or_decision = _get_trace_for_run(run_id)
                    if trace_or_decision:
                        log_trace_event(
                            trace_id=trace_or_decision,
                            event_type="playbook_action_reprocess",
                            source_type="agent",
                            source_id="Playbook_Engine",
                            target_type="playbook",
                            target_id=run_id,
                            payload={
                                "run_id": run_id,
                                "step_index": step_index,
                                "action_type": action_type,
                                "idempotency_key": idempotency_key,
                                "status": "failed",
                                "error": last_err,
                            },
                        )
                except Exception:
                    pass
        except Exception as exc:
            out["failed"] += 1
            out["details"].append({"id": dlq_id, "status": "failed", "error": str(exc)})
            try:
                trace_or_decision = _get_trace_for_run(run_id)
                if trace_or_decision:
                    log_trace_event(
                        trace_id=trace_or_decision,
                        event_type="playbook_action_reprocess",
                        source_type="agent",
                        source_id="Playbook_Engine",
                        target_type="playbook",
                        target_id=run_id,
                        payload={
                            "run_id": run_id,
                            "step_index": step_index,
                            "action_type": action_type,
                            "idempotency_key": idempotency_key,
                            "status": "failed",
                            "error": str(exc),
                        },
                    )
            except Exception:
                pass
    return out
