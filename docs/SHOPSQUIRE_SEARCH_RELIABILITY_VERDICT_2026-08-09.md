# External Search — Independent Recheck and Reliability Verdict

**Date:** 2026-08-09 · **HEAD:** `11935b34` · **Re-verifying:** screenshot 59 + the delta report
**Prior:** [external search diagnosis](SHOPSQUIRE_EXTERNAL_SEARCH_DIAGNOSIS_2026-08-09.md)

---

## 1. Screenshot 59: fixed

`EXTERNAL_RESEARCH_SEARCH_URL` is now set on the running backend.

```
enabled True · live True · advisory_live True · endpoint_configured True
reason "live" · approved_sources 10 of 13
```

`advisory_live` was `False`; it is the discovery lane, and it is now on. The 503
`local_discovery_not_enrolled` at [shopping_cases.py:546](../src/app/routers/shopping_cases.py#L546) can no longer fire. **The specific
defect in screenshot 59 is closed.**

---

## 2. The report is honest — verified independently

Every structural claim checks out:

| Claim | Verified |
|---|---|
| 7 commits `ce4eef09`…`11935b34` | ✅ all present, 09:00–09:16 today |
| Backend PID 55252 on :8080 | ✅ |
| Listeners 5173 / 8080 / 8091 / 8888 / 8099 | ✅ all five |
| Migration head `20260861_case_fulfillment` | ✅ exists |
| 205 dirty worktree entries | ✅ exactly 205 |
| Six ambiguous journeys | ✅ specs exist |
| `novel_required` is the strict default | ✅ `certify_live_external_research.py:232` |

And on my **first** independent run of the stricter certification, the numbers reproduced exactly:

```
accepted_official claims : 8
external_calls           : 6
discovery_calls          : 3
paid_calls               : 0
```

The report did not overstate. That is worth saying plainly — this is the first delta report in this
series where the claims survived independent checking without correction.

---

## 3. But the green is not reproducible, and the cause is not your code

I ran the same certification again minutes later:

```
certification_status : failed
gate_failures        : required_novel_discovery_returned_no_allowlisted_results
                       official_origin_unreachable_or_not_network_executed
                       zero_or_insufficient_expected_scoped_claims: 0 < 1
provider_accounting  : discovery_calls 3 · official_origin_fetches 0 · paid_calls 0
unresolved           : microsoft_learn_hyperv   official_origin_not_discovered
                       mitre_attack_ics         official_origin_not_discovered
                       factory_io_official_docs official_origin_not_discovered
```

All three discovery calls dispatched. All three returned **zero allowlisted results**, so no origin
fetch ever happened. Confirmed straight at SearXNG:

```
site:learn.microsoft.com Hyper-V host hardware requirements  ->  0 results, 4 unresponsive engines
site:docs.factoryio.com Factory I/O system requirements      ->  0 results, 5 unresponsive engines
site:attack.mitre.org ICS matrix                             ->  0 results, 5 unresponsive engines
```

Earlier today the same query returned 20 allowlisted results. The report itself observed the onset
("Brave was rate-limited and Startpage hit a CAPTCHA"), but read it as an incidental note rather
than the headline.

**It is the headline.** SearXNG has no index of its own — it proxies Google/Bing/Brave/Startpage/
DuckDuckGo, and those detect and throttle repeated datacenter traffic. Certifying harder makes it
worse. This is a structural property of metasearch, not a defect you can code around.

So the honest status of "Real SearXNG discovery: Green" is: **green when upstream engines answer,
red when they don't, and you do not control which.** A CI gate on this will flake.

---

## 4. The fix is already in your registry

While discovery returned nothing, I fetched the canonical entrypoints directly:

```
learn.microsoft.com/.../hyper-v/host-hardware-requirements   200   55,662 bytes
docs.factoryio.com/manual/system-requirements/               200   72,980 bytes
attack.mitre.org/matrices/ics/                               200  248,140 bytes
```

**All three work right now.** And every one of them is already declared in
[`config/official_workload_sources.json`](../config/official_workload_sources.json) under `canonical_entrypoints`.

Which means: **for the 10 approved sources, discovery is redundant.** The registry already knows
the URL. Sending a search engine to rediscover a page whose address you have written down is
strictly worse — slower, rate-limited, non-deterministic, and it lets a third party choose your
evidence.

### This also dissolves the MITRE precision problem

The report flags that discovery picked `attack.mitre.org/analytics/` instead of the ICS matrix, and
proposes a path/canonical-family policy layer. That layer is right for novel sources — but for an
**enrolled** source the problem simply does not arise: fetch `/matrices/ics/` because the registry
says so. You never let a search engine choose the page for a source you have already curated.

### Corrected execution order

```
enrolled source?
   ├─ YES → canonical_entrypoint → origin fetch → parser → typed claim      [deterministic]
   │         (cache by (source_id, entrypoint), TTL = freshness_sla_hours)
   └─ NO  → discovery → domain allowlist → PATH/CANONICAL-FAMILY policy
             → semantic applicability → parser → typed claim                 [best-effort]
```

`novel_required` mode is then exactly what its name says: a test of the *novel-source* path, run
deliberately and allowed to be flaky. It should not be the default gate for enrolled sources, and
it should not be what CI blocks on.

---

## 5. One live-runtime discrepancy

The backend on PID 55252 is running in a **degraded profile**:

```
profile: standard        (expected demo_v2)
recommendation_core: off (expected primary)
requirement_authority_ready: False
```

It was started without `start_demo.ps1`, so `SHOPSQUIRE_RUNTIME_PROFILE`, `RECOMMEND_CORE_MODE`,
`MULTI_INTENT_PLANNER_ENABLED` and the three authority gates from `84c33f27` are all unset.
Discovery works (that env did get set), but the V2 core is not serving and official-requirements
claims cannot authorise.

Your next clickthrough will not match what the certification exercised. Relaunch via
`scripts/start_official_research_proof_backend.ps1` (plus the two discovery vars) before testing.

---

## 6. What to do with the rest of the report

### Agree, unchanged

Upload corroboration UX (PDF/TXT + inline correction), supplier continuation UI, exact-product
evidence depth, narration evaluation before any canary, and keeping rich narration shadow-only.
All correctly sequenced. The refusal to bulk-stage 205 dirty entries without approval is the right
call — don't let anyone talk you out of it.

### Change

1. **Reorder item 1.** "Research-origin precision" should become **"canonical-first execution"**:
   canonical entrypoint for enrolled sources; path policy only on the novel path. This converts the
   flakiest component into a deterministic one and fixes MITRE as a side effect.
2. **Promote the evidence cache from Phase 4 to now.** Keyed `(source_id, canonical_entrypoint)`,
   TTL from the per-source `freshness_sla_hours` already declared (168h / 720h / 72h). After it,
   repeat demo runs make **zero** network calls and cannot be throttled at all. This is the single
   highest-value reliability item and it is also the cheapest.
3. **Split the CI gate.** `canonical_allowed` mode = blocking. `novel_required` = opt-in, non-blocking,
   and allowed to fail on upstream throttling. Otherwise your pipeline goes red for reasons no one
   can fix.
4. **Fix `reviewed_by`** — still empty on all 13 sources including the 10 approved. Approval without
   a named reviewer is not an audit trail, and it is a prerequisite for the production-enrollment
   item already on the list.
5. **Add discovery/origin receipts to Decision Trace** — already on the list at item 1, keep it, but
   make sure it renders `cache_hit` distinctly from `network_execution`. Once the cache lands, most
   runs should legitimately show zero external calls, and that must not read as "didn't research".

### Answering the open questions

- **Fixture vs real enrolled suppliers:** stay fixture-only until the supplier continuation UI is
  browser-certified. The backend refuses silent substitution and uses revision checks — good — but
  nothing buyer-visible confirms an offer yet. Real suppliers behind an unfinished UI is the one
  place a mistake becomes an outbound email.
- **Dirty worktree:** don't archive anything on my read either. Ask for a per-directory decision,
  not a blanket one.
- **Relevance labels:** 43 candidates × 8 slates is the last genuinely blocking external item. It
  gates the human relevance seal, which gates the pilot. Worth scheduling before the UX work, since
  it's calendar time you can run in parallel.

---

## 7. Bottom line

Screenshot 59 is fixed. The implementation is real, and the report is accurate.

The remaining problem is not correctness — it is that you built a reliable evidence pipeline on top
of an unreliable discovery mechanism, when the registry already contains the addresses that make
discovery unnecessary for every source you have approved.
