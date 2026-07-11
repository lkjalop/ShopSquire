# V2 Analysis — Workload / Persona / Intent Resolution (2026-07-12)

**A mini stop-and-assess.** Triggered by: "generalize the game-requirements insight beyond games
(AutoCAD, Unreal, video rendering); handle persona differences (primary vs university-CS vs
english-major vs work); handle multi-intent; don't rebuild the deterministic treadmill; watch
latency; make the model take more responsibility." Verdict up front: **you are correct, not
paranoid — and the correct fix is ONE agnostic mechanism, not N special cases.**

## 1. The evidence (end-to-end test, current core, live model + demo DB)

| Query | node | reqs | top-3 | clarify asked |
|---|---|---|---|---|
| laptop for a **primary school** student | el-6-6 | {} | HDD-A9…, LAP-031, LAP-04C | "budget?" |
| laptop for a **university CS** student | el-6 | {} | GAM-0001, GAM-0002, GAM-0003 | "budget?" |
| laptop for a **university english** student | el-6-6 | {} | HDD-A9…, LAP-031, LAP-04C | "budget?" |
| a laptop for **work** | el-6-6 | {} | HDD-A9…, LAP-031, LAP-04C | "budget?" |
| laptop for **autocad and revit** | el-6-6 | {} | HDD-A9…, LAP-031, LAP-04C | "budget?" |
| laptop for **unreal engine** dev | el-6-11-2 | {} | GAM-0001..3 | "budget?" |
| laptop for **4k video editing** | el-6-6 | {gpu_vram≥8} | LAP-343, HDD-A9…, LAP-031 | "budget?" |
| **gaming <$1500 AND video editing** | el-6-6 | {**storage≥1500**, gpu_vram≥4} | LAP-343, HDD-A9…, E2E | "budget?" |
| daughter starting uni, essays + photoshop | el-6-6 | {} | HDD-A9…, LAP-031, LAP-04C | "budget?" |

**Five failure modes, all the same root:**
1. **Persona blindness** — a 7-year-old, an English major, and a CAD professional get the *same
   arbitrary SKU-alphabetical slice*. No requirement inference from persona/use-case.
2. **Software-workload blindness** — AutoCAD/Revit/Unreal produce `reqs={}`. The model only
   emits a spec when it happens to guess a number; there is no grounded requirements lookup.
3. **Multi-intent collapse** — "gaming AND video editing" flattens to one node; the two
   workloads' requirements are not unioned.
4. **Budget→requirement bleed (live bug)** — "under $1500" parsed as `storage_gb ≥ 1500`. The
   number extractor has no notion that $1500 is a price, not a spec.
5. **Useless clarify** — every case asks "what budget?" even when the real ambiguity is the
   *use-case* ("what kind of work?", "which CS courses — ML or web?").

## 2. Why this is ONE mechanism, not N special cases (the anti-treadmill point)

Every row above is the same shape: **an underspecified query where a WORKLOAD / PERSONA /
USE-CASE implies hardware requirements the recommendation must honor.** "for university CS",
"to play Valorant", "for AutoCAD", "for a primary schooler", "for 4k editing" are not five
features — they are five *inputs to one resolver*:

```
query
  → (model) classify expressed intent(s) → use_case_key(s)     [unbounded → bounded, CLAMPED]
  → (deterministic) look up each key's REQUIREMENT PROFILE      [KB / Steam / spec-source]
        gpu_vram, ram, storage, cpu_tier, display, refresh …
  → (deterministic) resolve MULTI-intent by MAX (most demanding wins — the safe recommendation)
  → requirements → fit stage → ranker → upsell logic
  → (model) decide: enough to recommend, or ASK the use-case-specific next question?
  → (model) narrate the verdict + WHY, grounded in the profile's source
```

The model does the **unbounded→bounded mapping** (phrase → use_case_key, clamped to a known
set) and the **judgement** (enough info vs ask). Deterministic code does the **requirements**
(no model-invented specs) and the **fit**. This is the platform's existing doctrine —
model-judged, clamped, deterministic-grounded — applied to *use-case*, and it is **vertical-
blind**: the identical resolver serves games (Steam), pro software (a spec KB), personas (a
persona KB), and other industries (pharma "medicine for hay fever" → active-ingredient class;
furniture "desk for a small room" → dimension constraints). One mechanism, many DATA sources.

**Half of it already exists in legacy** and must be reused, not rebuilt: `config/use_case_kb.json`
(7 use-cases: gaming, university, engineering, creative, corporate, calls, ai_ml),
`use_case_advisor` (persona + requirement logic), `connectors/steam_requirements.py`,
`gpu_translation.py`, and the governed web leg (external-search fallback, injection-scanned).

## 3. The reordered roadmap (this SUBSUMES three separate items into one)

The prior roadmap listed "relevance (item 4)", "valorant pipeline (item 5)", and "persona
features" as separate. They collapse into **one item: the Intent→Requirements Resolver.** This
does NOT balloon the roadmap — it *shrinks* it (3 items → 1 mechanism + data).

1. **Typed shared postflight** (`recommendation_postflight.py`) — v1+v2 both use it (memory,
   post-policy, metering, narration). *Prereq: the resolver's narration needs it.*
2. **Shadow worker + Redis Stream** — real live comparison (writer exists, no consumer).
3. **Intent→Requirements Resolver** (`recommendation_core/intent_resolver.py`) — THE unifying
   mechanism. Model classifies use_case_key(s) clamped to the KB; deterministic profile lookup
   (use_case_kb + Steam + spec-source, external-search fallback on miss + consent); multi-intent
   by MAX; **fixes the budget-bleed** (price tokens excluded from spec extraction structurally);
   feeds fit + ranker + the **use-case-specific next question**. Persona granularity (primary /
   high-school / university-by-major / work-by-type) = KB rows, not code.
4. **`quality.py` intrinsic gate** — precision, hard-constraint rate, recall@K, NDCG@K,
   empty-rate, diversity (now measurable because the resolver gives relevance ground truth).
5. **Requirements-grounded loop w/ trusted-source + supplier shortfall** — Steam/spec verify →
   sift inventory → recommend-with-lagginess OR truth + supplier draft (sandbox, human-gated).
   This is item 3 extended with external verification + the fulfillment draft path.
6. **Decision-trace surfacing** — "Why Recommended" shows the inferred use-case, its SOURCE,
   the requirement profile, and how it ranked; per-agent events show the resolver's decision.
   *The observability of the new reasoning = the trust thesis made visible.*
7. Prior-subject resolution (delete FILTER-guard + sold-name veto) · offered-candidate clamp ·
   result-count discipline · integration tests · sealed benchmark · shadow soak → canary.

## 4. How the model takes MORE responsibility without brittleness or latency

**More responsibility (clamped):** the model now owns (a) intent classification (phrase →
use_case_key(s)), (b) the enough-vs-ask decision, (c) narration. All three are *judgement*, and
all three are clamped — it picks from KB keys, it can only ask from a bounded question set, it
narrates over grounded evidence. It never invents a requirement, a price, or a spec.

**No new brittleness:** zero new decision surfaces. The requirement numbers live in DATA
(use_case_kb / Steam / spec-source), reviewed as data. Adding AutoCAD is a KB row, not an
`if "autocad"` branch. That is the whole point — the treadmill you're guarding against is
per-workload code; the mechanism is per-workload *data*.

**No new latency (the design constraint):**
- **KB fast-path**: known use-cases resolve by dictionary lookup (~0ms), no model/network call
  beyond the routing call that already happens.
- **Parallel scatter-gather**: catalog retrieval, requirement lookup, and (if needed) trusted
  source run as *concurrent* legs with per-leg budgets (`recommend_pipeline` already does this),
  so wall-clock = slowest leg, not the sum.
- **External search only on KB-miss AND consent** — rare, and async/offerable ("want me to
  look up its requirements?") rather than blocking every turn.
- **Ask-before-fetch**: when intent is ambiguous, the next question short-circuits the expensive
  legs — cheaper *and* more honest than guessing.

## 5. Are you being pedantic / paranoid?

No. The test proves it: today the core cannot tell a primary schooler from a CAD professional.
Your instinct — that fixing this per-game/per-app/per-persona rebuilds the deterministic
treadmill — is exactly the failure mode this whole rebuild exists to escape. The one nuance
(not a correction): the guard against over-inference is the *ask-vs-recommend* decision — for
"a laptop for work" the right move is to ASK "what kind of work?", not to guess. That is where
the model earns its expanded responsibility, and it is anti-brittle by construction (it doesn't
hard-code work→specs; it recognizes underspecification and resolves it by conversation).

## 6. Agnostic-core check

Focus is electronics, but nothing above is electronics-specific. The resolver is
`intent → requirement-profile → fit`; the profiles are data. Pharma: "medicine for hay fever" →
antihistamine class + dosage constraints. Fashion: "outfit for a winter wedding" → formality +
season constraints. Furniture: "desk for a small apartment" → dimension constraints. Same
mechanism, different KB. The persona dimension generalizes identically (a "gift for my mum" is a
persona-shifted intent in any vertical). Build it electronics-first, keep the resolver and the
KB schema vertical-blind.
