from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from src.app.services.decision_log import log_trace_event
from src.app.services.faq_bank import FAQ_BANK


class PlanInput(BaseModel):
    question: str
    max_queries: int = Field(default=3, ge=1, le=8)


class PlanOutput(BaseModel):
    queries: List[str]
    intent: str


class RetrievedChunk(BaseModel):
    context_id: str
    source: str
    trust_score: float
    score: float
    text: str


class RetrieveOutput(BaseModel):
    chunks: List[RetrievedChunk]


class RankOutput(BaseModel):
    context_ids: List[str]


class InjectionOutput(BaseModel):
    context_ids: List[str]
    source_trust_scores: Dict[str, float]
    budget_chars: int
    used_chars: int


class DecideOutput(BaseModel):
    answer: str
    confidence: float
    citations: List[str]


class VerifyOutput(BaseModel):
    pass_gate: bool
    issues: List[str]


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def _plan(inp: PlanInput) -> PlanOutput:
    q = (inp.question or "").strip()
    tokens = _tokenize(q)
    queries = [q]
    if tokens:
        queries.append(" ".join(tokens[: min(6, len(tokens))]))
    if any(k in q.lower() for k in ("refund", "return", "warranty", "broken", "damaged")):
        intent = "returns_warranty"
        queries.append("return policy warranty damage evidence")
    elif any(k in q.lower() for k in ("shipping", "delivery", "track")):
        intent = "shipping"
        queries.append("shipping tracking delivery")
    else:
        intent = "general"
    return PlanOutput(queries=list(dict.fromkeys(queries))[: inp.max_queries], intent=intent)


def _retrieve(plan: PlanOutput) -> RetrieveOutput:
    out: List[RetrievedChunk] = []
    for item in FAQ_BANK:
        q = str(item.get("q") or "")
        a = str(item.get("a") or "")
        tags = " ".join([str(t) for t in (item.get("tags") or [])])
        corpus = f"{q} {a} {tags}".lower()
        score = 0.0
        for pq in plan.queries:
            tk = _tokenize(pq)
            if not tk:
                continue
            overlap = sum(1 for t in tk if t in corpus)
            score = max(score, float(overlap) / float(max(1, len(tk))))
        if score <= 0:
            continue
        cid = f"faq:{abs(hash(q)) % 100000}"
        out.append(
            RetrievedChunk(
                context_id=cid,
                source="faq_bank",
                trust_score=0.72,
                score=round(score, 4),
                text=f"Q: {q}\nA: {a}",
            )
        )
    out.sort(key=lambda x: (x.score, x.trust_score), reverse=True)
    return RetrieveOutput(chunks=out[:20])


def _rank(ret: RetrieveOutput, max_chunks: int = 5) -> RankOutput:
    keep = [c.context_id for c in sorted(ret.chunks, key=lambda x: (x.score, x.trust_score), reverse=True)[: max(1, max_chunks)]]
    return RankOutput(context_ids=keep)


def _inject(ret: RetrieveOutput, rank: RankOutput, budget_chars: int = 1400) -> InjectionOutput:
    # Policy/security gate before injection.
    blocked_patterns = ("ignore previous", "system prompt", "jailbreak", "override policy")
    selected: List[str] = []
    trust: Dict[str, float] = {}
    used = 0
    chunk_map = {c.context_id: c for c in ret.chunks}
    for cid in rank.context_ids:
        ch = chunk_map.get(cid)
        if ch is None:
            continue
        low = ch.text.lower()
        if any(p in low for p in blocked_patterns):
            continue
        size = len(ch.text)
        if used + size > budget_chars:
            continue
        selected.append(cid)
        trust[cid] = float(ch.trust_score)
        used += size
    return InjectionOutput(context_ids=selected, source_trust_scores=trust, budget_chars=budget_chars, used_chars=used)


def _decide(question: str, ret: RetrieveOutput, inj: InjectionOutput) -> DecideOutput:
    cmap = {c.context_id: c for c in ret.chunks}
    snippets = [cmap[cid].text for cid in inj.context_ids if cid in cmap]
    if not snippets:
        return DecideOutput(answer="No high-trust context found. Escalate to human review.", confidence=0.35, citations=[])
    answer = snippets[0].split("\nA: ", 1)[-1].strip()
    confidence = min(0.95, 0.45 + (0.1 * len(inj.context_ids)))
    return DecideOutput(answer=answer, confidence=round(confidence, 4), citations=inj.context_ids[:4])


def _verify(dec: DecideOutput, inj: InjectionOutput) -> VerifyOutput:
    issues: List[str] = []
    if not dec.citations:
        issues.append("missing_citations")
    if inj.used_chars > inj.budget_chars:
        issues.append("budget_exceeded")
    if dec.confidence < 0.4:
        issues.append("low_confidence")
    return VerifyOutput(pass_gate=(len(issues) == 0), issues=issues)


def run_agentic_rag_pipeline(
    *,
    question: str,
    trace_id: str | None = None,
    context_budget_chars: int = 1400,
    max_chunks: int = 5,
) -> Dict[str, Any]:
    tid = trace_id or f"rag-{uuid.uuid4()}"
    plan_in = PlanInput(question=question)
    plan = _plan(plan_in)
    log_trace_event(
        trace_id=tid,
        event_type="rag_plan",
        source_type="agent",
        source_id="RAG_Planner_Agent",
        target_type="pipeline",
        target_id="agentic_rag",
        payload=plan.model_dump(),
    )
    ret = _retrieve(plan)
    log_trace_event(
        trace_id=tid,
        event_type="rag_retrieve",
        source_type="agent",
        source_id="RAG_Retriever_Agent",
        target_type="pipeline",
        target_id="agentic_rag",
        payload={"retrieved": len(ret.chunks), "context_ids": [c.context_id for c in ret.chunks[:10]]},
    )
    rank = _rank(ret, max_chunks=max_chunks)
    log_trace_event(
        trace_id=tid,
        event_type="rag_rank",
        source_type="agent",
        source_id="RAG_Ranker_Agent",
        target_type="pipeline",
        target_id="agentic_rag",
        payload=rank.model_dump(),
    )
    inj = _inject(ret, rank, budget_chars=context_budget_chars)
    log_trace_event(
        trace_id=tid,
        event_type="context_injected",
        source_type="agent",
        source_id="RAG_Context_Injector_Agent",
        target_type="llm_context",
        target_id="dynamic_injection",
        payload=inj.model_dump(),
    )
    dec = _decide(question, ret, inj)
    log_trace_event(
        trace_id=tid,
        event_type="rag_decide",
        source_type="agent",
        source_id="RAG_Decider_Agent",
        target_type="response",
        target_id="assistant",
        payload=dec.model_dump(),
    )
    ver = _verify(dec, inj)
    log_trace_event(
        trace_id=tid,
        event_type="rag_verify",
        source_type="agent",
        source_id="RAG_Verifier_Agent",
        target_type="response",
        target_id="assistant",
        payload=ver.model_dump(),
    )
    return {
        "status": "ok",
        "trace_id": tid,
        "pipeline": "agentic_rag",
        "answer": dec.answer,
        "confidence": dec.confidence,
        "citations": dec.citations,
        "context_ids": inj.context_ids,
        "source_trust_scores": inj.source_trust_scores,
        "context_budget_chars": inj.budget_chars,
        "context_used_chars": inj.used_chars,
        "verification": ver.model_dump(),
    }

