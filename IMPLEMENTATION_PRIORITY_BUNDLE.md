# ShopSquire Agentic Platform — Prioritized Build Bundle (for Coding Agents)

This file bundles **what to build next**, in **priority order**, with **concrete code skeletons**, **file locations**, and **approximate lines of code (LOC)**.  
It is aligned with the existing deep-dive analysis document (Decision Trace, Dynamic Trace Logs, Security Observer, CV integration, guided flows, graph/time-series, etc.).

---

## How to use this bundle

- Treat each **P0/P1/P2** section as a sprint-sized epic.
- Each task includes:
  - **Outcome / Acceptance criteria**
  - **Suggested files**
  - **Approx LOC**
  - **Code skeleton** (copy/paste friendly)

---

# P0 — Foundation (must-have before “smart” features)

## P0.1 Dynamic Decision Trace (real-time, event-driven, no hardcoding)

### Outcome
- Trace updates **during execution**, not at end.
- Frontend trace panel shows events as they happen (SSE/WebSocket).
- Every agent step produces a machine-readable event with evidence pointers.

### Suggested files
- `src/app/trace/events.py` (schemas)
- `src/app/trace/logger.py` (writer)
- `src/app/trace/stream.py` (SSE/WS)
- `src/app/middleware/trace_mw.py` (request correlation)
- `src/app/agents/*` (emit events)

### Approx LOC
- 450–900 LOC total (backend) + 150–350 LOC (frontend stream UI)

### Code skeleton
```python
# src/app/trace/events.py
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional, Dict, List
from datetime import datetime

TraceEventType = Literal[
  "request_received", "intent_classified", "rag_retrieved", "cv_analyzed",
  "policy_gate", "tool_call", "deception_signal", "risk_scored",
  "next_questions", "verdict", "human_escalation", "error"
]

class EvidenceRef(BaseModel):
    kind: Literal["text", "image", "file", "db", "graph", "timeseries"]
    ref: str                    # e.g., sha256:..., s3://..., db:table/id
    meta: Dict[str, Any] = Field(default_factory=dict)

class TraceEvent(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    ts: datetime = Field(default_factory=datetime.utcnow)
    type: TraceEventType
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[EvidenceRef] = Field(default_factory=list)
    severity: Literal["debug","info","warn","error"] = "info"
```

```python
# src/app/trace/logger.py
import json, uuid
from .events import TraceEvent
from typing import Iterable

class TraceWriter:
    def __init__(self, sink):
        self.sink = sink  # postgres, redis stream, kafka, file, etc.

    async def emit(self, event: TraceEvent) -> None:
        await self.sink.append(event.model_dump())

def new_span_id() -> str:
    return uuid.uuid4().hex
```

```python
# src/app/trace/stream.py (SSE example)
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio, json

router = APIRouter()

@router.get("/trace/{trace_id}/events")
async def stream_trace(trace_id: str):
    async def gen():
        # Subscribe to redis stream / db polling / in-memory pubsub
        async for evt in subscribe_trace(trace_id):
            yield f"data: {json.dumps(evt)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
```

---

## P0.2 Fix backend/frontend connectivity and production basics (CORS, timeouts, env, errors)

### Outcome
- Correct ports, reliable API base URL, consistent env config.
- Timeouts and retries set for model calls/tools.
- Standard error envelope returned to UI; UI handles gracefully.

### Suggested files
- `src/app/main.py` (CORS, routers)
- `src/app/config.py` (env)
- `src/app/http/client.py` (timeouts)
- `frontend/src/config.ts` (API URL)
- `src/app/errors.py` (error envelope)

### Approx LOC
- 200–450 LOC

### Code skeleton
```python
# src/app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_PORT: int = 8000
    FRONTEND_ORIGIN: str = "http://localhost:3000"
    DATABASE_URL: str
    TRACE_SINK: str = "postgres"
    MODEL_TIER_1: str = "ollama:apollo-astralis:4b"
    MODEL_TIER_2: str = "ollama:larger-model"
    class Config:
        env_file = ".env"

settings = Settings()
```

```python
# src/app/errors.py
from pydantic import BaseModel
from typing import Optional, Dict, Any

class ApiError(BaseModel):
    code: str
    message: str
    trace_id: Optional[str] = None
    details: Dict[str, Any] = {}
```

---

## P0.3 Policy Gate at the tool boundary (Transaction Firewall “allow/deny + evidence”)

### Outcome
- Every action/tool call (refund, label, payout, address change, external fetch) is gated.
- Gate emits a `policy_gate` trace event with:
  - rule hits
  - allow/deny decision
  - reasons
  - policy version

### Suggested files
- `src/app/policy/engine.py`
- `src/app/policy/rules/*.py`
- `src/app/tools/*` (wrap calls)

### Approx LOC
- 350–800 LOC

### Code skeleton
```python
# src/app/policy/engine.py
from dataclasses import dataclass
from typing import Dict, Any, List, Literal

Decision = Literal["allow","deny","review"]

@dataclass
class PolicyDecision:
    decision: Decision
    reasons: List[str]
    rule_hits: Dict[str, float]  # rule -> score
    policy_version: str

class PolicyEngine:
    def __init__(self, rules, version="2026-01-27"):
        self.rules = rules
        self.version = version

    async def evaluate(self, ctx: Dict[str, Any]) -> PolicyDecision:
        hits = {}
        reasons = []
        score = 0.0
        for r in self.rules:
            h = await r.check(ctx)
            if h:
                hits[r.name] = h.score
                reasons.append(h.reason)
                score += h.score
        if score >= 0.8:
            return PolicyDecision("deny", reasons, hits, self.version)
        if score >= 0.4:
            return PolicyDecision("review", reasons, hits, self.version)
        return PolicyDecision("allow", reasons, hits, self.version)
```

---

# P1 — Reduce human time waste + increase customer “felt heard”

## P1.1 Next-Question Engine (NQE): guided troubleshooting + evidence capture before escalation

### Why
- Reduces back-and-forth and human escalations.
- Keeps buyer engaged with purposeful, empathetic steps.

### Outcome
- For **repair/refund/replace/return** flows:
  - Ask 1–3 “highest value” questions at a time.
  - Each question is tagged with **what it verifies** and **what evidence it needs**.
- Stops when:
  - enough evidence to decide OR
  - user distressed OR
  - fraud risk high OR
  - policy exception

### Suggested files
- `src/app/flows/nqe.py`
- `src/app/flows/catalog.py` (question templates per category)
- `src/app/agents/consumer_support_agent.py` (calls NQE)
- `src/app/trace/events.py` (event type: `next_questions`)

### Approx LOC
- 450–1,200 LOC

### Code skeleton
```python
# src/app/flows/nqe.py
from pydantic import BaseModel
from typing import List, Literal, Optional, Dict, Any

class NextQuestion(BaseModel):
    id: str
    text: str
    goal: Literal["verify_defect","verify_eligibility","reduce_fraud_risk","clarify_details"]
    evidence_needed: List[Literal["photo","video","receipt","serial","none"]] = []
    stop_condition: Optional[str] = None

class NQEInput(BaseModel):
    intent: str
    product_category: str
    symptom: Optional[str] = None
    timeline_days: Optional[int] = None
    risk_score: float = 0.0
    missing_fields: List[str] = []

class NextQuestionEngine:
    def __init__(self, rag, templates):
        self.rag = rag
        self.templates = templates

    async def propose(self, inp: NQEInput) -> List[NextQuestion]:
        # 1) deterministic must-ask checks
        qs = []
        if "order_id" in inp.missing_fields:
            qs.append(NextQuestion(
                id="ask_order_id",
                text="Could you share the order number (or the email/phone used at checkout)?",
                goal="clarify_details",
                evidence_needed=["none"]
            ))
        # 2) category troubleshooting from RAG
        if inp.product_category:
            kb = await self.rag.retrieve(query=f"{inp.product_category} defect troubleshooting {inp.symptom}")
            # 3) model-assisted generation (tier-1 local model) with strict schema
            qs += await model_generate_questions(inp, kb)
        # 4) risk-aware cap
        return qs[:3]
```

---

## P1.2 Troubleshooting + Policy RAG (safe, curated, provenance-tagged)

### Outcome
- RAG only retrieves from **approved** sources: policy docs, manufacturer troubleshooting, known defect playbooks.
- Every retrieval returns **document IDs** and is logged as a `rag_retrieved` trace event.
- Output includes citations to doc IDs (internal refs, not web URLs if private).

### Suggested files
- `src/app/rag/index.py` (ingestion)
- `src/app/rag/retrieve.py` (retrieval)
- `src/app/rag/guardrails.py` (tenant, ACL, injection protection)
- `src/app/rag/sources/*` (connectors)

### Approx LOC
- 700–1,800 LOC

### Code skeleton
```python
# src/app/rag/retrieve.py
from typing import List, Dict, Any
from dataclasses import dataclass

@dataclass
class RetrievedChunk:
    doc_id: str
    chunk_id: str
    text: str
    score: float

class Retriever:
    async def retrieve(self, query: str, k: int = 6) -> List[RetrievedChunk]:
        # vector search + ACL filter
        chunks = await vector_search(query, k=k)
        return [c for c in chunks if await acl_allows(c.doc_id)]
```

---

## P1.3 Case Evidence Bundle + chain-of-custody (CV/NLP outputs become “proof artifacts”)

### Outcome
- Every case has:
  - hashes for uploads
  - OCR outputs w/ bounding boxes
  - CV forensics scores
  - deception signals
  - graph/time-series flags
  - final verdict + versioned policy decision
- Escalation produces a “one-page case brief” automatically.

### Suggested files
- `src/app/case/models.py`
- `src/app/case/service.py`
- `src/app/case/brief.py` (LLM-generated but schema-bound)
- `src/app/storage/hashing.py`

### Approx LOC
- 600–1,500 LOC

### Code skeleton
```python
# src/app/storage/hashing.py
import hashlib

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
```

```python
# src/app/case/models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class UploadArtifact(BaseModel):
    artifact_id: str
    sha256: str
    mime: str
    size_bytes: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    exif: Dict[str, Any] = {}

class CaseBundle(BaseModel):
    case_id: str
    order_id: Optional[str] = None
    user_id: Optional[str] = None
    claims: Dict[str, Any] = {}
    uploads: List[UploadArtifact] = []
    nlp: Dict[str, Any] = {}
    cv: Dict[str, Any] = {}
    risk: Dict[str, Any] = {}
    verdict: Dict[str, Any] = {}
```

---

# P2 — Fraud intelligence (graph + time series) and CV forensics

## P2.1 CV pipeline: receipt/serial OCR + manipulation detection + catalog similarity

### Outcome
- Detect: edited receipt, stock photo submission, serial mismatch, tampering signals.
- Output: structured CV report + evidence refs (hashes, pHash, OCR bounding boxes).

### Suggested files
- `src/app/cv/pipeline.py`
- `src/app/cv/ocr.py`
- `src/app/cv/forensics.py`
- `src/app/cv/similarity.py`

### Approx LOC
- 900–2,500 LOC (depending on libraries / models)

### Code skeleton
```python
# src/app/cv/pipeline.py
from typing import Dict, Any
from .ocr import run_ocr
from .forensics import detect_manipulation
from .similarity import match_catalog
from ..trace.logger import TraceWriter
from ..trace.events import TraceEvent, EvidenceRef

async def analyze_upload(image_bytes: bytes, trace_id: str, writer: TraceWriter) -> Dict[str, Any]:
    manip = detect_manipulation(image_bytes)
    ocr = run_ocr(image_bytes)
    sim = await match_catalog(image_bytes)

    await writer.emit(TraceEvent(
        trace_id=trace_id,
        span_id="cv_analyzed",
        type="cv_analyzed",
        message="CV analysis complete",
        data={"manipulation": manip, "ocr": ocr, "similarity": sim},
        evidence=[EvidenceRef(kind="file", ref=f"sha256:{manip['sha256']}")]
    ))
    return {"manipulation": manip, "ocr": ocr, "similarity": sim}
```

---

## P2.2 Deceptive language detection (20+ signals) + manipulation-resistant empathy

### Outcome
- Detect coercion, impersonation, legal intimidation, channel switching, template scams, contradictions.
- Record spans + scores, but do **not** punish users for frustration alone.
- Empathy is controlled: warm tone + strict evidence gates.

### Suggested files
- `src/app/nlp/deception.py`
- `src/app/nlp/sentiment.py`
- `src/app/agents/tone.py` (empathy templates)

### Approx LOC
- 400–1,000 LOC

### Code skeleton
```python
# src/app/nlp/deception.py
import re
from typing import Dict, Any, List

PATTERNS = {
  "false_legal_threat": re.compile(r"\b(sue|lawyer|court)\b", re.I),
  "channel_switching": re.compile(r"\b(email me|whatsapp|telegram|signal)\b", re.I),
  "credential_fishing": re.compile(r"\b(otp|verification code|2fa)\b", re.I),
}

def score_deception(text: str) -> Dict[str, Any]:
    hits = []
    score = 0.0
    for name, rx in PATTERNS.items():
        m = rx.search(text)
        if m:
            hits.append({"type": name, "span": [m.start(), m.end()], "match": m.group(0)})
            score += 0.2
    return {"score": min(score, 1.0), "hits": hits}
```

---

## P2.3 Graph + time series fraud detection (rings + anomalies)

### Outcome
- Build entity graph: account ↔ device ↔ address ↔ payment ↔ order ↔ pHash.
- Detect rings (dense shared entities), abnormal velocities, change points.
- Produce explainable “why flagged” evidence (subgraph summary, time-series deltas).

### Suggested files
- `src/app/analytics/events_sink.py`
- `src/app/analytics/features_timeseries.py`
- `src/app/analytics/graph_builder.py`
- `src/app/analytics/risk_scoring.py`

### Approx LOC
- 1,200–3,000 LOC

### Code skeleton
```python
# src/app/analytics/graph_builder.py
from typing import Dict, Any, List, Tuple

def build_edges(event: Dict[str, Any]) -> List[Tuple[str,str,str]]:
    # returns (src, rel, dst)
    edges = []
    u = f"user:{event['user_id']}"
    if event.get("device_id_hash"):
        edges.append((u, "USED_DEVICE", f"device:{event['device_id_hash']}"))
    if event.get("address_hash"):
        edges.append((u, "USED_ADDRESS", f"address:{event['address_hash']}"))
    if event.get("payment_token"):
        edges.append((u, "PAID_WITH", f"pay:{event['payment_token']}"))
    return edges
```

---

# P3 — Quality, governance, and hardening (what makes it “real”)

## P3.1 Evaluation harness + regression gates

### Outcome
- Offline test set for:
  - intent classification + slot extraction
  - next-question quality (coverage & stop conditions)
  - fraud false positives/negatives
  - CV evidence correctness
- CI blocks regressions.

### Suggested files
- `tests/evals/*.jsonl`
- `src/app/eval/runner.py`

### Approx LOC
- 400–1,200 LOC

---

## P3.2 OWASP mappings + red-team suite (LLM / Agentic / API)

### Outcome
- Every alert mapped to OWASP category.
- Red-team scripts (prompt injection, tool misuse, memory poisoning, SSRF).
- “Fail closed” for high-risk tool calls.

### Suggested files
- `src/app/security/owasp_map.py`
- `src/app/security/redteam/*.py`

### Approx LOC
- 300–900 LOC

---

# Model tiering: where Apollo-Astralis 4B fits

## Tier routing policy (recommended)
- **Tier 0**: rules + small classifier (fastest)
- **Tier 1 (Apollo-Astralis 4B)**: NQE question generation, structured extraction, escalation brief, safe explanations
- **Tier 2 (larger model)**: complex disputes, ambiguous fraud, long multi-tool planning

### Code skeleton
```python
# src/app/models/router.py
from typing import Dict, Any

def choose_model(task: str, ctx: Dict[str, Any]) -> str:
    if task in {"extract", "next_questions", "case_brief"}:
        return "ollama:apollo-astralis:4b"
    if ctx.get("risk_score", 0) > 0.7 and task == "verdict":
        return "ollama:larger-model"
    return "ollama:apollo-astralis:4b"
```

---

# Suggested minimal repo structure

```
src/app/
  agents/
  analytics/
  case/
  cv/
  middleware/
  models/
  nlp/
  policy/
  rag/
  security/
  trace/
  tools/
frontend/
  src/
tests/
```

---

# Definition of Done (DoD) checklist (apply to every task)
- ✅ Emits trace events with `trace_id`
- ✅ Stores evidence refs (hashes/doc IDs)
- ✅ Has unit tests for core logic
- ✅ Has a “happy path” + “abuse path”
- ✅ Frontend shows state/progress without spinner-only dead time

---

## Quick sequencing (if you’re solo + coding agents)

**Week 1 / Next 2–4 days:** P0.1 + P0.3 (trace + policy gate)  
**Week 2:** P1.1 + P1.2 (NQE + RAG)  
**Week 3+:** P1.3 + P2.1 (evidence bundle + CV)  
**Then:** P2.3 (graph/time series) + P3 (eval/redteam)

