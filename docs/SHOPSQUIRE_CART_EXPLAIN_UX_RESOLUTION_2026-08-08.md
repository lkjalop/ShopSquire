# ShopSquire cart/explain UX resolution and release-gate assessment

Date: 2026-08-08 (Australia/Sydney)

## Executive verdict

The four screenshot failures are addressed in the current worktree and covered by backend and
frontend regressions. The release is **not** ready for removal of the deprecated V2 compatibility
endpoint: human relevance review, real official-source enrollment, hosted/physical voice evidence,
and a deliberately observed real pilot rollback remain external evidence gates.

## Screenshot findings and resolution

| Screenshot | Root cause | Current resolution |
|---|---|---|
| 50 — why 30 | Commercial quantity could survive a cart clear through structured/confirmed state, and an unresolved new workload could inherit an older quantity. | Cart clear removes commercial keys from all state containers and the browser; unresolved concept resolution drops inherited quantity. The clear/reset boundary passed 31 focused checks. |
| 51 — broken no multiturn | Explanation context was effectively a single last explanation and mixed explain/mutation turns could fall into an unrelated retrieval clarifier. | Explanation evidence is persisted per SKU; an existing cart/selected product suppresses the false empty-retrieval budget clarifier. |
| 52 — no explanation | The cart-mutation confirmation response won the response projection and hid the requested explanation. | Compound cart projection carries the selected SKU's explanation and deadline feasibility into the confirmation response. |
| 53 — not clearing/not adding | Decomposition represented the new line but lost the second cart operation unless the model returned both; the UI displayed a generic confirmation with no durable operation list. | A cart-grounded parser resolves both clauses deterministically, including `30 + 30 = 60` and removal of the Lenovo line. The pending card enumerates both operations and applies them transactionally. |

Only one unconfirmed plan is current per tenant/buyer. A newer plan atomically supersedes older
proposals; old cards cannot apply. “Discard plan” now durably rejects the server-side plan instead of
only hiding browser UI.

## Reordered release gates

1. **Keep V2 compatibility available — PASS.** `recommend_compat.py` remains registered and
   deprecated; it was not changed.
2. **Deterministic cart/explain behavior and provider latency — PASS locally.** The live qwen3:14b
   probe produced 3,216 ms, 3,523 ms, and 3,058 ms after warm-up. Reusing the process-scoped HTTP
   client reduced non-provider transport/setup time from roughly 2.2 seconds to 10–42 ms. The
   timing contract separately reports queue, model execution, provider-internal, transport, and
   total provider time.
3. **Human relevance review — BLOCKED on a person.** The eight-slate file remains an independent AI
   draft. Current evidence is Precision@10 0.2222 and NDCG@10 0.5916. The current candidate slates
   also expose two shown but ungraded SKUs: `HDD-A9AE2F06` in `brand_negation:0` and
   `LAP-0A1191AB` in `persona_creator:0`. The seal command now refuses incomplete coverage and
   rejects automated reviewer identities.
4. **Real official workload/product sources — BLOCKED on operator enrollment.** The code now
   requires an API credential, publisher-policy ID, named independent reviewer, tenant allowlist,
   official domain allowlist, and positive freshness SLA. Freshness is derived from each claim's
   observation time; an endpoint cannot label itself fresh. None of the production values are
   configured locally, so no production-source evidence is claimed.
5. **Typed architecture alternatives — PASS.** The response projects exactly laptop, mobile
   workstation, fixed workstation, server, and cloud, with typed tradeoffs and unresolved inputs.
   It never selects a class or grants catalog/commercial authority.
6. **IMAGE and voice evidence — PARTIAL.** A real concurrent local run used GLM-OCR and
   qwen3-vl:8b: OCR completed in 8,662 ms, vision in 17,850 ms, and combined wall time was 17,854
   ms, demonstrating actual overlap. A real unreachable-provider run now returns degraded in
   2,092 ms against a two-second provider budget; before the shared deadline fix it took 10,086 ms.
   The host exposes a physical `Microphone Array (Realtek(R) Audio)`, but no capture harness is
   installed and neither hosted ASR nor TTS credential is configured. Hosted and physical voice
   certification therefore remains open.
7. **Pilot identities and observed rollback — BLOCKED on operator identities/live observation.**
   Exact tenant-qualified enrollment and immediate `pilot -> off` rollback pass automated tests,
   while wildcard/malformed/empty cohorts fail closed. No real pilot subjects are configured, so a
   production rollback observation is not claimed.
8. **Remove compatibility endpoint — NOT PERMITTED** until gates 3, 4, 6, and 7 have production
   evidence.

## Verification completed

- 230 focused backend checks passed across cart resolution/mutation, explanation persistence,
  timing, provider enrollment, infrastructure projection, relevance sealing, image deadline,
  pilot rollback, and voice contracts.
- 31 additional cart-clear/session-reset checks passed.
- 12 frontend component/behavior tests passed.
- Frontend production build passed; the existing single-chunk size warning remains.
- `git diff --check` passed for the touched surfaces.

## Required operator actions

1. Have a named independent human inspect all eight current candidate slates, grade every shown SKU,
   then run:

   `python -m scripts.seal_relevance_labels --reviewer <name> --reviewed-at <ISO-8601> --apply`

   Rerun the three sealed scorecards after the label file changes. Do not tune against the test
   split and do not promote unless both thresholds pass.
2. Populate the official-source variables documented in `.env.example`, then capture source
   revisions, observation timestamps, policy decisions, and freshness-SLA results from real calls.
3. Supply hosted voice credentials and a physical audio capture harness, then run microphone -> ASR
   -> chat and response -> TTS -> speaker tests on the pilot host.
4. Supply explicit `tenant:user` pilot identities, set `RECOMMEND_CORE_MODE=pilot`, observe the
   agreed window, deliberately flip to `off`, and retain served/delegated telemetry proving rollback.

