from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from src.app.rag.retrieve import Retriever
from src.app.services.decision_log import log_trace_event


class NextQuestion(BaseModel):
    id: str
    text: str
    goal: str
    evidence_needed: List[str] = []
    stop_condition: Optional[str] = None
    source: str = "template"


class NQEInput(BaseModel):
    intent: str
    product_category: str
    symptom: Optional[str] = None
    timeline_days: Optional[int] = None
    risk_score: float = 0.0
    missing_fields: List[str] = []
    tenant_id: Optional[str] = None
    template_variant: Optional[str] = None
    template_version: Optional[str] = None
    trace_id: Optional[str] = None
    query: Optional[str] = None


class NextQuestionEngine:
    def __init__(self, rag: Retriever, templates) -> None:
        self.rag = rag
        self.templates = templates

    def propose(self, inp: NQEInput) -> List[NextQuestion]:
        questions: List[NextQuestion] = []

        # Optional slot unification via recommendation analyzer
        try:
            if (not inp.missing_fields) and inp.query:
                from src.app.services.recommendations import RecommendationService
                analyzer = RecommendationService()
                analysis = analyzer.analyze_query(inp.query)
                slots = analysis.get("slots") or {}
                followups = analysis.get("followups") or []
                derived_missing: List[str] = []
                if not slots.get("price_min") and not slots.get("price_max") and not slots.get("budget"):
                    derived_missing.append("budget")
                if not (slots.get("specs") or {}).get("ram_gb_min"):
                    derived_missing.append("specs")
                if not analysis.get("entities", {}).get("use_case"):
                    derived_missing.append("use_case")
                if not (analysis.get("entities", {}).get("brands")):
                    derived_missing.append("brand_preference")
                # Merge with provided missing_fields without duplicates
                inp.missing_fields = list({*(inp.missing_fields or []), *derived_missing})
                # Emit trace for learning loop
                if inp.trace_id:
                    try:
                        log_trace_event(
                            trace_id=inp.trace_id,
                            event_type="nqe_slots_unified",
                            source_type="agent",
                            source_id="NQE_Engine",
                            target_type="system",
                            target_id=None,
                            payload={"derived_missing": derived_missing, "followups": followups[:3]},
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        if "order_id" in inp.missing_fields:
            questions.append(
                NextQuestion(
                    id="ask_order_id",
                    text="Could you share the order number or the email/phone used at checkout?",
                    goal="clarify_details",
                    evidence_needed=["none"],
                )
            )

        if "amount" in inp.missing_fields:
            questions.append(
                NextQuestion(
                    id="ask_amount",
                    text="Do you remember the purchase amount (approximate is fine)?",
                    goal="clarify_details",
                    evidence_needed=["none"],
                )
            )

        # Prioritize templates that correspond to missing_fields first
        # Template governance: allow per-tenant overrides if templates support it
        raw_templates = self.templates.get_templates(
            inp.intent,
            inp.product_category,
            tenant_id=inp.tenant_id,
            variant=inp.template_variant,
            version=inp.template_version,
            trace_id=inp.trace_id,
        )
        if inp.trace_id:
            try:
                template_meta = {}
                if raw_templates:
                    template_meta = {
                        "variant": raw_templates[0].get("variant"),
                        "version": raw_templates[0].get("version"),
                    }
                log_trace_event(
                    trace_id=inp.trace_id,
                    event_type="nqe_template_selection",
                    source_type="agent",
                    source_id="NQE_Engine",
                    target_type=None,
                    target_id=None,
                    payload=template_meta,
                )
            except Exception:
                pass
        def relevance(tmpl_id: str) -> int:
            id_low = (tmpl_id or '').lower()
            score = 0
            for mf in (inp.missing_fields or []):
                mfl = str(mf or '').lower()
                if not mfl:
                    continue
                # Map common fields to template ids
                if mfl in ('budget', 'price') and ('budget' in id_low):
                    score += 2
                if mfl in ('use_case', 'intent') and ('use_case' in id_low or 'platform' in id_low):
                    score += 2
                if mfl in ('brand_preference', 'brand') and ('brand' in id_low):
                    score += 2
                if mfl in ('specs', 'spec') and ('spec' in id_low):
                    score += 1
            return score
        prioritized = sorted(raw_templates, key=lambda t: (-relevance(t.get('id')), t.get('id')))
        # Ensure coverage: include one question per key missing field before capping
        def find_tmpl(ids: List[str]) -> Optional[dict]:
            idset = {i for i in ids if i}
            for t in prioritized:
                if t.get('id') in idset:
                    return t
            return None
        coverage: List[dict] = []
        mfs = [str(m or '').lower() for m in (inp.missing_fields or [])]
        if any(m in ('budget','price') for m in mfs):
            t = find_tmpl(['ask_budget_tier','ask_budget'])
            if t: coverage.append(t)
        if any(m in ('use_case','intent') for m in mfs):
            t = find_tmpl(['ask_use_case','ask_platform'])
            if t: coverage.append(t)
        if any(m in ('brand_preference','brand') for m in mfs):
            t = find_tmpl(['ask_brand_pref'])
            if t: coverage.append(t)
        # Add remaining prioritized templates after coverage (preserve order), then convert
        seen_ids = {t.get('id') for t in coverage}
        ordered = coverage + [t for t in prioritized if t.get('id') not in seen_ids]
        for tmpl in ordered:
            questions.append(NextQuestion(**tmpl))

        rag_hits = self.rag.retrieve(f"{inp.product_category} {inp.intent} troubleshooting", tenant_id=inp.tenant_id)
        # Filter RAG by source reliability if configured
        min_rel = 0.0
        try:
            import os
            min_rel = float(os.environ.get("NQE_RAG_MIN_RELIABILITY", "0") or 0.0)
        except Exception:
            min_rel = 0.0
        filtered_hits = []
        for h in rag_hits or []:
            try:
                rel = float(h.meta.get("reliability", 1.0) or 1.0)
            except Exception:
                rel = 1.0
            if rel >= min_rel:
                filtered_hits.append(h)
        if rag_hits and inp.trace_id:
            try:
                log_trace_event(
                    trace_id=inp.trace_id,
                    event_type="rag_retrieved",
                    source_type="agent",
                    source_id="RAG_Retriever",
                    target_type="system",
                    target_id=None,
                    payload={
                        "query": f"{inp.product_category} {inp.intent} troubleshooting",
                        "chunks": [
                            {"doc_id": h.doc_id, "chunk_id": h.chunk_id, "score": h.score, "source": h.meta.get("source")}
                            for h in rag_hits
                        ],
                    },
                )
            except Exception:
                pass
        for hit in filtered_hits[:2]:
            questions.append(
                NextQuestion(
                    id=f"rag_{hit.chunk_id}",
                    text=f"Based on policy guidance: {hit.text}",
                    goal="clarify_details",
                    evidence_needed=["none"],
                    source="rag",
                )
            )

        # Risk-aware suggestion to run quick security/policy checks when signals warrant it
        try:
            if float(inp.risk_score or 0.0) >= 0.7:
                questions.append(
                    NextQuestion(
                        id="security_check",
                        text="Would you like me to run quick security/policy checks on this request?",
                        goal="policy_suggestion",
                        evidence_needed=["none"],
                        source="template",
                    )
                )
        except Exception:
            pass

        deduped: Dict[str, NextQuestion] = {}
        for q in questions:
            deduped[q.id] = q

        # Risk-aware cap: ask fewer questions when risk is high to reduce friction.
        cap = 3 if inp.risk_score < 0.7 else 2
        # Keep guaranteed coverage even if > cap by trimming after ensuring at least one per missing field group
        out = list(deduped.values())
        if len(out) > cap:
            # Prefer keeping coverage items first
            keep_ids = [q.id for q in out if q.id in ('ask_budget','ask_budget_tier','ask_use_case','ask_platform','ask_brand_pref')]
            result: List[NextQuestion] = []
            for q in out:
                if q.id in keep_ids and q not in result:
                    result.append(q)
                if len(result) >= cap:
                    break
            if len(result) < cap:
                for q in out:
                    if q not in result:
                        result.append(q)
                    if len(result) >= cap:
                        break
            # Log proposed followups for learning loop
            if inp.trace_id:
                try:
                    log_trace_event(
                        trace_id=inp.trace_id,
                        event_type="nqe_followups_proposed",
                        source_type="agent",
                        source_id="NQE_Engine",
                        target_type=None,
                        target_id=None,
                        payload={"question_ids": [q.id for q in result[:cap]]},
                    )
                except Exception:
                    pass
            return result[:cap]
        return out
