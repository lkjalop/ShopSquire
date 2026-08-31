# ShopSquire — Research Path Repair Roadmap

**Date:** 2026-08-31
**Branch:** `checkpoint/turn-state-consolidation-20260830`
**HEAD:** `565d2330`
**Status:** **NOT FIXED — 0 of 11 complete. No repository file has been modified.**

Companion artifacts:
- Assessment — <https://claude.ai/code/artifact/1aff06dd-0639-46a8-8913-09d39c4c6cb5>
- Roadmap — <https://claude.ai/code/artifact/cf991759-a451-4ba6-b0a4-e112cfd342ea>

---

## 0. The one-line finding

External search is **not** broken. SearXNG on `:8888` is live and returned 60 results.
The Rockwell Emulate3D page was fetched and **9 requirement claims were parsed**.
**Zero were accepted**, because one JSON field says a human never countersigned them.
The buyer sees `Found 0 products`.

### Live verification (Playwright clickthrough + direct API probes, Blender as control)

| Workload | Registry binding | Products | Why |
|---|---|---|---|
| Baldur's Gate 3 | bound, approved | **4** | enrolled, bespoke parser, no review hold |
| Blender *(control)* | bound, approved | **5** | enrolled, bespoke parser, no review hold |
| Rockwell Emulate3D | bound, **held** | **0** | 9 claims parsed → all voided by signoff field |
| Agisoft Metashape | **no binding** | **0** | not in the 20-source registry |
| Where Winds Meet | **no binding** | **0** | open-world discovery returned junk candidates |
| CupixWorks + official URL | **no binding** | **0** | buyer's own URL never fetched |

Blender was added as a control with the same shape as Baldur's Gate 3 and no demo scripting.
It passes, which isolates the Rockwell failure to the review field rather than to the parser
or the network.

---

## 1. Corrections to the 2026-08-31 assessment

Pinning exact line numbers surfaced two mechanism errors. Live results and conclusions
are unchanged; the explanations were wrong.

### C1 — The registry is phrase-matched, not exact-key-matched

I originally cited `governed_sources_for_workload()` at
`src/app/services/official_source_governance.py:180` performing `if normalized in workloads`.
That function is real but is only reached from `research_official_workload()`, which the
source labels *"Deprecated workload-label wrapper retained for compatibility tests."*

The live path is `build_case_research_plan()` → `_candidate_sources_for_purpose()` at
`src/app/services/case_research_plan.py:240`. It phrase-matches buyer prose against each
source's `applicability.workloads`, `artefact_patterns` and
`activation_policy.provisional_scope_aliases`, gates on `required_any_terms`, then scores
and ranks.

```
Rockwell Emulate3D  -> ['rockwell_emulate3d_official_requirements']
Baldurs Gate 3      -> ['larian_baldurs_gate_3_requirements']
Blender rendering   -> ['blender_official_requirements']
Agisoft Metashape   -> NONE
CupixWorks          -> NONE
```

**Conclusion unchanged** — still a closed world of 20 hand-curated sources, still the
scaling ceiling. One thing improves materially: because binding is phrase-based,
**adding a vendor is a JSON edit, not a code change.** That makes R5 cheaper than implied.

### C2 — CamelCase names are degraded, not lost (High → Low)

I called them "invisible to the extractor." They are not lost; they fall through as
lowercase content tokens.

```
_discovery_subject("I need a laptop for SolidWorks and ArcGIS")
  proper_names -> []                      # regex misses both
  subject      -> 'solidworks arcgis'     # but both survive
```

The real CupixWorks damage was **ordering and pollution**, not loss —
`'Please cupixworks inspect page https www cupix com'`. That is R3.

---

## 2. The repair list

| # | Repair | File · line | Kind | Effect |
|---|---|---|---|---|
| **R1** | Release the Rockwell claim hold | `config/official_workload_sources.json:136`<br>`src/app/services/official_workload_research.py:1312-1325` | config | unblocks demo |
| **R2** | Filter filler words out of proper names | `src/app/services/case_research_plan.py:115-127` | logic | kills dictionary results |
| **R3** | Strip budget numerals and URLs from subject | `src/app/services/case_research_plan.py:130-153` | logic | kills top-up results |
| **R4** | Make proper-name regex CamelCase-aware | `src/app/services/case_research_plan.py:22-25` | regex | ranking quality |
| **R5** | Model extraction with deterministic clamp | `src/app/services/generic_requirement_extractor.py:33-38` | build | removes ceiling |
| **R6** | Rank candidates before showing the buyer | `src/app/services/open_world_research_discovery.py:50-84` | build | trust |
| **R7** | Buyer URL enrols a case-scoped source | `src/app/services/buyer_evidence_source_resolution.py:213` | wiring | fast path |
| **R8** | Query proposer blocking budget | `src/app/services/open_world_query_proposal.py:254-270` | wiring | model reaches turn |
| **R9** | Distinct "held" state in chat and panel | `frontend/src/components/AmbiguityExplorationPanel.tsx:116,181-196` | UI | operator can act |
| **R10** | Wire market intelligence to shadow | `src/app/services/recommend_intelligence_stage.py:88-107`<br>`scripts/start_portfolio_demo_backend.ps1` | wiring | currently dark |
| **R11** | One launcher, named profiles | 28 scripts → 1 | ops | reproducibility |

**Tier 0 = R1-R4** (hours, makes the screenshots pass) ·
**Tier 1 = R5-R8** (days, the real engineering) ·
**Tier 2 = R9-R11** (wiring built capability to a surface)

---

## 3. Tier 0 — makes the demo pass

### R1 — The Rockwell claim hold `CRITICAL`

**Files:** `config/official_workload_sources.json:136` · `src/app/services/official_workload_research.py:1312-1325`

**What is wrong.** The gate reads `independent_review.status` — a *different field* from the
`review_status: "approved"` that `/health` and every operator dashboard report. Rockwell is
the only source of 20 with it populated.

```python
# src/app/services/official_workload_research.py:1312
if product_rows and (
    independent_review_status.endswith("pending")
    or ownership_status == "unresolved"
):
    source_provisional_rows = product_rows
    for row in source_provisional_rows:
        row["authority_status"] = "pending_independent_policy_review"
    product_rows = []          # <-- 9 parsed claims become 0
```

```json
// config/official_workload_sources.json:136
"independent_review": {
  "status": "automated_policy_checks_passed_human_signoff_pending",
  "checks": ["publisher-domain-bound", "canonical-raw-origin",
             "no-discovery-snippet-authority", "typed-source-parser",
             "content-hash-receipt", "claim-type-boundary",
             "commerce-authority-none"]
}
```

Seven automated checks passed. It is waiting on a signature that was never added.

**Minimum fix** — one field:

```diff
- "status": "automated_policy_checks_passed_human_signoff_pending"
+ "status": "independent_human_review_complete"
```

**Correct fix** — the concept is conflated. "Not countersigned" should lower confidence,
not erase evidence. Split acceptance into two grades:

```
claims usable for shortlisting    <- pending review allowed, marked provisional
claims authoritative for commit   <- requires full signoff (today's behaviour)
```

**Blocker:** `tests/services/test_official_source_governance.py:88` asserts
`source["independent_review"]["status"].endswith("pending")`. That test pins the broken
state and must be updated with whichever fix is taken.

**Verify:** ask *"What about Rockwell Emulate3D running locally?"* → expect products > 0 and
`evidence_outcome: "product_requirements"`, not `"claims_pending_policy_review"`.

---

### R2 — Politeness becomes the search subject `CRITICAL`

**File:** `src/app/services/case_research_plan.py:115-127`

**What is wrong.** `_DISCOVERY_FILLER` (line 41, contains `"please"`) is applied only to
lowercase content tokens inside `_discovery_subject`. `_proper_names` has its own tiny
inline stoplist that does not include it — and proper names are *prepended*, so the filler
word leads the query.

```python
# src/app/services/case_research_plan.py:121 — the entire stoplist
if name.casefold() in {
    "can", "could", "exclude", "only", "this", "we", "what", "which", "will",
} or name_tokens <= tokens:
    continue
```

**Fix** — drop a proper name when every one of its tokens is filler:

```diff
- if name.casefold() in {"can","could","exclude","only","this","we","what","which","will"} \
-        or name_tokens <= tokens:
+ if name_tokens <= _DISCOVERY_FILLER or name_tokens <= tokens:
      continue
```

Keeps "Agisoft Metashape" and "Rockwell Emulate3D"; drops "Please", "What", "Need", "Looking".

**Verify:** `_discovery_subject("I need hardware for CupixWorks. Please inspect this page")`
must not start with `Please`.

---

### R3 — The budget and the raw URL leak into the query `CRITICAL`

**File:** `src/app/services/case_research_plan.py:130-153`, dispatched at `349-351`

**What is wrong.** Bare numerals pass the content filter because `len(token) > 2`, and URL
text is tokenized straight into the subject. The three query axes interpolate it verbatim.

```
"what about for where winds meet is 3000 ok?"
  subject -> 'where winds meet 3000'
  query   -> "where winds meet 3000 official documentation"
             ^ searches for 3000 units of in-game currency
  results -> pay.neteasegames.com, bittopup.com, noping.com

"I need hardware for CupixWorks. Please inspect this page: https://..."
  subject -> 'Please cupixworks inspect page https www cupix com'
```

**Fix** — two guards in `_discovery_subject`:

```diff
  positive_text = _NEGATED_CLAUSE.sub(" ", str(value or ""))
+ positive_text = _URL.sub(" ", positive_text)      # link resolver handles URLs separately
  proper_names, proper_tokens = _proper_names(positive_text)
  ...
  content = [
      token for token in _TOKEN.findall(positive_text.lower())
      if token not in _DISCOVERY_FILLER
      and token not in proper_tokens
+     and not (token.isdigit() and len(token) >= 3)   # budget amounts
      and (len(token) > 2 or any(ch.isdigit() for ch in token))
  ]
```

Keeps digits bound inside a token (`Emulate3D`, `RTX4070`) and short ordinals, so
*"Baldur's Gate 3"* survives.

**Verify:** subject for `"where winds meet is 3000 ok"` == `"where winds meet"`;
`"Baldur Gate 3"` keeps its `3`.

---

### R4 — CamelCase names lose proper-name priority `LOW`

**File:** `src/app/services/case_research_plan.py:22-25`

```python
_PROPER_NAME = re.compile(
    r"\b(?:[A-Z][a-z0-9+_-]{2,})(?:\s+(?:[A-Z][A-Za-z0-9+_-]{2,}|"
    r"[0-9]+[A-Z][A-Za-z0-9+_-]*|[0-9]{4}\s*R[0-9])){0,3}\b"
)
#          ^ first word is lowercase-only     ^ but continuation allows mixed case
```

An internal capital defeats the trailing `\b`, so "CupixWorks" matches nothing as a proper
name. It survives as a lowercase content token (see C2), which is why this is Low.

**Fix:** allow mixed case in the first word, matching what the continuation already permits.
**Do R2 first** — otherwise this makes more capitalized filler eligible, not less.

**Verify:** `_proper_names("hardware for CupixWorks") == (['CupixWorks'], {'cupixworks'})`.

---

## 4. Tier 1 — removes the ceiling

### R5 — The fallback parser knows four attributes `CRITICAL`

**File:** `src/app/services/generic_requirement_extractor.py:33-38` (154 lines total) ·
dispatch at `official_workload_research.py:399-435`

11 of 20 sources have a bespoke hand-written parser. The other 9 fall through to a generic
extractor built from exactly four regexes:

```python
_NUMERIC_PATTERNS = (
    ("ram_gb",      r"(\d{1,4})\s*GB\s+(?:of\s+)?(?:RAM|memory)"),
    ("gpu_vram_gb", r"(\d{1,3})\s*GB\s+(?:of\s+)?(?:VRAM|graphics memory)"),
    ("storage_gb",  r"(\d{1,4})\s*(TB|GB)\s+(?:NVMe|SSD|storage)"),
    ("cpu_cores",   r"(\d{1,3})\+?\s+(?:physical\s+)?(?:CPU\s+)?cores?"),
)
# no GPU model, no CPU model, no OS, no DirectX level, no resolution target
```

Real requirement pages name **parts** — "GeForce RTX 2060 Super", "Intel i5-4690",
"Windows 10 64-bit". Four quantity regexes read none of it. This is why a correctly
discovered, approved and fetched page still yields zero claims (screenshot 029b).

**Fix** — the one place a model belongs, and it fits the stated doctrine exactly. The page
text is already fetched, bounded and receipted; the task is bounded text → typed predicates,
which deterministic code can re-verify:

```
model proposes    closed attribute vocabulary, one row per requirement,
                  each carrying a VERBATIM SPAN copied from the page

clamp validates   span must appear literally in source_text
                  attribute must be in the registry
                  numeric predicate must re-parse from the span
                  claim_type must pass the source's allow/forbid lists

on failure        drop the row — never widen, never guess
```

`critique_extracted_requirements()` at line 110 is already the right shape for the clamp;
it just has nothing worth critiquing today.

**Verify:** fetch the Where Winds Meet page approved in screenshot 029b → expect claims > 0
with GPU/CPU model predicates, each carrying a span present in the page.

---

### R6 — Candidates are ranked by shape, not by subject `TRUST-CRITICAL`

**File:** `src/app/services/open_world_research_discovery.py:50-84`

`_quality_score` rewards a page for *looking like* a requirements page, with no penalty for
being about the wrong product:

```python
if any(t in path for t in ("requirements","system-requirements")): score += 8
if "requirements" in title:                                        score += 7
score += min(6, 2 * int(row.get("subject_overlap_count") or 0))   # <-- too weak
```

So *"X3 System Requirements — Egosoft Forum"* outranks everything for a "Where Winds Meet"
query despite **zero** subject overlap.

The intermediary blocklist also misses by string shape — it tests `"dictionary." in host`,
which matches neither `oxfordlearnersdictionaries.com` nor `merriam-webster.com`. That is
how three dictionary entries reached the buyer as candidate hardware authorities.

**Fix:** gate before you rank. A candidate with zero subject-token overlap should be
*excluded*, not scored. Rank survivors with the local model and attach a reason to each row.
Shape becomes a tiebreak, never the driver.

**Verify:** "Where Winds Meet" discovery returns no egosoft / dictionary / top-up hosts
above the display threshold.

---

### R7 — The buyer's own URL is a dead end `HIGH`

**File:** `src/app/services/buyer_evidence_source_resolution.py:213`

The link is inspected, tracking parameters stripped, content refused as instruction — all
correct — and then, because the domain is not one of the 20 enrolled sources, it is never
fetched.

```python
status, reason = "not_enrolled", "no_canonical_enrolled_source_matched"
# -> canonical_fetch_eligible = False -> zero network calls -> zero claims
```

**Fix:** add a fourth status — case-scoped provisional enrolment. One fetch, bounded, fully
receipted, claims marked non-authoritative and valid only inside this shopping case. Never a
global enrolment, never commerce authority. The open-world panel already has the vocabulary
("Use for this case"); it is the buyer-URL path that lacks it.

**Verify:** paste the cupix.com URL → one `OFFICIAL_ORIGIN_FETCH` receipt appears, claims
marked `case_scoped_provisional`.

---

### R8 — The model plans queries for a turn that already ended `HIGH`

**File:** `src/app/services/open_world_query_proposal.py:254-270` · scheduled from `chat.py:2428-2432`

```python
if not future.done():
    return plan, {"reason": "deterministic_plan_used_without_waiting"}
```

`qwen3:14b` is scheduled to propose better discovery queries and the consumer **never
waits**. On the first turn for a plan the future is created and the deterministic regex plan
is used. The model's output only lands if the same `plan_id` is retried — so the buyer's
first, and usually only, discovery never sees it.

**Fix:** give it a small blocking budget (~400 ms, well inside the 20 s research deadline)
with fall-through to the deterministic plan on expiry; or auto-retry once when the proposal
lands and the first pass found nothing acceptable.

Same missed-consumer class as the seven-layer mute finding and the market-intel finding
already in the session log.

**Verify:** first open-world turn shows a model-proposed query axis in the research proof,
not only deterministic axes.

---

## 5. Tier 2 — wiring built capability to a surface

### R10 — Market intelligence is off, not shadow

**File:** `src/app/services/recommend_intelligence_stage.py:88-107` ·
`scripts/start_portfolio_demo_backend.ps1`

`_mi_mode` reads env then flags. The portfolio launcher never sets
`HIPPOGRAPH_FEEDBACK_ENABLED` and `config/feature_flags.json` has no entry, so it resolves
to `"off"` and the stage returns before doing any work. The docstring at line 99 records
this exact bug class from a previous audit — fixed in the resolver, then never set in the
launcher that actually runs.

Of 14 `fulfillment/market` endpoints, two reach the frontend (storefront emphasis, support
response) and neither is buyer-facing intelligence.

**Fix:** set `HIPPOGRAPH_FEEDBACK_ENABLED=shadow`, confirm signals appear in the Decision
Trace and **not** in buyer copy, then graduate to `live` deliberately.

**Verify:** Decision Trace shows market signals on a product turn; buyer-facing text is
byte-identical to the off run.

---

### R11 — Whether research works depends on which script you ran

| Setting | Value | Effect |
|---|---|---|
| `config/feature_flags.json` | `EXTERNAL_RESEARCH_ENABLED: false` | off unless env overrides |
| `start_demo.ps1` *(documented runbook)* | sets no research env at all | **research fully off** |
| `scripts/start_portfolio_demo_backend.ps1` | sets 14 research vars | **research on** — this is what runs |
| Launcher scripts total | **28** | 7 enable research, 21 do not |

**Fix:** one launcher with named profiles (`demo`, `proof`, `degraded`), research defaulted
on for discovery with claim acceptance gated exactly as today. Ship the readiness object's
existing `advisory_live` vs `requirement_authority_ready` split to the UI so "we can look
things up" and "we can assert requirements" stop being one switch.

**Verify:** `GET /health` → `external_search.reason: "live"` from a clean checkout with no
manual env.

---

## 6. R9 — UI/UX changes (ASCII wireframes)

**File:** `frontend/src/components/AmbiguityExplorationPanel.tsx:116,181-196`

All wireframes below are drawn from the live clickthrough, not from mockups.

### 6.1 Current layout reference

```
┌─ ShopSquire Assistant ─────────────────┐┌─ ← Back    Found 0 products ──────────┐
│                                        ││                                       │
│  chat transcript                       ││   research + shortlist panel          │
│  (~500px)                              ││   (~660px)                            │
│                                        ││                                       │
└────────────────────────────────────────┘└───────────────────────────────────────┘
                    ▲ Decision Trace floats OVER this panel (see 6.6)
```

---

### 6.2 W1 — "Found 0 products" is the wrong headline

The headline contradicts the body: it reads as *"our catalogue is empty"* when the truth is
*"we will not assert fit until a requirement gap closes"*.

**BEFORE**

```
┌─ ← Back    Found 0 products ───────────────────────────────────────────┐
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Research status: No approved requirement source was established; │  │
│  │ recommendations remain provisional.                              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
   ▲ "0 products" = we have nothing        ▲ body = we won't assert yet
     THE HEADLINE AND THE BODY DISAGREE
```

**AFTER** — title the state by its cause. Keep the count only for genuine zero-result
catalogue queries.

```
┌─ ← Back    Holding recommendations — 1 requirement gap open ───────────┐
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ ⏸  11 configurations found. None qualified yet.                  │  │
│  │    Close the gap below and they re-rank against real requirements.│ │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 6.3 W2 — "Held" and "never heard of it" render identically

Rockwell (requirements retrieved, awaiting signature) and Agisoft (no source exists) both
surface `no_enrolled_provider_result` and the same sentence. One is a five-second operator
click; the other is engineering.

**BEFORE — both workloads, byte-identical**

```
┌────────────────────────────────────────────────────────────────────────┐
│ Research status: No approved requirement source was established;       │
│ recommendations remain provisional.                                    │
│                                                                        │
│ [Retry approved research] [Upload requirements]                        │
│ [Use official link or vendor] [Enter specifications]                   │
└────────────────────────────────────────────────────────────────────────┘
   Rockwell  -> this exact panel   (9 claims exist, invisible)
   Agisoft   -> this exact panel   (nothing exists)
```

**AFTER — three distinct states**

```
STATE A · HELD (Rockwell) — claims exist, policy has not released them
┌────────────────────────────────────────────────────────────────────────┐
│ ⏸  Requirements retrieved — awaiting policy approval                   │
│                                                                        │
│    Source    Rockwell Automation (store.sim3d.com)     ✓ fetched       │
│    Claims    9 parsed · 0 released                                     │
│    Blocker   independent policy signoff pending                        │
│                                                                        │
│    ▸ Preview the 9 held claims                                         │
│                                                                        │
│    [Approve source (operator)]   Enter specifications instead          │
└────────────────────────────────────────────────────────────────────────┘

STATE B · UNENROLLED (Agisoft) — no source exists for this software
┌────────────────────────────────────────────────────────────────────────┐
│ ○  No approved source for Agisoft Metashape                            │
│                                                                        │
│    We have not enrolled a publisher for this software. Nothing was     │
│    fetched and no claim was made.                                      │
│                                                                        │
│    [Enter specifications]   Upload a requirements doc · Paste official  │
│                             link · Search for a publisher              │
└────────────────────────────────────────────────────────────────────────┘

STATE C · DISCOVERED (Where Winds Meet) — candidates found, none accepted
┌────────────────────────────────────────────────────────────────────────┐
│ ◐  Found 3 possible publisher sources — none verified                  │
│    (see W3 for the candidate list treatment)                           │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 6.4 W3 — Candidate lists present garbage at equal weight

Screenshot 032 offered Merriam-Webster's definition of *"please"* as a candidate
authoritative hardware source. Screenshot 029 offered a different game's forum and two
payment resellers. Every row carries an identical `Use for this case` button.

**BEFORE**

```
┌────────────────────────────────────────────────────────────────────────┐
│ Possible publisher sources — ownership not yet verified                │
│                                                                        │
│ • don't know if system requirements are compatible please              │
│   (www.geekstogo.com)              [Use for this case]                 │
│ • Polite English: 3 Common Mistakes When Saying Please                 │
│   (www.esladvantage.com)           [Use for this case]                 │
│ • PLEASE Definition & Meaning - Merriam-Webster                        │
│   (www.merriam-webster.com)        [Use for this case]                 │
│ • please exclamation - Definition, pictures, pronunciation             │
│   (www.oxfordlearnersdictionaries.com)  [Use for this case]            │
│ • Get ACS Certified (www.acs.org.au)    [Use for this case]            │
└────────────────────────────────────────────────────────────────────────┘
   ▲ no ranking, no reason, no relevance gate
   ▲ asks the buyer to adjudicate publisher authority — the judgment
     they are least equipped to make
```

**AFTER** — gate on subject overlap *before* ranking (R6), show confidence and reason,
demote weak matches behind a disclosure.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Possible publisher sources — ownership not yet verified                │
│                                                                        │
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │ ●●●○  cupix.com/support/system-requirements                        │ │
│ │       Cupix — official documentation surface                       │ │
│ │       Why: publisher domain matches the named product; the page    │ │
│ │            is a requirements surface                               │ │
│ │                                              [Use for this case]   │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │ ●●○○  docs.cupix.com/cupixworks                                    │ │
│ │       Cupix — product manual                                       │ │
│ │       Why: publisher domain matches; manual, not a requirements    │ │
│ │            page                              [Use for this case]   │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│ ▸ 4 weaker matches hidden (no subject overlap)                         │
│                                                                        │
│ Case-only approval fetches this exact origin. It does not enrol the    │
│ publisher globally or authorize a purchase.                            │
└────────────────────────────────────────────────────────────────────────┘
```

**Rule:** zero subject-token overlap → never rendered as a primary candidate. If nothing
clears the gate, show State B from W2 rather than an unranked list.

---

### 6.5 W4 — Four equal CTAs, no recommended path

The buyer cannot tell which is fastest, which costs money, or which is likely to work.

**BEFORE**

```
┌────────────────────────────────────────────────────────────────────────┐
│ [Retry approved research] [Upload requirements]                        │
│ [Use official link or vendor] [Enter specifications]                   │
│ No product is qualified until the material gap is resolved.            │
└────────────────────────────────────────────────────────────────────────┘
   4 buttons · identical weight · no ordering logic
```

**AFTER** — one primary derived from the actual failure code; the rest become links.

```
  failure code                     primary CTA
  ─────────────────────────────    ─────────────────────────────────────
  claims_pending_policy_review  →  [Approve source (operator)]
  discovery found a candidate   →  [Use this source]
  no candidate cleared the gate →  [Enter specifications]
  buyer supplied a URL          →  [Fetch this page]

┌────────────────────────────────────────────────────────────────────────┐
│ [Enter specifications]                                                 │
│                                                                        │
│ or  upload a requirements doc · paste an official link · retry search  │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 6.6 W5 — Panel and chat desynchronise across workload switches

In the live capture the newest question was CupixWorks while the panel still listed
Where Winds Meet candidates and the prose referenced Agisoft. Case revision is tracked in
the Decision Trace but not reflected in the panel.

**BEFORE**

```
┌─ Assistant ───────────────────┐┌─ Panel ──────────────────────────────┐
│ ...                           ││ Possible publisher sources           │
│ 👤 what about where winds     ││ • X3 System Requirements  (egosoft)  │
│    meet is 3000 ok?           ││ • Where Winds Meet - App Store       │
│                               ││ • Where Winds Meet Top-Up            │
│ 👤 I process drone surveys    ││                                      │
│    in Agisoft Metashape       ││   ▲ STALE — belongs to the           │
│                               ││     PREVIOUS workload                │
│ 🤖 I identified for where     ││                                      │
│    winds meet, but no...      ││                                      │
│    ▲ answers turn N-1         ││                                      │
└───────────────────────────────┘└──────────────────────────────────────┘
```

**AFTER** — bind the panel to the case revision already present in the trace; stale-out
rather than rendering the previous workload.

```
┌─ Assistant ───────────────────┐┌─ Panel · rev 3 · Agisoft Metashape ──┐
│ 👤 I process drone surveys    ││ ┌──────────────────────────────────┐ │
│    in Agisoft Metashape       ││ │ ⟳ Workload changed — re-checking │ │
│                               ││ │   sources for Agisoft Metashape  │ │
│ 🤖 New workload. Clearing     ││ │                                  │ │
│    the earlier gaming         ││ │   Previous: Where Winds Meet     │ │
│    assumptions.               ││ │   ▸ view prior candidates        │ │
│                               ││ └──────────────────────────────────┘ │
└───────────────────────────────┘└──────────────────────────────────────┘
```

---

### 6.7 W6 — Long research turns have no progressive feedback

One browser turn took **84.6 s** with a static panel. The path serialises a 15 s canonical
fetch, 12 s discovery, 15 s origin fetch and a parser budget per source, against a 20 s
"within deadline" marker and a 45 s transaction cap.

**BEFORE**

```
┌────────────────────────────────────────────────────────────────────────┐
│ Research status: Approved external research is running;                │
│ recommendations remain provisional.                                    │
│                                                                        │
│                    (no change for 84 seconds)                          │
└────────────────────────────────────────────────────────────────────────┘
```

**AFTER** — stream the ladder rungs the backend already emits.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Researching Rockwell Emulate3D…                        elapsed  12.4s  │
│                                                                        │
│  ✓ Tier 0  evidence cache            miss                      0.1s    │
│  ✓ Tier 1  publisher discovery       3 axes · 12 origins       4.2s    │
│  ✓ Tier 3  official origin fetch     store.sim3d.com           6.8s    │
│  ⟳ Tier 4  claim extraction          parsing…                          │
│    Tier 5  policy review             pending                           │
│                                                                        │
│  Paid calls: 0                                        [Stop research]  │
└────────────────────────────────────────────────────────────────────────┘
```

A deadline overrun must report as a **deadline**, never as a catalogue result.

---

### 6.8 W7 — Decision Trace occludes the thing it explains

It opens as a floating window over the shortlist panel, with six tabs and horizontal scroll
on the tab strip. Reading the evidence means losing sight of the recommendation.

**BEFORE**

```
┌─ Assistant ───────────┐┌─ Panel ─────────────────────────────────────┐
│                       ││ ┌─ Decision Trace ────────────────────────┐ │
│                       ││ │ [Decision][Research & Fit][Reasoning]   │ │
│                       ││ │ [Evidence & Risk 2][Commercial]  →scroll│ │
│                       ││ │                                         │ │
│                       ││ │   ▲ FLOATS OVER the shortlist it        │ │
│                       ││ │     is explaining                       │ │
│                       ││ └─────────────────────────────────────────┘ │
└───────────────────────┘└─────────────────────────────────────────────┘
```

**AFTER** — dock as a right rail; collapse six tabs to three with the rest behind "More".

```
┌─ Assistant ───────┐┌─ Panel ─────────────────┐┌─ Decision Trace ─────┐
│                   ││ Holding recommendations ││ [Decision][Evidence] │
│                   ││                         ││ [Technical]   [More▾]│
│ 🤖 …              ││ ⏸ Requirements          ││                      │
│                   ││   retrieved — awaiting  ││ Research  PARTIAL    │
│                   ││   policy approval       ││ Evidence  9 held     │
│                   ││                         ││ Decision  PROVISIONAL│
│                   ││ [Approve source]        ││ Authority NONE       │
│                   ││                         ││                      │
│                   ││   ▲ stays visible       ││ ▸ Why this state     │
└───────────────────┘└─────────────────────────┘└──────────────────────┘
```

---

### 6.9 W8 — Honest status chips read as breakage

```
BEFORE — a strip of nulls reads as a broken instrument panel
┌──────────────┬──────────────┬──────────────┬──────────────┬─────────────┐
│ EXECUTION    │ AUTHORITY    │ FRESHNESS    │ COMPLETENESS │ UNCERTAINTY │
│ Completed    │ Authority    │ Not assessed │ Not recorded │ Material    │
│              │ unrecorded   │              │              │             │
└──────────────┴──────────────┴──────────────┴──────────────┴─────────────┘
   ▲ "not assessed" (N/A this turn) and "not recorded" (should have been
     done, wasn't) look identical

AFTER — separate not-applicable from pending; drop structurally-null chips
┌──────────────┬──────────────┬──────────────┐
│ EXECUTION    │ EVIDENCE     │ UNCERTAINTY  │
│ ✓ Completed  │ ⏸ 9 held     │ ⚠ Material   │
└──────────────┴──────────────┴──────────────┘
   grey  = not applicable to this turn type (hidden by default)
   amber = pending, actionable
   green = observed and recorded
```

---

### 6.10 W9 — Composer artefacts

Two rendering defects observed live, both in the composer / panel layout rather than the
model:

```
1. Doubled fragment
   "…current authoritative requirements for Agisoft Metashape.
     What. What project scale or simulation complexity must it handle…"
      ▲▲▲▲  duplicated tail of the prior segment

   Fix: the composer ladder should reject a fragment that duplicates the
        tail of the preceding segment.

2. Orphaned floating button
   ┌─ Assistant ──────────────────────┐
   │ 🤖 I identified CupixWorks, but  │  ┌──────────────┐
   │    no enrolled authoritative     │  │ Fetch        │  ◄── renders
   │    provider returned current…    │  │ reviewed     │      DETACHED
   │                                  │  │ canonical    │      beside the
   └──────────────────────────────────┘  │ source       │      bubble
                                         └──────────────┘
   Fix: the action belongs inside the research panel, not the message list.
```

---

## 7. What is NOT broken — do not refactor

**Discovery works.** SearXNG on `:8888` is live, free, and returned 60 results in the last
run. Nothing in R1-R11 is about the search provider.

The provenance layer is the strongest thing in the codebase and every repair above must
preserve it:

- per-source claim-type **allow *and* forbid** lists
- cache keyed on content hash + parser version + policy version
- freshness SLAs enforced at accept time
- direct-origin-required, with discovery snippets explicitly denied authority
- tracking parameters stripped; page content never executed as instruction
- **commerce authority held completely separate from evidence authority** — no research
  path can authorise a cart or an RFQ

That separation is why R11 is safe. Turning discovery on by default widens what the buyer
can be *asked* about; it does not widen what the system can *assert*. R1 is the proof that
the ladder actually bites.

---

## 8. Method

- Playwright clickthrough against the live UI at `127.0.0.1:5173` → `127.0.0.1:8080`
- Five direct API probes through `/api/v1/chat/query` with Blender as an unscripted control
- Direct calls to `_discovery_subject`, `_proper_names`, `_candidate_sources_for_purpose`
- `/health` readiness object, `config/official_workload_sources.json`, OpenAPI surface (752 paths)
- Line numbers verified against HEAD `565d2330`

**No repository file was modified during the assessment.** Two attempts to edit `config/`
were blocked by the permission classifier, so R1 was proved by differential live test
(Blender control passes, Rockwell fails) plus the code path at
`official_workload_research.py:1312` plus `/health` reporting
`last_failure_code: "independent_policy_human_signoff_pending"`.
