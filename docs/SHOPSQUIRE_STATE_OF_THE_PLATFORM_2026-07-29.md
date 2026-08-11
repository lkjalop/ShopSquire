# ShopSquire — State of the Platform (2026-07-29)

*Delta from the 2026-07-28 assessment, verified against the tree rather than accepted from report.
Answers: what moved, what ShopSquire is now, and how to describe it.*

---

## 0. The headline

**`recommend.py` is gone.** During this analysis session, commit `f12ea071 archive legacy
recommendation router` deleted the 12,403-line file that has been the critical path for a month. The
file was present at one tool call and absent three calls later.

It was not merely deleted — it was **archived under a SHA-256 seal** with a manifest that records the
frozen characterization suite's honest last-observed state:

```python
assert evidence["collected_tests"] == 62
assert evidence["last_observed"]["failed"] == 36
assert evidence["status"] == "non_executable_historical_evidence"
```

**62 tests, 36 of them failing, explicitly marked as historical and forbidden from being presented as
green evidence.** Most teams delete the file and quietly drop the failing tests. This records that
they were failing and seals the hash so nobody can pretend otherwise. That single test is a better
signal of engineering character than any feature in the repo.

Verified after deletion: **zero remaining importers, app boots, 738 routes.**

---

## 1. Delta: 2026-07-27 → 2026-07-29 (48 hours)

| Measure | 07-27 | 07-29 | Δ |
|---|---:|---:|---:|
| Total LOC | 390,238 | **416,587** | **+26,349** |
| `src/` | 253,686 | 271,310 | +17,624 |
| `tests/` | 95,527 | 101,686 | +6,159 |
| Services | 384 | **424** | +40 |
| Routers | 115 | 117 | +2 |
| Migrations | 65 | **86** | +21 |
| Registered routes | 704 | **738** | +34 |
| **`recommend.py`** | **12,536** | **0 (deleted)** | **−12,536** |
| Collected tests | — | **5,524** (2,953 in `tests/services`) | — |
| Commits since 07-28 | — | **53** | — |

**~26,000 net new lines in 48 hours while simultaneously deleting a 12.5k-line file.**

### Report claims — independently verified

| Claim | Verdict |
|---|---|
| `recommend.py` ≈ 12,403 lines | ✅ exact |
| "Exactly one direct legacy import remains" | ✅ correct — my own grep false-positived on `recommendation_feedback` as a prefix match |
| 2,953 service tests collected | ✅ **exact match** |
| USGS governed adapter with licensing/origin controls | ✅ `market_source_registry.py` carries `licence_id`, `licence_url`, origin validation |
| Reversible Party identity with four-eyes | ✅ `account_intelligence.py:1083 identity_execution_four_eyes_required` |
| Fail-closed ATP / conservation exceptions | ✅ `inventory_event_projection.py` (440 ln), `inventory_projection_read_model.py` |
| Governed UoM conversion | ✅ `business_semantics.convert_quantity`, `product_identity.uom_category_mismatch` |
| Permanent `simulation_only` authority | ✅ present across 6 modules |
| Migration rollback defect found and fixed | ✅ `f198e707 make supply workflow migration replayable` |

**Every checkable claim in the report held.** No overclaiming found.

---

## 2. The specification loop closed in ~24 hours

Yesterday I wrote nine specifications (B.1–B.9). Verified in the tree today:

| Spec | Status | Evidence |
|---|---|---|
| **B1 currency authority** (the #1 blocker since 07-13) | ✅ **BUILT** | `currency_authority.py` (188 ln): `fx_provenance_required`, `fx_authority_not_approved`, `fx_authority_stale_or_future`, `approved_fx_authority_required` |
| **B.1 ATP fail-closed, `unknown` never `on_hand`** | ✅ built | tri-state ownership + conservation failure detection |
| **B.2 UoM conversion + category guard** (I called it a correctness blocker) | ✅ built | `uom_conversion_factor_must_be_positive`, `uom_category_mismatch` |
| **B.3 dataset licensing** | ✅ built | `licence_id` / `licence_url` on every registered source |
| **B.4 forecasting baselines** | ✅ built | `rolling_origin_evaluation`, `seasonal_naive`, `croston_sba`, `forecast_wape` — the in-sample `mape_proxy` is gone |
| **B.5 merge/split thresholds + four-eyes + reversibility** | ✅ built | `account_intelligence.py` 221 → **1,186 lines** |
| **B.6 supplier composite** | ✅ built | `otif`, `insufficient_evidence`, and `reliability = exp(-(spread / mean_lead))` — **verbatim the formula specified** |
| **B.7 contradiction handling** | ✅ partial | `claim_grounding.py` has `supported \| needs_evidence \| contradicted` |
| **B.8 origin pinning / no uncontrolled scraping** | ✅ built | `cf5e6c8b pin public fetches to approved origins`; USGS chosen as a **credential-free official source** — the "never authenticate" rule followed exactly |
| **B.9 simulation vs certification** | ✅ partial | `simulation_only` authority is permanent and enforced; provider certification registry not yet formalised |

**Eight and a half of nine specifications implemented inside a day.** The `reliability = exp(−σ/LT̄)`
match is verbatim. This is the fastest spec-to-implementation loop I have seen in this codebase.

---

## 3. What ShopSquire is now

### The description

> **ShopSquire is an evidence-governed commerce decision system: an event-sourced, bitemporal
> platform that spans buyer conversation → catalog truth → margin → procurement → supplier
> communication, where every output carries its provenance, every number carries its basis, and the
> system abstains rather than guess when the facts are incomparable.**

Two days ago I described it as *"a working system with an unusually good conscience and no
customer."* That is now too weak. The conscience stopped being a posture and became **mechanism**:

- **Currency authority** — cannot compare AUD to USD without a dated, sourced, approved FX rate.
- **UoM authority** — cannot compare "each" to "case of 24" across UoM categories.
- **ATP authority** — cannot report availability when reservations are unknown; returns `unknown`.
- **Evidence authority** — external claims carry licence, origin, revision, freshness.
- **Simulation authority** — synthetic results are permanently labelled `simulation_only` and cannot
  be laundered into production claims.
- **Identity authority** — merges require four-eyes, are append-only, and are reversible.
- **Historical authority** — the archived legacy suite is hash-sealed with `36 failed` recorded.

**The unifying property, and the thing that makes this genuinely unusual:**

> It knows the difference between what it *observed*, what it *derived*, what it *estimated*, and
> what it *cannot know* — and it structurally prevents the last two from acquiring business authority.

Most AI systems fail by letting generated text become an assertion, and an assertion become an
action. Every authority boundary above exists to break that chain at a different point.

### What it is *not*

- **Not a product.** No customer, no pilot, no revenue.
- **Not proven.** Every number is synthetic. The report says this itself, correctly: *"synthetic
  replay proves invariants and model discrimination — not reduced stockouts or increased margin."*
- **Not a recommender.** That framing has been obsolete for a while; the deletion of `recommend.py`
  makes it official.
- **Not a CRM, ERP, or system of record** — deliberately, and the line has held.

---

## 4. Structural state

### The good
- **`recommend.py` retired properly** — deleted, hash-sealed, honestly labelled, zero importers, app
  boots at 738 routes.
- **Test mass is real:** 5,524 collected, 2,953 in services alone, 101,686 lines of test code.
  Test-to-source ratio **0.37**.
- **Routers are shrinking** as logic moves to services — the anti-monolith pattern is holding.
- **86 migrations with a rehearsed rollback** — and a real rollback defect was found *and fixed*
  (surviving append-only triggers on re-upgrade). Finding that class of bug means the rehearsal is
  genuine, not ceremonial.

### The remaining large files
| File | Lines | Note |
|---|---:|---|
| `routers/admin.py` | 4,169 | unchanged; now the biggest file in the repo |
| `routers/support_complaints.py` | 3,990 | router doing service work |
| `services/orchestrator.py` | 3,960 | **overlaps `recommendation_core` — ownership still undecided** |
| **`routers/chat.py`** | **3,410** | ⚠️ **grew from 3,251.** The duplicate regex router and the 1,533-line god-function are still there, and the file is getting *bigger* |
| `routers/admin_email_security.py` | 3,244 | |
| `routers/merchant_dashboard.py` | 3,203 | |
| `services/recommendations.py` | 2,297 | ⚠️ legacy sibling of `recommendation_core` — a second decision surface that survived the archive |

**With `recommend.py` gone, `chat.py` inherits the title of the most dangerous file** — it holds a
duplicate decision surface (the regex intent router), it is growing, and the doctrine explicitly
forbids what it does.

---

## 5. What actually remains

| # | Item | Why it matters | Owner |
|---|---|---|---|
| 1 | **Real outcome evidence** | The only thing that separates this from an engineering artifact. Synthetic replay proves invariants, not reduced stockouts or improved margin. Needs a design-partner shadow pilot with real orders, ATP, receipts, invoices, supplier outcomes | **YOU** (a customer, not code) |
| 2 | **PostgreSQL migration rehearsal** | SQLite is proven; production-shaped Postgres upgrade/rollback and trigger behaviour are **not certified**. 86 migrations is a lot of unrehearsed surface | ME |
| 3 | **CI on hosted runners** | Local sharding is green; `gh` is unauthenticated. Local-green is not evidence anyone else can check | YOU (`gh auth login`) then ME |
| 4 | **Full production-shaped browser battery** | Component tests + admin build pass; the complete Redis/backend/worker/storefront/admin clickthrough was not rerun | ME |
| 5 | **`chat.py` strangle** | The last duplicate decision surface, and it is growing | ME |
| 6 | **`recommendations.py` (2,297) disposition** | Fold or delete — a second decision surface survived the archive | ME |
| 7 | **`orchestrator.py` vs `recommendation_core`** | Decide which one is the brain before either grows further | ME |
| 8 | **B3 relevance labels** | Still `human_reviewed_by: null` — the oldest open item in the project | **YOU** |
| 9 | Provider certification registry (B.9) | `simulation_only` is enforced; per-provider certification with expiry is not yet formalised | ME |
| 10 | Ruff cleanup by subsystem | New boundaries ratcheted; legacy repo not clean | ME |
| 11 | Inventory intelligence depth (lot/expiry, waste, FVA, lost demand) | Genuine capability, correctly sequenced **after** a pilot | ME |

**The critical observation:** items 2, 3 and 4 are all the same category — **evidence that someone
other than this machine can verify.** The engineering is far ahead of the proof that it runs anywhere
but here. For a self-hosted product, "runs on a hosted runner and rehearses on Postgres" is not
hygiene; it *is* the product claim.

---

## 6. Trajectory read

**Two days ago** I wrote: *"direction excellent, batch discipline poor"* — 6,100 uncommitted lines,
12 pending migrations, two open correctness blockers.

**Today:** the batch landed as **53 discrete commits** with readable one-concern messages
(`persist governed inventory projections`, `execute reversible Party identity redirects`,
`pin public fetches to approved origins`). The working tree is down to **29 entries**, most of them
scratch directories and docs. **The batch-discipline criticism was addressed.**

Both correctness blockers I raised are now closed: **B1 currency authority is built**, and the
uncommitted-cutover problem resolved itself into a completed archive.

**This is the healthiest 48 hours in the project's history.** A month-long critical path closed, two
blockers cleared, nine specifications implemented, and the delivery pattern that I criticised was
corrected within a day.

**The one thing that has not changed in seven months:** there is still no customer, and therefore
still no evidence that any of this helps anyone. That is now — unambiguously — the only remaining
question that matters.

---

## 7. On the hiring-manager framing

The proposed positioning:

> *"I build AI systems that can identify their evidence, quantify uncertainty, abstain when facts are
> incomparable, and prevent model-generated text from acquiring business authority."*

**This is accurate and defensible**, and I verified each clause:
- *identify their evidence* → licence/origin/revision on every external source
- *quantify uncertainty* → forecast interval calibration, conditional coverage, WAPE over rolling origins
- *abstain when facts are incomparable* → `currency_authority`, `uom_category_mismatch`, ATP `unknown`
- *prevent text acquiring authority* → `claim_grounding` verdicts, `simulation_only`, four-eyes gates

**One sharpening.** The strongest single artifact is not the architecture — it is the archive test
that records `36 failed` on a suite being retired. Lead with that in an interview. Anyone can claim
they build careful systems; almost nobody ships a test whose job is to stop *themselves* from
overclaiming later. That is the credential.

**One caution.** Do not present synthetic evaluation as outcome evidence. The report gets this right
internally; make sure the demo does too. The honest and stronger claim is: *"I built the measurement
apparatus that would detect it if I were wrong, and it is telling me I don't have outcome evidence
yet."*

---

*Assessment only. No code changed. Note: the repository was being actively modified by a concurrent
session during this analysis; all figures verified against the tree at HEAD `f12ea071`.*
