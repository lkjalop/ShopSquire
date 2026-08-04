# Hippograph + Market-Intelligence Assessment — and their place in the V2 arc (2026-07-11)

Evidence-based (file:line-verified sweep, same discipline as the deep-dive). Companion to
`docs/SHOPSQUIRE_V2_REBUILD_STATUS_AND_ROADMAP_2026-07-11.md`.

## 1. How hippograph actually works (one paragraph)

Hippograph is a **per-turn, in-memory graph recall**: it projects `decision_trace_events`
(relation edges), `conversion_event` (reward edges — dollars become node weight), plus
optional catalog brand edges, M3 market findings, and human-feedback priors into a small
graph (nodes canonicalized through entity_resolution), then runs a 2-hop spreading-activation
(PageRank-flavored: decay 0.5/hop + 0.1×reward prior) from the turn's seed nodes and returns
top-k scored nodes. Deterministic, read-only, rebuilt every call. Consumers: the recommend
intelligence stage (insights/shadow-counterfactual/ranking nudge), the market-intelligence
context gatherer, an operator endpoint, and governance pulse.

## 2. Verdict

**What's genuinely good — keep and say no to "fixing" it:**
- The **sensor layer being deterministic is correct**, not brittleness. M1 signals, M2
  warehouse, M3's 11 detectors, M6 attribution, M7's fail-closed action gate — measurement,
  bookkeeping, and authorization SHOULD be deterministic and auditable. The doctrine is
  *deterministic sensors → model judgment → clamped actions*, and the sensor half is real.
- Every ranking-mutating lever passes `adaptive_action_gate.authorize()` (kill-switch →
  action whitelist → confidence floor → durable audit, fail-closed). That is the guard
  pattern V2 wants everywhere.
- Reward-weighted recall over the platform's own decision/conversion history is a real
  asset no competitor gets for free — it just needs a backbone (below) and daylight (flags).

**The three real problems:**
1. **It's dark.** `HIPPOGRAPH_FEEDBACK_ENABLED` off ⇒ `_mi_mode=off` ⇒ insights never
   populate ⇒ counterfactual + nudge never run; `MARKET_PIPELINE_ENABLED` off ⇒ no findings
   ⇒ sales-response nudge no-ops even though its flag is on in feature_flags.json. The whole
   chain is built, gated, and unlit.
2. **It's ungrounded.** Zero linkage to the new taxonomy: recall keys on raw SKUs +
   brand slugs; cold-start products reach the graph only via a 0.25-weight brand edge;
   `market_intelligence_agent` scopes findings to a query by 3-char token overlap — the same
   token-blindness the classifier just escaped.
3. **It has the house diseases in miniature:** ~30 inline magic numbers (EWMA α, surge
   ratios, severity maps, confidence divisors); THREE different severity→weight maps; TWO
   copies of the off/shadow/live mode parser; TWO inventory-position classifiers with
   different thresholds; and hippograph's read path swallows every exception to `[]` while
   the warehouse path logs — the silent/loud split is arbitrary.

## 3. Improvement plan (ranked, tied to the V2 spine)

1. **Taxonomy backbone for recall (small, additive, high yield).** A `project_taxonomy()`
   projection reading `product_classification` (sku → node_handle; handles encode hierarchy
   as string prefixes) gives recall category edges: cold-start SKUs become reachable through
   category siblings, and recall gains "shoppers convert in this category" semantics.
   Node-id contract already lines up (both key on sku). Treat `status != approved` as
   no-edge; respect `grounding_status`. ~1 session, zero recall-math changes.
2. **Findings keyed to taxonomy nodes.** M3 detectors emit `scope` today; adding
   `node_handle` (via product_classification for sku-scoped findings) lets
   `market_intelligence_agent` scope findings to a turn by TAXONOMY MAPPING instead of token
   overlap — the same unbounded-language→bounded-vocabulary move as everywhere else. The V2
   turn_router already produces the query's node handle; findings join on it for free.
3. **V2 core integration: market intel becomes an evidence leg.** In `recommendation_core`,
   the intelligence stage is a post-plan evidence leg reading the SAME TurnEnvelope, its
   outputs landing in `CoreResponse.extras` → surfaced by the adapter. The two `_mi_mode`
   copies, the `_flag_on` re-implementations, and the stage's bolt-on position in the
   monolith all retire with Phase 5.
4. **Light the chain in V2 shadow, not in the monolith.** Don't flip the dark flags on
   suggest() — the corpus was recorded flags-off, and lighting them there creates parity
   noise. Instead: pipeline on (batch, buyer-invisible) now; recall/nudges light up as core
   stages during Phase-5 shadow where the differ measures their effect for free.
5. **Thresholds → data, constants → one home.** Detector thresholds and severity/weight maps
   move to a `data/market/thresholds.json` (the attribute-defs pattern: tuning becomes data
   review, not code diffs); ONE severity map; ONE inventory-position classifier
   (sales_response_policy's, parameterized); ONE mode parser.
6. **Silent→loud sweep in the read path** (`build_hippograph_insights`, `hippograph_db`,
   `gather_market_context` full-body swallows): same `grounding_status`-style tri-state or
   at minimum the warehouse's logged-fallback idiom. A recall that quietly returns `[]`
   is the 13th mute layer waiting to happen.
7. **Where the MODEL earns a bigger role (clamped, per doctrine):** (a) digest narration —
   already scaffolded, off, low risk; (b) *lever proposal*: the model reads findings and
   proposes which CLOSED action (sales_response_policy's enum) fits the situation, gate
   authorizes, policy clamps magnitude — llm_planner pattern applied to market response;
   (c) finding interpretation in buyer-facing prose via the narration guard. The model never
   invents a finding, a price, or a boost magnitude.

## 4. What this means for recommend.py / suggest() brittleness

The monolith's intelligence stage is already extracted and gate-guarded — it is NOT where
effort should go. The brittleness that matters lives in the decision surfaces V2 replaces
(routing, off-catalog, workload parsing — Phases 0-4 work, done or in flight). Market intel's
path to "less deterministic" is NOT softening its sensors; it is (a) grounding its recall and
scoping on the taxonomy, (b) letting the model propose actions from a closed vocabulary while
deterministic policy clamps magnitudes and the gate authorizes, and (c) making every silent
degradation loud. Same doctrine, third subsystem.

## 5. Sequencing

Now→Phase 4: nothing blocks the core build; item 1 (project_taxonomy) is safe anytime.
With Phase 4 step 3: item 2 (findings on node handles) rides the router's handle output.
Phase 5: items 3-4 (core evidence leg, light-in-shadow). Backlog: items 5-7 (data-driven
thresholds, dedup, loud reads) — mechanical, low risk, high hygiene.
