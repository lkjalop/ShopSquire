# ShopSquire — Delta, Security Posture, Competitive Position & Showcase Plan (2026-08-02)

*Delta since the 2026-07-29 deep dive (HEAD `b07beaf9` → `b3dca021`). What it can now defend itself
from, how the competitive field moved, and eight things to show.*

---

## 1. Delta — the pattern finally inverted

**116 commits in 4 days.** But the shape changed, and this is the headline:

| Measure | 2026-07-29 | 2026-08-02 | Δ |
|---|---:|---:|---:|
| **`src/`** | 271,310 | **265,958** | **−5,352** ⬇ |
| `tests/` | 101,686 | **104,905** | +3,219 |
| `frontend/` | 18,756 | **20,218** | +1,462 |
| `alembic/` | 7,046 | **8,078** | +1,032 |
| Migrations | 86 | **98** | +12 |
| Services | 424 | 434 | +10 |
| Security modules | 137 | 140 | +3 |
| **Total** | 416,587 | **418,042** | +1,455 |

**Source code shrank while tests grew.** For four days I have been writing that the risk was building
faster than validating. That reversed. The commit titles say it plainly: *migrate residual
recommendation tests to V2 contracts · freeze retired V1 CV NQE characterization · isolate
migration-first state contract tests · consolidate Decision Trace trust UX · ground hosted V2
fixtures.* This is a consolidation phase, and it is the right one.

### Three recommendations landed

**1. Decision Trace restructured 14 tabs → 5 sections.** (`DecisionTrace.tsx`, 4,402 → 4,769)
```js
{ id: 'decision',        label: 'Decision',            leaves: ['summary','events','execution'] },
{ id: 'reasoning',       label: 'Reasoning',           leaves: ['why','intent','memory','complexity'] },
{ id: 'evidence-risk',   label: 'Evidence & Risk',     leaves: ['evidence','multimodal','security'] },
{ id: 'commercial',      label: 'Commercial Journey',  leaves: ['market','procurement'] },
{ id: 'audit-technical', label: 'Audit & Technical',   leaves: ['audit','raw'] },
```
Plus a **TrustCue** layer that grades every decision's authority in plain language:
`Human approved` · `Platform authorized` · `Proposal only` · `Authority unrecorded` ·
`Freshness unknown`. That is the abstention doctrine surfaced as UI, which is what the trace was
missing.

**2. The security corpus became a test.** `tests/security/test_generated_security_corpus.py` — **6
tests, passing**, hash-verifying all 46 artifacts and exercising **real production code**:
```python
from src.app.routers.vision import _canonical_qr_assessment
from src.app.security.csv_safety import neutralize_csv_text
from src.app.security.email_attachment_parser import hydrate_attachments_from_bytes
from src.app.services.intake_gate import sanitize_attachment_ocr_for_llm, strict_binary_ingest_gate
```
Including `test_supplier_pdf_injection_is_detected_and_removed_from_model_context` — the exact LLM01
proof I argued was the single strongest thing to build.

**3. Cloud portability.** `src/app/providers/{aws,azure}.py` + `terraform/` + `infra/azure`. The
"no cloud SDK in the application layer" boundary is real, and AWS landed alongside Azure.

### New defensive code written to make the corpus pass
| Module | Lines | What it does |
|---|---:|---|
| `services/intake_gate.py` | **743** | MIME sniffing, **polyglot signature detection**, archive depth inspection, AV scan hook, **NFKC normalisation**, zero-width + **bidi-override stripping** |
| `security/email_attachment_parser.py` | **896** | attachment hydration and forensic parse |
| `security/csv_safety.py` | 42 | formula-injection neutralisation on `= + - @` |

The bidi comment is worth reading — it isn't generic hardening, it's a specific threat model:
> *"bidi overrides used to hide a real address behind a rendered one… a legitimate email almost never
> carries a bidi override"*

---

## 2. What it can now defend itself from

Articulate it as **five layers**, because that's how a security reviewer will ask:

| Layer | Threat | Control |
|---|---|---|
| **Ingress** | polyglots, MIME lies, decompression bombs, malicious SVG, archive recursion | `strict_binary_ingest_gate` — sniff over extension, polyglot signatures, depth/size ceilings, AV hook |
| **Encoding** | zero-width chars, bidi override, homoglyphs defeating regex detection | NFKC normalise → strip obfuscation → *then* pattern match |
| **Content** | prompt injection in images, EXIF/XMP, QR codes, supplier PDFs, CSV formulas | OCR + pattern scan, `sanitize_attachment_ocr_for_llm`, `neutralize_csv_text`, QR quarantine |
| **Semantic** | claims that cannot be constructed from evidence | currency / UoM / ATP / evidence / identity / simulation **authorities** |
| **Action** | agent spending money, emailing suppliers, merging customers | `auto_sent: False`, human send gate, four-eyes on identity, `KILL_SWITCH`, hash-chained `audit_log_chain` |

**Layers 1–3 are what everyone means by AI security. Layer 4 is the one almost nobody has.**

### Against the 2026 enterprise procurement checklist
Research finding: *"By mid-2026, enterprise procurement checklists routinely demand kill switches,
evidentiary audit trails, human-in-the-loop boundaries, model change control, and ISO/IEC 42001 or
SOC 2 attestations as gating conditions."*

| Gating item | ShopSquire |
|---|---|
| Kill switch | ✅ `KILL_SWITCH` in config + schema |
| Evidentiary audit trail | ✅ `audit_log_chain` with `payload_hash` + `prev_hash` — **a hash chain, i.e. tamper-evident** |
| Human-in-the-loop boundaries | ✅ `send_gate: human`, `auto_sent: False`, four-eyes |
| Model change control | ✅ model/prompt/policy versions carried on results |
| **ISO 42001 / SOC 2** | ❌ **the only gap** — and it's a certification, not an engineering task |

**Four of five, built before the checklist was written.** That is the strongest single fact in this
document.

---

## 3. The competitive field moved — and a new category appeared

Since the last analysis, **"AI agent governance platform" became a named category**: Fiddler
(repositioned January 2026 as *"the AI Control Plane for Enterprise Agents"*), Arthur (*"industry's
first Agent Discovery & Governance platform"*), FutureAGI (self-hostable runtime consolidating
enforcement + audit + registry + gateway), Trustible, Modulos. Trustible now counts **16 types** of
governance platform across six groups.

**This is validation, not threat** — the market decided governance is the product. But it changes the
comparison, so be precise about it:

| | Horizontal governance platforms | ShopSquire |
|---|---|---|
| **Governs** | any agent, domain-agnostic | commerce decisions specifically |
| **Question answered** | *"did the agent behave suspiciously?"* | *"is this claim constructible from the evidence?"* |
| **Method** | behavioural / statistical — Fiddler scores 11 safety dimensions incl. prompt injection and hallucination | semantic / deterministic — authorities |
| **Can it know AUD ≠ USD?** | ❌ | ✅ |
| **Can it know "each" ≠ "case of 24"?** | ❌ | ✅ |
| **Can it know on-hand ≠ available?** | ❌ | ✅ |
| **Deployment** | mostly SaaS (FutureAGI self-hostable) | self-hosted / BYO-model |

### The differentiation sentence
> **Horizontal governance platforms detect that an agent behaved badly. ShopSquire prevents the bad
> claim from being constructible in the first place — because it knows what the numbers mean.**

**And this gap is structural, not a feature backlog.** A domain-agnostic platform *cannot* enforce
that a quote comparison is invalid because the FX rate is stale, or that ATP is unknown because
reservations weren't supplied. Those require knowing the business semantics of the data. You cannot
bolt domain authorities onto a horizontal governor; you have to build them into the decision path.

### The full field
| Player | Owns | Structural limit |
|---|---|---|
| **Sierra** ($15.8B, F50) | channel-first CX agents, "compliance-grade policy governance", pro-code | 3–7 month deploys, six figures, no mid-market, no procurement |
| **Agentforce** | inherits Salesforce Trust Layer + owns the CRM relationship | conversion-centric, SaaS-only, priced past SMB |
| **Fiddler / Arthur / FutureAGI** | agent observability + policy, audit-grade evidence | domain-blind — cannot enforce commerce semantics |
| **Blue Yonder / o9 / Kinaxis** | agents inside a planning model | *"strongest inside the planning estate, still building out action beyond it"*; provenance not a feature |
| **Coupa / Zip / Ariba** | source-to-pay, intake orchestration | no buyer-side catalog truth, no conversational grounding |
| **ChatGPT / Rufus / Gemini** | buyer discovery → checkout, huge distribution | conversion-optimised; a refusal is a loss to them |
| **ShopSquire** | buyer conversation → catalog → margin → procurement → supplier, one audit trail, self-hosted | no customer, no production traffic, no certification |

---

## 4. Why someone would choose it

**Be honest about who wouldn't.** If you want an AI that always answers, or you're an enterprise that
wants a vendor with SOC 2 and a support org — not this, not yet.

The five reasons that hold:

1. **It runs in your perimeter, on your model.** Not a data processor. For a distributor whose
   supplier pricing is the competitive edge, uploading it to a SaaS is the objection that ends the
   conversation.
2. **Zero marginal cost per conversation.** Agentforce rewrote pricing three times in 18 months;
   Sierra and Decagon are six figures. Self-hosted with BYO-model, a conversation costs electricity.
3. **It refuses, and shows the working.** The 2026 buyer question is *"what happens when it's
   wrong?"* — and the answer "it structurally can't construct that claim" is different in kind from
   "we have guardrails."
4. **Four of five enterprise gating items already exist** — kill switch, tamper-evident audit chain,
   HITL boundaries, model change control.
5. **It spans the join nobody else does.** CRM owns the customer, support owns the ticket, Coupa owns
   the PO, Fiddler owns the agent trace. Nobody owns buyer→catalog→margin→procurement→supplier under
   one audit trail.

---

## 5. Eight things to show on LinkedIn — and why each one works

Each is one post. **One idea, one artifact, one trade-off.** Lead with the trade-off, because that's
the register that reads as senior rather than promotional.

---

### 1. 🥇 "I deleted 12,403 lines and wrote a test so I couldn't lie about it"
**Artifact:** `test_recommend_v1_archive.py` — hash-sealed manifest recording `"failed": 36`,
`"status": "non_executable_historical_evidence"`.
**Trade-off:** *I could have quietly dropped the failing tests during the migration. Everyone does.
Instead I sealed the number so that future-me can't claim the retired engine was green.*
**Proves:** you retire your own work, and you engineer against your own future dishonesty. **Start
here — it's the most universally recognised failure in software and almost nobody guards against it.**

### 2. "My AI can't tell you if $1,800 is enough — and that's the feature"
**Artifact:** `currency_authority.py` — 188 lines, **8 refusals, one every 23 lines**.
**Trade-off:** *The catalog has AUD and USD. I could show a number and be right most of the time.
Instead nothing can compare currencies without a dated, sourced, approved FX authority. Users
sometimes get "I can't answer that." That is the cost, and I chose it.*
**Proves:** abstention as architecture. Contrarian in the exact direction the industry is running.

### 3. "I built a quality gate and it told me no"
**Artifact:** replay where every metric passes and `gates_pass: False`, plus the 19-row adjudication
ledger where six divergences are marked `known_wrong_v1`.
**Trade-off:** *A gate that only confirms you is decoration. Mine can fail while every metric is
green, because unresolved parity differences block certification regardless.*
**Proves:** ML evaluation discipline; you build measurement that can refute you.

### 4. "A supplier's PDF told my agent to skip the human approval. Here's what happened."
**Artifact:** `supplier_quote_indirect_injection.pdf` (white-on-white instructions) → the trace
showing the text classified `untrusted:document_text`, reaching the pattern scanner and **blocked
from model context**.
**Trade-off:** *Reading supplier documents is the point of the feature. Treating their contents as
data and never instruction costs a whole parsing layer. Worth it.*
**Proves:** you understand indirect prompt injection as a *supply-chain* problem, not a chatbot one.
**This is the most under-discussed real risk in agentic commerce.**

### 5. "46 attack files, and two of them still get through"
**Artifact:** the corpus + `test_generated_security_corpus.py`, including the documented gaps
(`injection_mirrored`, `injection_edge_cropped`).
**Trade-off:** *I could have removed the two artifacts that fail. A corpus where everything passes
isn't testing anything.*
**Proves:** security thinking plus the willingness to publish your own misses.

### 6. "Why I said no to Kafka, MongoDB, TiDB and Flink"
**Artifact:** the audit — 1,076 raw SQL calls, 67 `ON CONFLICT`, 25 pgvector sites.
**Trade-off:** *I'm event-sourced, so Kafka is the obvious call. But my event log is the database,
and that's deliberate: events are transactional with the projections they feed. Kafka would
introduce dual-write between log and read model — and then I'd have to defend that in an audit.*
**Proves:** senior restraint. **The rarest signal on this list** — engineers get hired for what they
chose *not* to build far more often than they expect.

### 7. "A supplier that always takes 10 days beats one averaging 7"
**Artifact:** `reliability = exp(-σ_lead / mean_lead)` in the supplier composite; lead-time variance
feeding safety stock.
**Trade-off:** *Scoring on speed is the obvious model and it's wrong. Variance destroys safety stock;
consistency is what you can plan around. So reliability rewards low σ, not low mean.*
**Proves:** domain modelling depth — you understand the business, not just the code.

### 8. "Deleting a 12,000-line file made the app boot faster and nothing broke"
**Artifact:** src shrank 5,352 lines in four days while tests grew 3,219; `recommend.py` 12,403 → 0;
zero importers; 738 routes; boots in 4s.
**Trade-off:** *Four days of no new features. The pressure is always to add. Consolidation is the
part nobody posts about.*
**Proves:** you finish. And it's a rare, honest counter-post to the build-in-public genre.

---

### How to run the series
- **Order:** 1 → 4 → 2 → 6 → 3 → 7 → 5 → 8. Start with the most universal, end with the most niche.
- **Cadence:** one per week. Eight weeks of consistent senior-signal beats one long demo.
- **Format:** the trade-off in the post body, the code as an image, no link-in-first-comment games.
- **Close every one identically:** *"No customer, no production traffic, synthetic data. What I can
  prove is the engineering and that my measurement apparatus is honest enough to tell me when I'm
  wrong."* Repetition of that line across eight posts **is** the personal brand.

---

## 6. What still hasn't moved

Unchanged and still the only things that matter:

1. **No outside contact.** 116 more commits, still nobody using it.
2. **Relevance labels** still `human_reviewed_by: null` — the oldest open item in the project.
3. **ISO 42001 / SOC 2** — now a named procurement gate you don't clear.
4. **David** hasn't received the delta note.

The engineering answer to "is this good?" has been yes for two weeks. **The remaining question has
never been an engineering question.**

---

## Sources

- [AI Agent Governance and Compliance in 2026: Frameworks, Audit Trails, and the Regulatory Reckoning — Zylos Research](https://zylos.ai/research/2026-05-01-ai-agent-governance-compliance-2026/)
- [Buyer-Side Governance: What Enterprise Customers Now Demand From AI Agent Vendors — Zylos Research](https://zylos.ai/research/2026-07-02-buyer-side-governance-enterprise-ai-agent-deployments/)
- [AI Agent Compliance and Governance in 2026: A Practical Guide — FutureAGI](https://futureagi.com/blog/ai-agent-compliance-governance-2026)
- [Top AI Governance Platforms for Agentic AI in 2026 — Arthur](https://www.arthur.ai/column/best-ai-governance-platforms-2026)
- [16 Types of AI Governance Platforms Compared (2026) — Trustible](https://trustible.ai/post/types-of-ai-governance-platforms/)
- [Best AI Governance Platforms in 2026: How to Choose — Secure Privacy](https://secureprivacy.ai/blog/best-ai-governance-platforms-2026)
- [Fiddler AI: Enterprise AI Governance & Observability Platform](https://www.ciopages.com/directory/vendor/fiddler-ai)
- [Agentforce vs. Sierra: How Do They Compare? — Salesforce](https://www.salesforce.com/compare/agentforce-vs-sierra/)
- [Sierra AI In-Depth Report: Inside the $15.8B Agent OS for Enterprise — The CODEW](https://www.thecodew.com/2026/07/sierra-ai-in-depth-report.html)
- [Agentic AI in Supply Chain: What's Shipping in 2026 — Tellius](https://www.tellius.com/resources/blog/agentic-ai-in-supply-chain-use-cases-platforms-and-whats-shipping-2026)

*Assessment only. No code changed. Verified at HEAD `b3dca021`.*
