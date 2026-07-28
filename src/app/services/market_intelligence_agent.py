"""Tenant- and subject-scoped market intelligence for the recommendation path."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.app.schemas.market_evidence import MarketEvidence

_SEVERITY_RANK = {"critical": 1.0, "warn": 0.7, "info": 0.4}
_USEFUL_INSIGHT_KINDS = ("product", "finding", "brand", "segment")


def _catalog_subject_scope(db, *, tenant_id: str, result_skus: List[str]) -> tuple[List[str], List[str]]:
    """Resolve exact result SKUs to approved taxonomy subjects for this tenant."""
    if db is None or not result_skus:
        return [], []
    try:
        from sqlalchemy import bindparam, text
        stmt = text(
            "SELECT DISTINCT node_handle FROM product_classification "
            "WHERE tenant_id=:tenant AND status='approved' AND sku IN :skus"
        ).bindparams(bindparam("skus", expanding=True))
        rows = db.execute(stmt, {"tenant": tenant_id, "skus": list(result_skus)}).fetchall()
        nodes = sorted({str(row[0]) for row in rows if row and row[0]})
        from src.app.services.taxonomy_registry import ancestors
        parent_nodes = sorted({a.handle for node in nodes for a in ancestors(node)})
        return nodes, parent_nodes
    except Exception:
        return [], []


def _normalized_direction(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"up", "increase", "increasing", "spike", "growth", "surge"}:
        return "up"
    if token in {"down", "decrease", "decreasing", "drop", "slowdown", "decline"}:
        return "down"
    if token in {"stable", "flat", "steady"}:
        return "stable"
    if token in {"mixed", "conflicting"}:
        return "mixed"
    return "unknown"


def _finding_dict(f: Any, *, tenant_id: str) -> Dict[str, Any]:
    evidence = getattr(f, "evidence", None) or {}
    entity_ref = str(getattr(f, "entity_ref", None) or "")
    provenance = [str(item) for item in (evidence.get("provenance_chain") or []) if str(item)]
    complete = bool(
        evidence.get("source_system")
        and evidence.get("source_record_id")
        and evidence.get("lineage_root")
        and provenance
        and evidence.get("observed_at")
    )
    requested_status = str(evidence.get("status") or "").strip().lower()
    status = requested_status if requested_status in {
        "observed", "estimated", "simulated", "insufficient_data", "quarantined"
    } else ("observed" if complete else "insufficient_data")
    typed = MarketEvidence(
        finding_type=str(getattr(f, "finding_type", None) or "unknown"),
        tenant_id=tenant_id,
        subject_type=str(evidence.get("subject_type") or ("sku" if entity_ref else "global")),
        subject_id=str(evidence.get("subject_id") or entity_ref or "global"),
        taxonomy_node=evidence.get("taxonomy_node"),
        direction=_normalized_direction(evidence.get("direction")),
        status=status,
        authority=(
            "authoritative"
            if complete and evidence.get("authority") == "authoritative"
            else "advisory"
        ),
        confidence=float(getattr(f, "confidence", 0.0) or 0.0),
        source_system=evidence.get("source_system"),
        source_record_id=evidence.get("source_record_id"),
        trust_tier=evidence.get("trust_tier"),
        licence_id=evidence.get("licence_id"),
        licence_url=evidence.get("licence_url"),
        licence_terms_hash=evidence.get("licence_terms_hash"),
        permitted_use=evidence.get("permitted_use"),
        lineage_root=evidence.get("lineage_root"),
        provenance_chain=provenance,
        observed_at=evidence.get("observed_at"),
        summary=str(getattr(f, "summary", None) or ""),
        metadata={
            "severity": getattr(f, "severity", None),
            "window": getattr(f, "window", None),
            "entity_ref": getattr(f, "entity_ref", None),
        },
    )
    result = typed.model_dump(mode="json")
    result["entity_ref"] = getattr(f, "entity_ref", None)
    result["severity"] = getattr(f, "severity", None)
    result["scope"] = evidence.get("scope")
    result["provenance_complete"] = typed.provenance_complete
    result["licensed_provenance_complete"] = typed.licensed_provenance_complete
    if result.get("authority") == "authoritative" and not typed.licensed_provenance_complete:
        result["authority"] = "advisory"
    return result


def _subject_match(f: Any, *, result_skus: List[str], taxonomy_nodes: Optional[List[str]] = None,
                   ancestor_nodes: Optional[List[str]] = None) -> Optional[tuple[int, str]]:
    skuset = {str(s).strip().lower() for s in (result_skus or []) if s}
    taxset = {str(s).strip().lower() for s in (taxonomy_nodes or []) if s}
    ancestors = {str(s).strip().lower() for s in (ancestor_nodes or []) if s}
    ent = str(getattr(f, "entity_ref", None) or "").strip().lower()
    evidence = getattr(f, "evidence", None) or {}
    subject_type = str(evidence.get("subject_type") or "").strip().lower()
    subject_id = str(evidence.get("subject_id") or ent).strip().lower()
    taxonomy_node = str(evidence.get("taxonomy_node") or "").strip().lower()
    declared_scope = str(evidence.get("scope") or "").strip().lower()
    if ent in skuset or (subject_type == "sku" and subject_id in skuset):
        return 0, "this_item"
    if subject_type in {"product", "variant"} and subject_id in skuset:
        return 1, "this_product"
    if taxonomy_node and taxonomy_node in taxset:
        return 2, "taxonomy"
    if taxonomy_node and taxonomy_node in ancestors:
        return 3, "ancestor"
    if (not ent and not subject_id) or declared_scope == "global" or subject_type == "global":
        return 4, "global"
    return None


def _scope_findings(findings: List[Any], *, result_skus: List[str],
                    taxonomy_nodes: Optional[List[str]] = None,
                    ancestor_nodes: Optional[List[str]] = None) -> List[Any]:
    """Scope by explicit subject: SKU > product/variant > taxonomy > ancestor > global.

    Free-text token overlap is forbidden. A shared brand word is not evidence that a finding
    about one product family applies to another.
    """
    scored = []
    for f in findings:
        match = _subject_match(f, result_skus=result_skus, taxonomy_nodes=taxonomy_nodes,
                               ancestor_nodes=ancestor_nodes)
        if match is None:
            continue
        rank, _scope = match
        severity = _SEVERITY_RANK.get(str(getattr(f, "severity", None) or "info"), 0.4)
        confidence = float(getattr(f, "confidence", 0.0) or 0.0)
        scored.append((rank, -(severity * confidence), f))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [f for _, _, f in scored]


def _structured_evidence(findings: List[Dict[str, Any]], insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    salient = [{"label": i.get("label"), "kind": i.get("kind"), "score": i.get("score")}
               for i in (insights or []) if isinstance(i, dict) and i.get("kind") in _USEFUL_INSIGHT_KINDS][:6]
    return {
        "findings": [{"type": f.get("finding_type"), "severity": f.get("severity"),
                      "summary": f.get("summary"), "entity": f.get("entity_ref"),
                      "subject_type": f.get("subject_type"), "subject_id": f.get("subject_id"),
                      "taxonomy_node": f.get("taxonomy_node"), "source_system": f.get("source_system")}
                     for f in (findings or [])],
        "salient_entities": salient,
    }


def format_evidence_for_narration(findings: List[Dict[str, Any]], *, max_items: int = 4) -> str:
    lines = []
    for finding in (findings or [])[:max_items]:
        summary = finding.get("summary") or f"{finding.get('finding_type')} ({finding.get('severity')})"
        if summary:
            lines.append(f"- {summary}")
    if not lines:
        return ""
    return ("Verified internal market evidence for this query (cite ONLY if it answers the user; never "
            "invent specifics beyond these lines):\n" + "\n".join(lines))


def gather_market_context(db, *, query: Optional[str], uid_hash: Optional[str] = None,
                          result_skus: Optional[List[str]] = None,
                          taxonomy_nodes: Optional[List[str]] = None,
                          ancestor_nodes: Optional[List[str]] = None,
                          tenant_id: Optional[str] = None, top_k: int = 8,
                          max_findings: int = 5, force: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "hippograph_insights": [], "needs_market_evidence": False, "evidence_kinds": [],
        "market_findings": [], "market_evidence": {}, "narration_note": "",
    }
    try:
        if not tenant_id:
            from src.app.platform.tenant_context import current_tenant_id
            tenant_id = current_tenant_id()
        tenant_id = str(tenant_id or "default").strip() or "default"
        seed_skus = list(result_skus or [])[:5]
        derived_nodes, derived_ancestors = _catalog_subject_scope(
            db, tenant_id=tenant_id, result_skus=seed_skus)
        taxonomy_nodes = sorted(set(taxonomy_nodes or []) | set(derived_nodes))
        ancestor_nodes = sorted(set(ancestor_nodes or []) | set(derived_ancestors))
        from src.app.services.hippograph_feedback import build_hippograph_insights
        out["hippograph_insights"] = build_hippograph_insights(
            db, tenant_id=tenant_id, uid_hash=uid_hash, seed_skus=seed_skus, top_k=top_k)
        from src.app.services.query_decomposer import decompose
        plan = decompose(query)
        if force or getattr(plan, "needs_market_evidence", False):
            out["needs_market_evidence"] = True
            out["evidence_kinds"] = list(getattr(plan, "market_evidence_kinds", []) or [])
            from src.app.services.market_analysis import load_recent_findings
            raw = load_recent_findings(db, limit=max(int(max_findings) * 4, 12), tenant_id=tenant_id)
            scoped = _scope_findings(raw, result_skus=seed_skus, taxonomy_nodes=taxonomy_nodes,
                                     ancestor_nodes=ancestor_nodes)[:int(max_findings)]
            out["market_findings"] = []
            for finding in scoped:
                item = _finding_dict(finding, tenant_id=tenant_id)
                match = _subject_match(finding, result_skus=seed_skus, taxonomy_nodes=taxonomy_nodes,
                                       ancestor_nodes=ancestor_nodes)
                item["scope"] = match[1] if match else None
                out["market_findings"].append(item)
        out["market_evidence"] = _structured_evidence(out["market_findings"], out["hippograph_insights"])
        out["narration_note"] = format_evidence_for_narration(out["market_findings"])
        return out
    except Exception:
        return out
