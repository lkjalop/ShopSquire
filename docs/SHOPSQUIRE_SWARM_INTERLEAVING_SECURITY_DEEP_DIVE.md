# ShopSquire Deep Dive: Swarm Teams, Interleaving, Security, Agentic RAG, and Attack Detection

Generated: 2026-02-24

## 1) Executive Summary
ShopSquire already has real implementations for parallel agent execution, bounded interleaving loops, deterministic security gating, email BEC/DMARC workflows, and supply-chain simulation/swarm testing.  
It is **not** a single monolithic "LLM agent"; it is a policy-first orchestration system where LLM use is optional and bounded.

The biggest gaps are:
1. Some "agentic" features are still heuristic-first (regex/rule-heavy) rather than ML-heavy.
2. Parts of vision/tooling are explicitly placeholders/stubs.
3. "Dynamic context injection" is strong in orchestration and simulation context, but full production-grade RAG is still lightweight.

## 2) Parallel Agent Swarm / Teams

### What exists
1. Orchestrator parallel block:
- [`src/app/services/orchestrator.py:1050`](c:/AI/ShopSquire/src/app/services/orchestrator.py:1050) triggers either DAG exploration or parallel checks.
- [`src/app/services/parallel_agent_executor.py:335`](c:/AI/ShopSquire/src/app/services/parallel_agent_executor.py:335) runs CV, fraud, inventory in parallel with `ThreadPoolExecutor(max_workers=3)`.
- Tool gating is enforced per tool using [`src/app/security/tool_intent_gate.py`](c:/AI/ShopSquire/src/app/security/tool_intent_gate.py).

2. DAG runtime for phase-separated concurrency:
- [`src/app/services/agent_dag_runtime.py:68`](c:/AI/ShopSquire/src/app/services/agent_dag_runtime.py:68) runs phase1 (security+cv) then phase2 (fraud+inventory), with tenant pool limits and tool-intent gate.

3. Swarm implementations (two lanes):
- Supply-chain simulation swarm (Celery-backed):
  [`src/app/routers/admin_supply_chain_sim.py:184`](c:/AI/ShopSquire/src/app/routers/admin_supply_chain_sim.py:184) + [`src/app/tasks/swarm_tasks.py:14`](c:/AI/ShopSquire/src/app/tasks/swarm_tasks.py:14).
- Red-team mutation swarm (threaded in-process):
  [`src/app/security/redteam/swarm.py:47`](c:/AI/ShopSquire/src/app/security/redteam/swarm.py:47).

### How to think about it
- "Teams" are implemented as bounded concurrent jobs with explicit policy checks and trace events.
- "Swarm" is used both for attack simulation and mutation benchmarking.

## 3) Interleaved Thinking

### What exists
1. Generic interleaving runtime:
- [`src/app/services/interleaving_controller.py`](c:/AI/ShopSquire/src/app/services/interleaving_controller.py)
- Budget, max-iteration, timeout, confidence threshold, allowlists, tool-policy hook, traceable events.

2. NLP/tool interleaving in orchestrator:
- [`src/app/services/orchestrator.py:1458`](c:/AI/ShopSquire/src/app/services/orchestrator.py:1458) `_run_interleaving`.
- Uses LLM planning when enabled via [`src/app/services/llm.py:807`](c:/AI/ShopSquire/src/app/services/llm.py:807), otherwise deterministic plan fallback.

3. CV interleaving:
- [`src/app/services/orchestrator.py:1785`](c:/AI/ShopSquire/src/app/services/orchestrator.py:1785) `_run_cv_interleaving`.
- Chains quality, OCR, serial, phash, forensics, evidence tags with tool-intent gating.

### Key point
This is not open-ended autonomous recursion. It is **bounded interleaving** with explicit stop reasons and security denial paths.

## 4) Security Architecture (How it is actually enforced)

### Core detection/correlation
- Observer signal detection + risk scoring: [`src/app/security/observer.py`](c:/AI/ShopSquire/src/app/security/observer.py)
- Tool-intent gate before tool execution: [`src/app/security/tool_intent_gate.py`](c:/AI/ShopSquire/src/app/security/tool_intent_gate.py)
- Agent guardrails for inter-agent interaction: [`src/app/security/agent_guardrails.py`](c:/AI/ShopSquire/src/app/security/agent_guardrails.py)

### Intake hardening
- Intake-only normalization + attachment/QR/OCR sanitization gates:
  [`src/app/services/intake_gate.py`](c:/AI/ShopSquire/src/app/services/intake_gate.py)

### Deterministic policy and actioning
- Policy gate + approvals + blocked/review actions in tool runner:
  [`src/app/tools/runner.py`](c:/AI/ShopSquire/src/app/tools/runner.py)
- Playbook engine with atomic config writes + action execution + DLQ:
  [`src/app/services/playbook_engine.py`](c:/AI/ShopSquire/src/app/services/playbook_engine.py)

## 5) Agentic RAG Pipeline + Dynamic Context Injection (Atomic Agents)

### What exists today
1. Lightweight RAG:
- Static document store from JSON: [`src/app/rag/index.py:21`](c:/AI/ShopSquire/src/app/rag/index.py:21)
- Retrieval with query/doc guardrails: [`src/app/rag/retrieve.py:43`](c:/AI/ShopSquire/src/app/rag/retrieve.py:43), [`src/app/rag/guardrails.py:14`](c:/AI/ShopSquire/src/app/rag/guardrails.py:14)

2. Dynamic context injection pattern:
- Orchestrator injects fresh memory+live state+dependency health into `retrieved_context`:
  [`src/app/services/orchestrator.py:440`](c:/AI/ShopSquire/src/app/services/orchestrator.py:440)
- Supply-chain harness injects per-run bitemporal and scenario context:
  [`src/app/security/supply_chain_harness.py:337`](c:/AI/ShopSquire/src/app/security/supply_chain_harness.py:337)

3. Atomic/isolated "agent steps" pattern:
- Harness chain (`AgentChainLink`) executes step-by-step with explicit outputs:
  [`src/app/security/supply_chain_harness.py:79`](c:/AI/ShopSquire/src/app/security/supply_chain_harness.py:79)

### Important caveat
- Production RAG is currently more "retrieval utility" than a full advanced agentic RAG stack.
- Vector path exists but includes scaffold behavior:
  [`src/app/services/vector_store.py:9`](c:/AI/ShopSquire/src/app/services/vector_store.py:9)

## 6) Prompt Injection Detection

### Where it is detected
1. Broad observer patterns (prompt injection, tool abuse, exfil):
- [`src/app/security/observer.py:116`](c:/AI/ShopSquire/src/app/security/observer.py:116)

2. Email-specific injection and dangerous tool intent:
- [`src/app/security/email_security_rules.py:642`](c:/AI/ShopSquire/src/app/security/email_security_rules.py:642)

3. Tool runner pre-invocation security block:
- [`src/app/tools/runner.py`](c:/AI/ShopSquire/src/app/tools/runner.py)

### Real behavior
- Detection is mainly deterministic regex/heuristics + policy gating.
- Strong for known patterns, weaker for subtle semantic jailbreak variants.

## 7) Email BEC + DMARC

### BEC pipeline
- Indicator extraction: [`src/app/security/email_security_rules.py`](c:/AI/ShopSquire/src/app/security/email_security_rules.py)
- Deterministic verdict + routing + OOB enforcement: [`src/app/security/email_security_verdict.py`](c:/AI/ShopSquire/src/app/security/email_security_verdict.py)
- End-to-end evaluator + ticketing + playbook + trace events: [`src/app/security/email_security.py`](c:/AI/ShopSquire/src/app/security/email_security.py)

### DMARC pipeline
- DMARC ingest/summary API: [`src/app/routers/dmarc.py`](c:/AI/ShopSquire/src/app/routers/dmarc.py)
- Admin summary: [`src/app/routers/admin_dmarc.py`](c:/AI/ShopSquire/src/app/routers/admin_dmarc.py)
- Parser/DB ingest: [`src/app/services/dmarc_ingest.py`](c:/AI/ShopSquire/src/app/services/dmarc_ingest.py)
- Poller: [`src/app/jobs/dmarc_poll.py`](c:/AI/ShopSquire/src/app/jobs/dmarc_poll.py)

## 8) 3rd-Party Supply Chain Attack Detection

### Implemented lanes
1. Runtime baseline/anomaly checks for partner endpoints and response schemas:
- [`src/app/security/supply_chain.py`](c:/AI/ShopSquire/src/app/security/supply_chain.py)

2. SBOM/KEV correlation, OAuth scope anomaly, artifact signature checks, SLSA attestation:
- [`src/app/security/supply_chain_controls.py`](c:/AI/ShopSquire/src/app/security/supply_chain_controls.py)

3. Attack scenario harness + swarm simulation:
- [`src/app/security/supply_chain_harness.py`](c:/AI/ShopSquire/src/app/security/supply_chain_harness.py)
- [`src/app/tasks/swarm_tasks.py`](c:/AI/ShopSquire/src/app/tasks/swarm_tasks.py)

### Reality check
- Strong simulation and deterministic control checks.
- Not a full external SCA platform replacement by itself.

## 9) Capability Matrix (Working vs Stubbed/Gaps)

| Area | Current status | What works now | Stubbed / needs more work |
|---|---|---|---|
| Parallel agent teams (orchestrator) | Working | Parallel CV/fraud/inventory, DAG option, budget+trace integration | Better tenant-aware adaptive scheduling and backpressure tuning |
| Swarm simulation (supply-chain) | Working | Celery + threaded scenario fanout + job status | Deeper real-world attack corpus and richer adversary mutation engine |
| Red-team swarm endpoint | Working (lightweight) | Async in-process rounds + benchmark summaries | Persistence/distributed job resilience beyond process memory |
| Interleaved thinking (NLP) | Working | Bounded iterations, tool allowlist, policy-denied events | More robust planner quality evaluation and stronger semantic policy checks |
| Interleaved thinking (CV) | Working | Multi-tool CV chain with confidence/budget control | Better dynamic tool planning (currently deterministic sequence) |
| Prompt injection detection | Working (heuristic-first) | Multi-layer regex/pattern detection + tool/policy blocks | Add model-based semantic detector + adversarial eval hardening |
| Email BEC detection | Working | Strong deterministic indicator fusion + OOB enforcement + routing | Improve precision/recall with learned scoring and sender graph depth |
| DMARC ingest & ops | Working | XML/ZIP ingest, summaries, admin endpoint, poller | Better provider format handling (e.g., gz variants), richer trend analytics |
| Supply-chain controls (SBOM/OAuth/signature/SLSA) | Working | Practical control checks and review flags | Stronger cryptographic provenance validation pipeline |
| Agentic RAG | Partial | Guardrailed retrieval over local docs + context injection pattern | Larger corpus, hybrid retrieval/rerank, stronger citation/provenance output |
| Dynamic context injection | Working | Per-request live context and scenario-context injection | Formal context contracts/versioning across all agents |
| Playbook action execution | Partial | Engine, run tracking, idempotency, DLQ, trace events | Several action types are deterministic stubs (not full external integrations) |
| Vision model call in orchestrator | Stubbed | Function exists | `call_vision_model` is explicit placeholder in orchestrator |
| Vector store path | Partial/Scaffold | Interface and fallback behavior exists | Full pgvector-first production retrieval path completion |

## 10) Evidence from Targeted Tests Run
Executed on 2026-02-24:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/security/test_tool_runner_prompt_injection.py tests/security/test_prompt_injection.py tests/api/test_security_supply_chain_and_swarm.py tests/security/test_email_security_p0_p1_p2.py tests/ci/test_dmarc_and_dispatcher_ci.py -q
```

Result: `15 passed`.

This validates the key paths you asked about: prompt injection gating, email BEC/DMARC flows, and swarm/supply-chain security endpoints.

## 11) Practical Interpretation for Your Team
1. ShopSquire is already "agentic" in orchestration and controls, not only in LLM generation.
2. The architecture is intentionally fail-safe: deterministic policy and security gates can override model behavior.
3. The next maturity jump is less about adding new endpoints and more about improving detection quality (semantic/ML), provenance depth, and external integration completeness.
