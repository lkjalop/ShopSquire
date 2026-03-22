from __future__ import annotations

import json
import re
import hashlib
from urllib.parse import quote, unquote
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session


_EMAIL_PAT = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _ensure_supplier_governance_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS supplier_governance_profiles (
                      tenant_id TEXT NOT NULL,
                      supplier_key TEXT NOT NULL,
                      vendor_name TEXT,
                      approved_domains_json TEXT NOT NULL DEFAULT '[]',
                      observed_domains_json TEXT NOT NULL DEFAULT '[]',
                      approved_contacts_json TEXT NOT NULL DEFAULT '[]',
                      observed_contacts_json TEXT NOT NULL DEFAULT '[]',
                      approved_bank_fingerprints_json TEXT NOT NULL DEFAULT '[]',
                      observed_bank_fingerprints_json TEXT NOT NULL DEFAULT '[]',
                      trusted_template_hashes_json TEXT NOT NULL DEFAULT '[]',
                      observed_template_hashes_json TEXT NOT NULL DEFAULT '[]',
                      pending_updates_json TEXT NOT NULL DEFAULT '[]',
                      history_json TEXT NOT NULL DEFAULT '[]',
                      notes_json TEXT NOT NULL DEFAULT '[]',
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (tenant_id, supplier_key)
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def _norm_list(values: List[Any] | None) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _json_list(value: Any) -> List[str]:
    try:
        if isinstance(value, str):
            parsed = json.loads(value or "[]")
        else:
            parsed = value
        if isinstance(parsed, list):
            return _norm_list(parsed)
    except Exception:
        pass
    return []


def _domain_from_addr(addr: str | None) -> str:
    raw = str(addr or "").strip().lower()
    if "@" not in raw:
        return raw
    return raw.rsplit("@", 1)[-1].strip()


def _hash16(value: str | None) -> str | None:
    try:
        if not value:
            return None
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _governance_version_hash(profile: Dict[str, Any]) -> str:
    seed = json.dumps(
        {
            "approved_domains": _norm_list(list(profile.get("approved_domains") or [])),
            "approved_contacts": _norm_list(list(profile.get("approved_contacts") or [])),
            "approved_bank_fingerprints": _norm_list(list(profile.get("approved_bank_fingerprints") or [])),
            "trusted_template_hashes": _norm_list(list(profile.get("trusted_template_hashes") or [])),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _parse_history_entry(entry: str) -> Dict[str, Any]:
    text = str(entry or "").strip()
    parts = text.split(":")
    action = parts[0] if parts else "recorded"
    update_key = parts[1] if len(parts) > 1 else ""
    actor_role = None
    actor_id = None
    reviewer_note = None
    version_hash = None
    for part in parts[2:]:
        if part.startswith("by="):
            _, _, raw = part.partition("=")
            if ":" in raw:
                actor_role, actor_id = raw.split(":", 1)
            else:
                actor_role = raw
        elif part.startswith("note="):
            _, _, raw = part.partition("=")
            reviewer_note = unquote(raw or "").strip() or None
        elif part.startswith("version="):
            _, _, raw = part.partition("=")
            version_hash = str(raw or "").strip() or None
    update_type, _, update_value = update_key.partition(":")
    action_label = {
        "approve": "Approved",
        "reject": "Rejected",
        "rollback": "Rolled back",
        "pending": "Pending review for",
    }.get(action, action.title())
    state = {
        "approve": "approved",
        "reject": "rejected",
        "rollback": "rolled_back",
        "pending": "pending",
    }.get(action, "recorded")
    return {
        "action": action,
        "update_key": update_key,
        "update_type": update_type or None,
        "update_value": update_value or None,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "reviewer_note": reviewer_note,
        "version_hash": version_hash,
        "summary": f"{action_label} {update_type.replace('_', ' ') if update_type else 'governance item'}{f' {update_value}' if update_value else ''}".strip(),
        "state": state,
    }


def build_supplier_governance_timeline(*, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    prof = profile if isinstance(profile, dict) else {}
    timeline: List[Dict[str, Any]] = []
    updated_at = str(prof.get("updated_at") or "").strip() or None
    pending = [str(x or "").strip() for x in (prof.get("pending_updates") or []) if str(x or "").strip()]
    for idx, entry in enumerate((prof.get("history") or [])[-32:]):
        row = _parse_history_entry(str(entry or ""))
        row["index"] = idx + 1
        row["created_at"] = updated_at
        timeline.append(row)
    for item in pending:
        update_type, _, update_value = item.partition(":")
        timeline.append(
            {
                "index": len(timeline) + 1,
                "created_at": updated_at,
                "action": "pending",
                "update_key": item,
                "update_type": update_type or None,
                "update_value": update_value or None,
                "actor_role": None,
                "actor_id": None,
                "reviewer_note": None,
                "version_hash": prof.get("version_hash"),
                "summary": f"Pending review for {update_type.replace('_', ' ') if update_type else 'governance item'}{f' {update_value}' if update_value else ''}".strip(),
                "state": "pending",
            }
        )
    latest_by_update: Dict[str, int] = {}
    for idx, row in enumerate(timeline):
        update_key = str(row.get("update_key") or "").strip()
        if update_key:
            latest_by_update[update_key] = idx
    for idx, row in enumerate(timeline):
        update_key = str(row.get("update_key") or "").strip()
        if not update_key:
            continue
        latest_idx = latest_by_update.get(update_key, idx)
        if latest_idx != idx and row.get("state") not in {"pending", "rolled_back"}:
            row["state"] = "superseded"
            row["summary"] = f"{row.get('summary') or 'Governance action'} (superseded)"
    return timeline[-40:]


def _attachment_contacts(attachment_forensics: List[Dict[str, Any]]) -> List[str]:
    found: List[str] = []
    for item in attachment_forensics:
        if not isinstance(item, dict):
            continue
        excerpts = item.get("evidence_excerpt_lines") if isinstance(item.get("evidence_excerpt_lines"), list) else []
        summary = str(item.get("text_summary") or "")
        blob = "\n".join([summary] + [str(x or "") for x in excerpts[:8]])
        found.extend(_EMAIL_PAT.findall(blob))
    return _norm_list(found)


def _attachment_bank_fingerprints(attachment_forensics: List[Dict[str, Any]]) -> List[str]:
    values: List[str] = []
    for item in attachment_forensics:
        if not isinstance(item, dict):
            continue
        for key in ("extracted_bank_fingerprint", "bank_fingerprint", "observed_bank_fingerprint"):
            clean = str(item.get(key) or "").strip()
            if clean:
                values.append(clean)
    return _norm_list(values)


def _attachment_template_hashes(email: Dict[str, Any], attachment_forensics: List[Dict[str, Any]]) -> List[str]:
    values: List[str] = []
    for item in (email.get("attachments") or []):
        if not isinstance(item, dict):
            continue
        for key in ("template_hash", "layout_hash", "logo_hash"):
            clean = str(item.get(key) or "").strip()
            if clean:
                values.append(clean)
    for item in attachment_forensics:
        if not isinstance(item, dict):
            continue
        for key in ("template_hash", "layout_hash", "logo_hash"):
            clean = str(item.get(key) or "").strip()
            if clean:
                values.append(clean)
    return _norm_list(values)


def _load_existing_profile(*, tenant_id: str, supplier_key: str) -> Dict[str, Any]:
    _ensure_supplier_governance_table()
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT vendor_name,
                           approved_domains_json,
                           observed_domains_json,
                           approved_contacts_json,
                           observed_contacts_json,
                           approved_bank_fingerprints_json,
                           observed_bank_fingerprints_json,
                           trusted_template_hashes_json,
                           observed_template_hashes_json,
                           pending_updates_json,
                           history_json,
                           notes_json
                    FROM supplier_governance_profiles
                    WHERE tenant_id=:tenant AND supplier_key=:supplier
                    """
                ),
                {"tenant": tenant_id, "supplier": supplier_key},
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return {}
    return {
        "vendor_name": str(row[0] or "").strip() or None,
        "approved_domains": _json_list(row[1]),
        "observed_domains": _json_list(row[2]),
        "approved_contacts": _json_list(row[3]),
        "observed_contacts": _json_list(row[4]),
        "approved_bank_fingerprints": _json_list(row[5]),
        "observed_bank_fingerprints": _json_list(row[6]),
        "trusted_template_hashes": _json_list(row[7]),
        "observed_template_hashes": _json_list(row[8]),
        "pending_updates": _json_list(row[9]),
        "history": _json_list(row[10]),
        "notes": _json_list(row[11]),
    }


def update_supplier_governance_snapshot(
    *,
    tenant_id: str | None,
    email: Dict[str, Any],
    evidence_snapshot: Dict[str, Any],
    structured_findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    tenant = str(tenant_id or "default")
    attachment_forensics = evidence_snapshot.get("attachment_forensics") if isinstance(evidence_snapshot.get("attachment_forensics"), list) else []
    artifact_intel = evidence_snapshot.get("artifact_intel") if isinstance(evidence_snapshot.get("artifact_intel"), dict) else {}
    baseline_checks = artifact_intel.get("baseline_checks") if isinstance(artifact_intel.get("baseline_checks"), dict) else {}
    parsed_fields = artifact_intel.get("parsed_fields") if isinstance(artifact_intel.get("parsed_fields"), dict) else {}
    vendor_domain = (
        str(email.get("vendor_domain") or "").strip().lower()
        or str(baseline_checks.get("vendor_domain") or "").strip().lower()
        or _domain_from_addr(str(email.get("reply_to") or ""))
        or _domain_from_addr(str(email.get("from_addr") or ""))
        or "unknown_supplier"
    )
    vendor_name = str(parsed_fields.get("vendor_name") or baseline_checks.get("vendor_name") or vendor_domain).strip()
    existing = _load_existing_profile(tenant_id=tenant, supplier_key=vendor_domain)

    approved_domains = _norm_list(list(existing.get("approved_domains") or []) + ([vendor_domain] if vendor_domain and vendor_domain != "unknown_supplier" else []))
    observed_domains = _norm_list(
        list(existing.get("observed_domains") or [])
        + [vendor_domain]
        + [_domain_from_addr(str(email.get("from_addr") or "")), _domain_from_addr(str(email.get("reply_to") or ""))]
    )
    approved_contacts = _norm_list(list(existing.get("approved_contacts") or []))
    observed_contacts = _norm_list(list(existing.get("observed_contacts") or []) + _attachment_contacts(attachment_forensics) + [str(email.get("from_addr") or "").strip(), str(email.get("reply_to") or "").strip()])
    approved_bank_fps = _norm_list(list(existing.get("approved_bank_fingerprints") or []))
    observed_bank_fps = _norm_list(list(existing.get("observed_bank_fingerprints") or []) + _attachment_bank_fingerprints(attachment_forensics))
    trusted_template_hashes = _norm_list(list(existing.get("trusted_template_hashes") or []))
    observed_template_hashes = _norm_list(list(existing.get("observed_template_hashes") or []) + _attachment_template_hashes(email, attachment_forensics))

    high_risk = any(str((f or {}).get("confidence_band") or "") == "high" for f in (structured_findings or []) if isinstance(f, dict))
    pending_updates = list(existing.get("pending_updates") or [])
    if high_risk:
        for fp in observed_bank_fps:
            if fp not in approved_bank_fps:
                pending_updates.append(f"review_bank_fingerprint:{fp}")
        for dom in observed_domains:
            if dom and dom not in approved_domains:
                pending_updates.append(f"review_domain:{dom}")
        for th in observed_template_hashes:
            if th and th not in trusted_template_hashes:
                pending_updates.append(f"review_template_hash:{th}")
    pending_updates = _norm_list(pending_updates)

    notes = _norm_list(list(existing.get("notes") or []))
    notes.append(f"risk_findings:{sum(1 for f in (structured_findings or []) if isinstance(f, dict))}")
    notes = _norm_list(notes)

    snapshot = {
        "tenant_id": tenant,
        "supplier_key": vendor_domain,
        "vendor_name": vendor_name or vendor_domain,
        "approved_domains": approved_domains[:24],
        "observed_domains": observed_domains[:24],
        "approved_contacts": approved_contacts[:24],
        "observed_contacts": observed_contacts[:24],
        "approved_bank_fingerprints": approved_bank_fps[:24],
        "observed_bank_fingerprints": observed_bank_fps[:24],
        "trusted_template_hashes": trusted_template_hashes[:32],
        "observed_template_hashes": observed_template_hashes[:32],
        "pending_updates": pending_updates[:24],
        "history": list(existing.get("history") or [])[:48],
        "governance_state": "review_required" if pending_updates else "stable",
    }

    try:
        _ensure_supplier_governance_table()
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO supplier_governance_profiles (
                      tenant_id, supplier_key, vendor_name,
                      approved_domains_json, observed_domains_json,
                      approved_contacts_json, observed_contacts_json,
                      approved_bank_fingerprints_json, observed_bank_fingerprints_json,
                      trusted_template_hashes_json, observed_template_hashes_json,
                      pending_updates_json, history_json, notes_json, updated_at
                    ) VALUES (
                      :tenant, :supplier, :vendor_name,
                      :approved_domains, :observed_domains,
                      :approved_contacts, :observed_contacts,
                      :approved_bank_fps, :observed_bank_fps,
                      :trusted_hashes, :observed_hashes,
                      :pending_updates, :history_json, :notes, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(tenant_id, supplier_key) DO UPDATE SET
                      vendor_name=:vendor_name,
                      approved_domains_json=:approved_domains,
                      observed_domains_json=:observed_domains,
                      approved_contacts_json=:approved_contacts,
                      observed_contacts_json=:observed_contacts,
                      approved_bank_fingerprints_json=:approved_bank_fps,
                      observed_bank_fingerprints_json=:observed_bank_fps,
                      trusted_template_hashes_json=:trusted_hashes,
                      observed_template_hashes_json=:observed_hashes,
                      pending_updates_json=:pending_updates,
                      history_json=:history_json,
                      notes_json=:notes,
                      updated_at=CURRENT_TIMESTAMP
                    """
                ),
                {
                    "tenant": tenant,
                    "supplier": vendor_domain,
                    "vendor_name": vendor_name or vendor_domain,
                    "approved_domains": json.dumps(snapshot["approved_domains"], ensure_ascii=False),
                    "observed_domains": json.dumps(snapshot["observed_domains"], ensure_ascii=False),
                    "approved_contacts": json.dumps(snapshot["approved_contacts"], ensure_ascii=False),
                    "observed_contacts": json.dumps(snapshot["observed_contacts"], ensure_ascii=False),
                    "approved_bank_fps": json.dumps(snapshot["approved_bank_fingerprints"], ensure_ascii=False),
                    "observed_bank_fps": json.dumps(snapshot["observed_bank_fingerprints"], ensure_ascii=False),
                    "trusted_hashes": json.dumps(snapshot["trusted_template_hashes"], ensure_ascii=False),
                    "observed_hashes": json.dumps(snapshot["observed_template_hashes"], ensure_ascii=False),
                    "pending_updates": json.dumps(snapshot["pending_updates"], ensure_ascii=False),
                    "history_json": json.dumps(snapshot["history"], ensure_ascii=False),
                    "notes": json.dumps(notes[:32], ensure_ascii=False),
                },
            )
            db.commit()
    except Exception:
        pass
    return snapshot


def get_supplier_governance_profile(*, tenant_id: str | None, supplier_key: str) -> Dict[str, Any]:
    tenant = str(tenant_id or "default")
    supplier = str(supplier_key or "").strip().lower()
    if not supplier:
        return {}
    profile = _load_existing_profile(tenant_id=tenant, supplier_key=supplier)
    if not profile:
        return {}
    profile["tenant_id"] = tenant
    profile["supplier_key"] = supplier
    profile["governance_state"] = "review_required" if profile.get("pending_updates") else "stable"
    profile["version_hash"] = _governance_version_hash(profile)
    profile["version_timeline"] = build_supplier_governance_timeline(profile=profile)
    profile["version_count"] = len(profile.get("version_timeline") or [])
    return profile


def list_supplier_governance_profiles(*, tenant_id: str | None = None, limit: int = 50) -> Dict[str, Any]:
    _ensure_supplier_governance_table()
    tenant = str(tenant_id or "").strip() or None
    rows = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT tenant_id, supplier_key, vendor_name,
                           approved_domains_json, observed_domains_json,
                           approved_bank_fingerprints_json, observed_bank_fingerprints_json,
                           pending_updates_json, history_json, updated_at
                    FROM supplier_governance_profiles
                    WHERE (:tenant_id IS NULL OR tenant_id=:tenant_id)
                    ORDER BY updated_at DESC
                    LIMIT :limit
                    """
                ),
                {"tenant_id": tenant, "limit": max(1, min(int(limit or 50), 200))},
            ).fetchall()
    except Exception:
        rows = []
    items = []
    for row in rows or []:
        pending = _json_list(row[7])
        history = _json_list(row[8])
        items.append(
            {
                "tenant_id": row[0],
                "supplier_key": row[1],
                "vendor_name": row[2],
                "approved_domains": _json_list(row[3]),
                "observed_domains": _json_list(row[4]),
                "approved_bank_fingerprints": _json_list(row[5]),
                "observed_bank_fingerprints": _json_list(row[6]),
                "pending_updates": pending,
                "history": history[-12:],
                "governance_state": "review_required" if pending else "stable",
                "version_hash": _governance_version_hash(
                    {
                        "approved_domains": _json_list(row[3]),
                        "approved_bank_fingerprints": _json_list(row[5]),
                    }
                ),
                "version_count": len(history[-12:]) + len(pending),
                "updated_at": row[9],
            }
        )
    return {"items": items, "count": len(items)}


def review_supplier_governance_update(
    *,
    tenant_id: str | None,
    supplier_key: str,
    update_key: str,
    decision: str,
    actor_id: str,
    actor_role: str,
    note: str | None = None,
) -> Dict[str, Any]:
    tenant = str(tenant_id or "default")
    supplier = str(supplier_key or "").strip().lower()
    update = str(update_key or "").strip()
    decision_n = str(decision or "").strip().lower()
    if not supplier or not update:
        return {"ok": False, "error": "supplier_key_and_update_key_required"}
    if decision_n not in {"approve", "reject", "rollback"}:
        return {"ok": False, "error": "decision_must_be_approve_reject_or_rollback"}
    profile = get_supplier_governance_profile(tenant_id=tenant, supplier_key=supplier)
    if not profile:
        return {"ok": False, "error": "supplier_profile_not_found"}

    approved_domains = _norm_list(list(profile.get("approved_domains") or []))
    approved_bank_fps = _norm_list(list(profile.get("approved_bank_fingerprints") or []))
    trusted_hashes = _norm_list(list(profile.get("trusted_template_hashes") or []))
    pending = _norm_list(list(profile.get("pending_updates") or []))
    history = _norm_list(list(profile.get("history") or []))
    notes = _norm_list(list(profile.get("notes") or []))

    pending = [item for item in pending if item != update]
    prefix, _, value = update.partition(":")
    value = value.strip()
    if decision_n == "approve":
        if prefix == "review_domain" and value:
            approved_domains = _norm_list(approved_domains + [value])
        elif prefix == "review_bank_fingerprint" and value:
            approved_bank_fps = _norm_list(approved_bank_fps + [value])
        elif prefix == "review_template_hash" and value:
            trusted_hashes = _norm_list(trusted_hashes + [value])
    elif decision_n == "rollback":
        if prefix == "review_domain" and value:
            approved_domains = [item for item in approved_domains if item != value]
        elif prefix == "review_bank_fingerprint" and value:
            approved_bank_fps = [item for item in approved_bank_fps if item != value]
        elif prefix == "review_template_hash" and value:
            trusted_hashes = [item for item in trusted_hashes if item != value]
    prospective_profile = {
        "approved_domains": approved_domains,
        "approved_bank_fingerprints": approved_bank_fps,
        "trusted_template_hashes": trusted_hashes,
    }
    history_entry = (
        f"{decision_n}:{update}:by={str(actor_role or 'owner').strip()}:{str(actor_id or 'admin').strip()}"
        f":version={_governance_version_hash(prospective_profile)}"
    )
    if note:
        clean_note = str(note).strip()[:180]
        history_entry += f":note={quote(clean_note, safe='')}"
        notes.append(f"review_note:{clean_note}")
    history.append(history_entry)

    try:
        _ensure_supplier_governance_table()
        with db_session() as db:
            db.execute(
                text(
                    """
                    UPDATE supplier_governance_profiles
                    SET approved_domains_json=:approved_domains,
                        approved_bank_fingerprints_json=:approved_bank_fps,
                        trusted_template_hashes_json=:trusted_hashes,
                        pending_updates_json=:pending_updates,
                        history_json=:history_json,
                        notes_json=:notes_json,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE tenant_id=:tenant AND supplier_key=:supplier
                    """
                ),
                {
                    "tenant": tenant,
                    "supplier": supplier,
                    "approved_domains": json.dumps(approved_domains, ensure_ascii=False),
                    "approved_bank_fps": json.dumps(approved_bank_fps, ensure_ascii=False),
                    "trusted_hashes": json.dumps(trusted_hashes, ensure_ascii=False),
                    "pending_updates": json.dumps(pending, ensure_ascii=False),
                    "history_json": json.dumps(history[-64:], ensure_ascii=False),
                    "notes_json": json.dumps(notes[-64:], ensure_ascii=False),
                },
            )
            db.commit()
    except Exception as exc:
        return {"ok": False, "error": f"update_failed:{exc}"}

    updated = get_supplier_governance_profile(tenant_id=tenant, supplier_key=supplier)
    return {"ok": True, "decision": decision_n, "supplier_key": supplier, "profile": updated}


def build_vendor_trust_graph_snapshot(
    *,
    governance_snapshot: Dict[str, Any],
    evidence_snapshot: Dict[str, Any],
    structured_findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    gov = governance_snapshot if isinstance(governance_snapshot, dict) else {}
    infra = evidence_snapshot.get("sender_infrastructure") if isinstance(evidence_snapshot.get("sender_infrastructure"), dict) else {}
    related = infra.get("related_incidents") if isinstance(infra.get("related_incidents"), list) else []
    auth = evidence_snapshot.get("auth_verdicts") if isinstance(evidence_snapshot.get("auth_verdicts"), dict) else {}

    supplier = str(gov.get("supplier_key") or "unknown_supplier")
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    def _add_node(node_id: str, label: str, node_type: str, risk: str = "info") -> None:
        if node_id and not any(n.get("id") == node_id for n in nodes):
            nodes.append({"id": node_id, "label": label, "type": node_type, "risk": risk})

    def _add_edge(source: str, target: str, relation: str, risk: str = "info") -> None:
        if source and target:
            edges.append({"source": source, "target": target, "relation": relation, "risk": risk})

    _add_node(f"supplier:{supplier}", supplier, "supplier", "info")
    for dom in (gov.get("approved_domains") or [])[:8]:
        node_id = f"domain:{dom}"
        _add_node(node_id, dom, "approved_domain", "low")
        _add_edge(f"supplier:{supplier}", node_id, "approved_domain", "low")
    for dom in (gov.get("observed_domains") or [])[:8]:
        risk = "medium" if dom not in (gov.get("approved_domains") or []) else "low"
        node_id = f"domain:{dom}"
        _add_node(node_id, dom, "observed_domain", risk)
        _add_edge(f"supplier:{supplier}", node_id, "observed_domain", risk)
    for fp in (gov.get("observed_bank_fingerprints") or [])[:6]:
        risk = "high" if fp not in (gov.get("approved_bank_fingerprints") or []) else "low"
        node_id = f"bank:{fp}"
        _add_node(node_id, fp, "bank_fingerprint", risk)
        _add_edge(f"supplier:{supplier}", node_id, "observed_bank_fingerprint", risk)
    for th in (gov.get("observed_template_hashes") or [])[:6]:
        risk = "medium" if th not in (gov.get("trusted_template_hashes") or []) else "low"
        node_id = f"template:{th}"
        _add_node(node_id, th[:12], "template_hash", risk)
        _add_edge(f"supplier:{supplier}", node_id, "template_hash", risk)
    for item in related[:6]:
        incident_id = str((item or {}).get("incident_id") or (item or {}).get("id") or "").strip()
        if not incident_id:
            continue
        _add_node(f"incident:{incident_id}", incident_id, "related_incident", str((item or {}).get("severity") or "warning"))
        _add_edge(f"supplier:{supplier}", f"incident:{incident_id}", "related_incident", str((item or {}).get("severity") or "warning"))

    risk_notes = _norm_list(list(gov.get("pending_updates") or []))
    if bool(auth.get("dmarc_fail")):
        risk_notes.append("auth_alignment_failed")
    risk_notes.extend(
        str((f or {}).get("finding_type") or "")
        for f in (structured_findings or [])[:10]
        if isinstance(f, dict) and str((f or {}).get("confidence_band") or "") == "high"
    )

    return {
        "supplier_key": supplier,
        "vendor_name": gov.get("vendor_name") or supplier,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes[:20],
        "edges": edges[:32],
        "risk_notes": risk_notes[:12],
        "graph_state": "elevated_risk" if risk_notes else "stable",
    }


def build_incident_graph_snapshot(
    *,
    tenant_id: str | None,
    supplier_key: str | None,
    evidence_snapshot: Dict[str, Any],
    limit: int = 12,
) -> Dict[str, Any]:
    tenant = str(tenant_id or "default")
    supplier = str(supplier_key or "").strip().lower()
    supplier_hash = _hash16(supplier)
    rows = []
    if supplier_hash:
        try:
            with db_session() as db:
                rows = db.execute(
                    text(
                        """
                        SELECT id, created_at, severity, risk_band, reasons_json, evidence_json
                        FROM email_security_incidents
                        WHERE tenant_id=:tenant_id AND supplier_key_hash=:supplier_key_hash
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tenant_id": tenant, "supplier_key_hash": supplier_hash, "limit": max(1, min(int(limit or 12), 50))},
                ).fetchall()
        except Exception:
            rows = []

    timeline: List[Dict[str, Any]] = []
    domains: set[str] = set()
    banks: set[str] = set()
    templates: set[str] = set()
    related_ids: List[str] = []
    for row in rows or []:
        reasons = _json_list(row[4])
        ev = {}
        try:
            ev = json.loads(row[5] or "{}")
        except Exception:
            ev = {}
        gov = ev.get("supplier_governance") if isinstance(ev.get("supplier_governance"), dict) else {}
        for dom in (gov.get("observed_domains") or [])[:8]:
            if str(dom or "").strip():
                domains.add(str(dom))
        for fp in (gov.get("observed_bank_fingerprints") or [])[:8]:
            if str(fp or "").strip():
                banks.add(str(fp))
        for th in (gov.get("observed_template_hashes") or [])[:8]:
            if str(th or "").strip():
                templates.add(str(th))
        timeline.append(
            {
                "incident_id": row[0],
                "created_at": row[1],
                "severity": row[2],
                "risk_band": row[3],
                "reasons": reasons[:6],
            }
        )
        related_ids.append(str(row[0]))

    current_gov = evidence_snapshot.get("supplier_governance") if isinstance(evidence_snapshot.get("supplier_governance"), dict) else {}
    for dom in (current_gov.get("observed_domains") or [])[:8]:
        if str(dom or "").strip():
            domains.add(str(dom))
    for fp in (current_gov.get("observed_bank_fingerprints") or [])[:8]:
        if str(fp or "").strip():
            banks.add(str(fp))
    for th in (current_gov.get("observed_template_hashes") or [])[:8]:
        if str(th or "").strip():
            templates.add(str(th))

    return {
        "supplier_key": supplier,
        "supplier_key_hash": supplier_hash,
        "incident_count": len(timeline),
        "timeline": timeline[:12],
        "relationships": {
            "domains": sorted(domains)[:24],
            "bank_fingerprints": sorted(banks)[:24],
            "template_hashes": sorted(templates)[:24],
        },
        "related_incident_ids": related_ids[:12],
    }
