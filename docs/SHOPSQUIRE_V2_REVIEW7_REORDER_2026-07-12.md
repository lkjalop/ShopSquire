# V2 — Review-7 Assessment + Reordered Sequence (2026-07-12)

GPT-5.6 review-7 ran the actual replay and returned a reading that **changes the plan**. Assessed
and ACCEPTED in full. Supersedes the P1 ordering in the review-6 response.

## The two findings that move the plan
1. **V2 is already quality-RED on LABEL-FREE metrics** (GPT-5.6's live `--facade-mode` run):
   empty-rate **16.67%** (>15% fail), constraint-satisfaction **39.44%** (<70% fail),
   budget/dup 0%, relevance coverage 0% → promotion gate FAIL. **Labels are not the only
   blocker** — the core shows suitable products for only ~39% of verdict-carrying picks (the
   cyberpunk zero-GPU class, systematized). Building more measurement infra before diagnosing
   this is premature.
2. **The P0.5 idempotency fix was cosmetic** — header name mismatch + a replay guard skipped for
   the stream path, so stream→fallback still double-resolved. **FIXED** (`dcc7d0e`): a real redis
   single-flight; a duplicate returns the first's cached result, producer runs exactly once.

Also confirmed: tenancy is only partly solved (X-Tenant-Id client-supplied, cart still uid-only)
— P0 is NOT "complete" until cart identity is `(tenant_id, uid)`.

## Reordered sequence (GPT-5.6's, adopted)
1. ✅ **Single-flight idempotency** — done (`dcc7d0e`).
2. ⬜ **DIAGNOSE the 39.4% constraint-satisfaction** (NEW #2, was not on the list). Export
   per-case empty + per-product fit verdicts from the replay; determine whether it's (a) genuinely
   unsuitable products (a ranking/fit bug), (b) missing catalog specs (products have no ram/gpu
   values → "unknown" verdicts), or (c) metric mis-population. **Do NOT lower thresholds to green
   it.** Needs a live replay run (Ollama+DB) — the export tooling I can build; the read is live.
3. ⬜ **P1.3 stateful replay** — carry session turn-to-turn; **key quality rows + labels as
   `case_id:turn`** (this is why labeling must WAIT — case-only keys collide follow-up turns);
   CONSUME `prior_shortlist` (not just carry it); `--facade-mode --stateful` becomes the release
   command.
4. ⬜ **Candidate-slate export for labeling** — query/constraints/workload/budget, V1+V2 ranked
   SKUs, specs + fit verdict, blank human grade, dev/test split assigned before grading.
5. ⬜ **Start labeling** (human) — critical strata: budget, negation, gaming/workload,
   university/persona, off-catalog, multi-turn. Two reviewers on test-split disagreements. Model
   never writes final labels.
6. ⬜ **P1.1 full-envelope serialization** — in PARALLEL with labeling (least urgent; live-worker
   fidelity). Versioned `TurnEnvelope.to_dict/from_dict` incl. budget/session/cart/image posture;
   worker consumes it.
7. ⬜ **Rerun the first genuine gate** — `--facade-mode --stateful` with labels. Require: 0
   security/honesty BLOCKERs · expected 3/3 · empty ≤15% · constraint-sat ≥70% · representative
   coverage · precision@10 & NDCG@10 ≥60% · no budget/dup/inactive/unsold products.

## What NOT to do (GPT-5.6, adopted)
No search canary · don't archive `suggest()` · don't lower thresholds · don't label only easy
single-turn cases · don't spend the next increment on P1.1 before the fit failure is diagnosed ·
don't call P0 complete until idempotency (✅) AND tenant ownership (⬜ cart identity) are real.

## The headline reframed
Before review-7 the story was "measurement is real; fill labels for a green number." Review-7's
actual reading says: **V2's search core is not close to promotable — it's red on quality metrics
that need no labels.** So the next real work is DIAGNOSIS of the 39.4% fit failure, not more
scaffolding. The screenshots (cyberpunk zero-GPU, budget-loss) are now backed by a number: the
core is systematically showing products that don't meet the workload requirements. That is the
thing to fix before anything downstream.

## Immediate next actions
- **Me (build, no live needed):** the diagnostic export (#2 tooling) + **P1.3 stateful replay
  with case:turn keying** (#3) — the prerequisite that makes labeling safe.
- **You (live/human):** run `python tests/characterization/shadow_replay.py --facade-mode` to
  confirm the reading locally; once the diagnostic export lands, we read WHICH products fail fit
  and WHY (unsuitable vs missing-specs vs metric bug).
