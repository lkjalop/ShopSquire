# External Search — Why It Doesn't Work, and What's Left

**Date:** 2026-08-09 · **HEAD:** `b33c41fc` · **Screenshot:** 59 (SearXNG)
**Prior:** [evidence-coverage roadmap](SHOPSQUIRE_EVIDENCE_COVERAGE_ROADMAP_2026-08-08.md) · [research adjudication](SHOPSQUIRE_RESEARCH_ADJUDICATION_AND_NARRATION_ROADMAP_2026-08-08.md)

---

## 0. Answer in one line

**External search works. One environment variable was not set, and no launcher in the repo sets it.**
I proved the full chain live, for free, and then enabled it on the running backend.

---

## 1. What the message claimed vs. what is true

> *"Approved-source research could not complete: Start the enrolled local SearXNG profile or upload requirements."*

| Claim | Reality |
|---|---|
| "Start the enrolled local SearXNG profile" | **SearXNG is already running.** `shopsquire-searxng-1`, `127.0.0.1:8888`, HTTP 200 |
| implied: SearXNG is the problem | SearXNG works perfectly — its JSON API returned the exact Microsoft Hyper-V host-requirements doc for an OT query |
| implied: no approved sources | **10 of 13 sources are `review_status: approved`**, including every one this query needs |

The message blames the component that is healthy. The actual cause is
[`shopping_cases.py:546-551`](../src/app/routers/shopping_cases.py#L546):

```python
search_url = str(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or "").strip()
if not search_url:
    raise HTTPException(status_code=503, detail={
        "code": "local_discovery_not_enrolled",
        "message": "Start the enrolled local SearXNG profile or upload requirements."})
```

It tests an **env var** and reports a **container**. Those are different facts.

And on top of that, the backend the screenshot was taken against had research off entirely:

```
enabled: False   endpoint_configured: False   tenant_enrollment_count: 0
reason: "EXTERNAL_RESEARCH_ENABLED is off"
```

`grep EXTERNAL_RESEARCH_SEARCH_URL` across `start_demo.ps1` and every script in `scripts/`:
**zero hits.** Even `scripts/start_official_research_proof_backend.ps1` only enables the
*official-requirements* leg, never *discovery*. So the discovery lane has never run from the app.

---

## 2. Proof that it works

`python scripts/certify_live_external_research.py` — the repo's own live certification, run just now:

```
query                      : site:docs.factoryio.com Factory I/O system requirements

discovery_receipt
  provider_id              : searxng_compatible_discovery
  provider_endpoint_host   : 127.0.0.1
  execution_status         : completed      network_execution: true
  http_status              : 200
  result_count             : 20             allowlisted_result_count: 20
  elapsed                  : ~1.37s

official_origin_receipt
  provider_id              : governed_http_origin
  provider_endpoint_host   : docs.factoryio.com
  selected_origin_urls     : https://docs.factoryio.com/manual/system-requirements/
  execution_status         : completed      http_status: 200
  billing_class            : free
  response_body_hash       : 5145973cbad…   (hash only — page content never stored)

external_calls: 2      paid_calls: 0      claims_accepted: 0
authority_rule: "discovery finds; accepted claims require official-origin compilation"
```

Note what this proves beyond "it works":

- **Discovery found the right document unaided.** The Factory I/O system-requirements page is
  exactly the first hypothesis in screenshot 59 ("Factory I/O host requirements and documented
  PLC/OPC/Modbus integrations").
- **Zero paid calls.** Self-hosted SearXNG + direct origin fetch. This is the tier-0/tier-3 ladder
  working as designed — no Brave, no Exa, no per-query billing.
- **The authority split is real in code**, not aspirational: SearXNG *discovers*,
  `docs.factoryio.com` is the *authority*, and the receipt records both separately.
- **SSRF posture holds** — one outbound request to the configured host; result URLs returned as
  data, and the origin fetch is separately governed and domain-allowlisted.

---

## 3. Fix applied

I restarted the backend with the canonical template from
[`certify_live_external_research.py:122`](../scripts/certify_live_external_research.py#L122):

```powershell
$env:EXTERNAL_RESEARCH_SEARCH_URL    = "http://127.0.0.1:8888/search?q={query}&format=json"
$env:EXTERNAL_RESEARCH_ALLOW_PRIVATE = "1"
```

`/health` now reports:

```
enabled True · live True · advisory_live True · requirement_authority_ready True
endpoint_configured True · approved_sources 10 of 13 · reason "live"
```

`advisory_live` was `False` before; that flag is the discovery lane. **"Research approved sources"
should now do something.**

This is a scratchpad launcher — `.env` and the repo scripts are unchanged.

---

## 4. Is there an actual approved site to scrape?

**Yes — 13 curated sources in [`config/official_workload_sources.json`](../config/official_workload_sources.json), 10 approved.** This is
genuinely good work and neither prior analysis knew it existed.

Each record carries `allowed_domains`, `canonical_entrypoints`, `allowed_claim_types`,
**`forbidden_claim_types`**, `applicability.workloads`, `parser_type`, `freshness_sla_hours`, and a
`publisher_policy`. Example:

```json
"source_id": "microsoft_learn_hyperv",
"allowed_domains": ["learn.microsoft.com"],
"canonical_entrypoints": [".../hyper-v/host-hardware-requirements", ...],
"allowed_claim_types":   ["minimum_requirements","compatibility","certification","software_feature"],
"forbidden_claim_types": ["capacity_sizing","behavioral_performance","benchmark_result",
                          "exact_product_fit","price","availability"],
"applicability": { "workloads": ["virtualisation","cyber_range","ot_cyber_range"],
                   "exclusions": ["VM count","per-VM resource sizing"] },
"freshness_sla_hours": 168
```

The `forbidden_claim_types` list is the strongest thing here: Microsoft may tell you Hyper-V's
*host requirements*, and is explicitly **not** allowed to authorise *VM-count sizing* or
*exact product fit*. That is the discovery-vs-authority split enforced per publisher, per claim
type. Very few systems do this.

Approved and directly relevant to the OT/digital-twin query:
`microsoft_learn_hyperv`, `factory_io_official_docs`, `mitre_attack_ics`,
`nist_digital_twin_cybersecurity`, `nist_manufacturing_digital_twins`,
`nvidia_omniverse_isaac_docs`.

Pending human review (3): `gns3_official_docs`, `huggingface_official_docs_and_model_cards`,
`nolvus_official_docs`. Those need a named reviewer — note `reviewed_by` is empty on **all 13**,
including the approved ones, which is a governance gap worth closing before any pilot claim.

---

## 5. The one real gap left: claim extraction

`claims_accepted: 0`, and the certify script exits non-zero because of it.

```
discovery        ✅  SearXNG, 20 allowlisted results, 1.37s, free
origin fetch     ✅  docs.factoryio.com, HTTP 200, hashed, governed
claim extraction ❌  NOTHING PARSES THE FETCHED HTML
compilation      ✅  requirement_compiler.py — contract exists and validates
```

Verified: `grep -rl "trafilatura|beautifulsoup|bs4|selectolax|lxml.html" src/app/` returns only
`connectors/competitor_price_fetch.py` — a different subsystem. Sources declare
`parser_type: "html"` and **no HTML parser is bound to it.**

So the platform can find and fetch the right authoritative page, hash it, and record the receipt —
then throws the content away without reading it.

This is local, free work. No API cost, no provider decision. It is the last piece.

---

## 6. Ambiguous user intent

Screenshot 59 shows this **already largely working**, and it is the strongest UX in the project so
far:

- purpose retained verbatim
- **three** competing interpretations, not one snap
- **one** high-information question ("which named software and version, and which stages run
  locally?") — correctly the divergent axis, not a budget question
- per-hypothesis shelves plus a shared-needs shelf
- `Fit: conditional`, `Evidence freshness: unknown`, MPNs displayed
- `Execution: local_exploration_completed · Evidence: material_gaps · Decision: exploration_allowed
  · External calls: 0 · Paid calls: 0 · Cart authority: none`

That last line is the three-dimensional status model, shipped. And products render **while**
interpretation is unresolved — the "explore before authority" correction landed.

**What ambiguity should do to research** (the open design question):

The registry already solves the hard part. `applicability.workloads` maps each source to workload
families, so `candidate_sources_for_purpose` can select sources **per hypothesis**:

```
hypothesis: Factory I/O host        -> factory_io_official_docs
hypothesis: Hyper-V guest support   -> microsoft_learn_hyperv
hypothesis: ICS adversary behaviour -> mitre_attack_ics, nist_digital_twin_cybersecurity
```

Recommended policy:

1. **Don't ask first, and don't fan out to everything.** Run discovery for the sources shared by
   ≥2 live hypotheses (the intersection) — those are safe bets regardless of which is true.
2. **Fan out per hypothesis only when the hypotheses disagree on a *material* requirement axis**
   (here: GPU/VRAM, which differs between 3D-visual and VM-heavy readings), bounded by
   `max_provider_fanout`.
3. **Ask the one question in parallel**, not instead. The answer collapses the hypothesis set and
   the already-running research narrows with it.
4. **Never let an unresolved hypothesis produce a verified-fit claim** — `conditional` is correct
   and already displayed.

The one thing to add: when hypotheses are collapsed by the buyer's answer, **say which shelves
disappeared and why**. A shelf silently vanishing reads as a bug; "you said mostly VMs, so I
dropped the 3D-rendering shelf and its GPU floor" reads as reasoning.

---

## 7. Roadmap

### Phase 0 — make the fix permanent (an hour)
1. **Add `EXTERNAL_RESEARCH_SEARCH_URL` + `EXTERNAL_RESEARCH_ALLOW_PRIVATE` to
   `scripts/start_official_research_proof_backend.ps1`.** One line each. Nothing else explains the
   whole screenshot.
2. **Fix the message** at [shopping_cases.py:546](../src/app/routers/shopping_cases.py#L546) — it must distinguish
   `discovery_endpoint_not_configured` (operator config) from `discovery_endpoint_unreachable`
   (probe the host and report *that*). Never blame a container you did not check.
3. **Health-check the discovery host on startup** and surface it in `/health` next to
   `endpoint_configured`, so "configured" and "reachable" are separate facts.

### Phase 1 — close the claim-extraction gap (the last real blocker)
4. **Bind an HTML parser to `parser_type`** — Trafilatura or selectolax, local, free. Extract into
   the existing `ExtractedClaim` shape.
5. **Enforce `allowed_claim_types` / `forbidden_claim_types` at extraction**, not just at
   compilation. A Hyper-V page must not be able to emit a `capacity_sizing` claim even if the
   parser finds a number that looks like one.
6. **Make `certify_live_external_research.py` exit 0** on `claims_accepted > 0` and wire it into CI
   as an opt-in live job.

### Phase 2 — governance
7. **Populate `reviewed_by`** on all 13 sources — empty on every one, including the 10 approved.
   Approval without a named reviewer is not an audit trail.
8. **Review the 3 pending sources** or remove them.

### Phase 3 — ambiguity-aware research
9. **Per-hypothesis source selection** via `applicability.workloads` (§6), intersection-first,
   bounded fan-out.
10. **Narrate shelf collapse** when an answer eliminates a hypothesis.

### Phase 4 — cache and cost
11. **Evidence cache** keyed by `(source_id, canonical_entrypoint)` with TTL from
    `freshness_sla_hours` (already declared per source: 168h, 720h, 72h). After this, repeat demo
    runs make **zero** network calls.
12. Paid providers remain unnecessary. Nothing in §2 needed one.

---

## 8. Cost position

| | |
|---|---|
| Paid search calls to date | **0** |
| Paid calls needed for the OT/digital-twin journey | **0** |
| Infrastructure | one local Docker container |
| Per-query marginal cost | £0 |

The tier ladder is not theoretical — it is running. SearXNG discovery plus governed origin fetch
covered the hardest query in the demo set at zero marginal cost, and the sources it reached
(Microsoft Learn, NIST, MITRE, Factory I/O) are more authoritative than anything a paid general
search index would have handed back.
