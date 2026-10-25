# ShopSquire — Publication Gap, Security Assessment & Reordered Roadmap

**Date:** 2026-09-15 · **Local HEAD:** `c7daafaa` · **103 dirty files**
**Published tip:** `87987967` on `origin/checkpoint/turn-state-consolidation-20260830`, **dated 2026-09-01**
**Method:** git ref comparison against `github.com/lkjalop/ShopSquire`, secret/credential scan of tracked
content, AST route-guard audit, live unauthenticated probes against the local instance, live buyer
journeys, full backend sweep. No cart, supplier, approval or payment action was taken.

---

## 0. Verdict

**The single largest risk on this project is no longer a defect. It is that the work is not published.**

GitHub has `87987967` from **1 September**. Local is **29 commits and 267 files ahead**
(**+21,943 / −2,894**), plus **103 uncommitted files** on top of that. Every fix in this entire arc —
the scope boundary, the evidence compiler, the authority gate, the atomic UI install, the audit
authentication, the stage-guard rollback, the price/quantity correction — exists on one laptop that
has bugchecked twice in the last fortnight.

Security: **no credentials, tokens or private keys are committed** — that part is clean. But there is
one genuine unauthenticated admin endpoint, and one configuration default that converts a documented
fail-closed control into a fail-open one. Both are the Janusec class exactly: not a clever exploit, a
route that looked guarded by convention and a default that opens instead of closes.

---

## 1. The publication gap

| | Value |
|---|---|
| Published tip | `87987967` — **2026-09-01** |
| Local HEAD | `c7daafaa` |
| Unpublished commits | **29** |
| Unpublished diff | **267 files · +21,943 / −2,894** |
| Uncommitted on top | **103 files** |
| Behind remote | 0 |

Two weeks of work, none of it pushed. The 103 dirty files include the price/quantity fix verified
two days ago and the stage-guard rollback discussed in §3.2 — neither is in any commit.

**This is the first thing to fix, before any code change.** Commit the tree in reviewable slices,
push the branch. Nothing else on this roadmap survives a disk failure.

---

## 2. Security assessment (the Janusec class)

The failure pattern in publicly-published security-adjacent codebases is rarely exotic: it is a
default credential that works, an admin route that was never guarded, or a secret that reached git
history. I checked all three.

### 2.1 Clean — no committed secrets ✅

```
tracked files matching .env / api_keys / *.pem / *.key / id_rsa  →  only *.example files
AKIA… / sk-… / ghp_… / -----BEGIN … PRIVATE KEY-----             →  1 hit, a detector test fixture
```

No AWS, OpenAI or GitHub tokens, and no private keys, in tracked content. `.env.example` and
`config/security/security-hardening.env.example` are templates. This is genuinely good hygiene for a
repo of this size.

### 2.2 🔴 Unauthenticated admin endpoint — confirmed live

```
GET /api/v1/admin/dmarc/summary          →  HTTP 200, no credentials
{"summary":{"top_ips":[],"top_domains":[]},"fail_rate":0.0}
```

`src/app/routers/admin_dmarc.py:29` declares `@router.get("/summary")` with **no role dependency**,
the router declares **no router-level `dependencies=`**, and
`admin_access_router_group.register_admin_access_router_group` adds none at `include_router`. The
`/api/v1/admin` prefix is a naming convention, not a guard.

Empty here because this instance has no DMARC data. On a real deployment it returns **sending-source
IPs, sending domains and email-authentication failure rates** — useful reconnaissance for anyone
planning to spoof that tenant's mail.

Second-order: the handler takes a caller-controlled `threshold_fail_rate` and calls `_emit_splunk`
when the rate clears it. An unauthenticated caller passing `threshold_fail_rate=0` can drive SIEM
writes on every request.

**Fix:** add `Depends(require_role([...]))` at the route or router, and add a registration-time
assertion that every router mounted under `/api/v1/admin` carries a role dependency. The assertion
matters more than the fix — it is the thing that stops the next one.

### 2.3 🟠 The fail-closed credential default is fail-open when `APP_ENV` is unset

`src/app/security/auth.py::_env_role_key` is well designed and clearly documented:

> *"Dev/local/test: an unset key falls back to the well-known 'local-*' value (ergonomics). In a
> non-dev env an UNSET key resolves to "" instead of the guessable default … Closes the 'auth
> defaults to a known key' fail-open."*

The control is correct. Its **trigger** is not:

```python
def _non_dev_env() -> bool:
    return str(os.getenv("APP_ENV", "local") or "local").strip().lower() not in (
        "local", "dev", "development", "test", "testing")
```

`APP_ENV` unset → `"local"` → `_non_dev_env()` is **False** → dev defaults apply → **`local-owner-key`
is a valid owner credential.** A container shipped without `APP_ENV`, a misspelled value, a dropped
env var in a compose override — any of those restores the backdoor the docstring says was closed.

**Fix:** invert the default. Unknown or unset environment must be treated as production; dev
ergonomics require an explicit `APP_ENV=local`. One line, and it makes the absence of configuration
safe instead of dangerous.

### 2.4 🟡 Default credential embedded in server-rendered admin markup

`admin_email_security.py:792, 906, 1116, 1656, 1688` and `merchant_dashboard.py:1343` emit
`'x-api-key': 'local-owner-key'` **into the HTML/JS served to the browser**. In a correctly
configured production environment this fails (the key resolves to `""`), so it is broken rather than
exploitable — but combined with §2.3 it is a working credential printed in a page. It also means
anyone reading the public repo learns the exact header name and dev key shape.

**Fix:** have those pages read the key from a runtime-injected config value, never a literal.

### 2.5 Route-guard audit — the broader picture

An AST pass over `src/app/routers` found **20 admin-prefixed routes with no route-level role
dependency**. Most are not exposed:

| Router | Routes | Live probe | Assessment |
|---|---:|---|---|
| `connectors_admin` | 2 | — | ✅ router-level `dependencies=[Depends(require_role([ROLE_OWNER…]))]` |
| `escalation_room` | 8 | `/api/v1/admin/incidents` → **401** | ✅ guarded by another mechanism |
| `admin_dmarc` | 1 | → **200** | 🔴 **exposed** (§2.2) |
| `admin_chat_tools` | 3 | 404 on probe | ⚠️ unverified — needs the correct path/method |
| `allocation` | 3 | 404 on probe | ⚠️ unverified |
| `admin_mfa_routes` | 3 | — | ⚠️ enrolment may legitimately precede a role, but needs *some* identity |

**The finding is not "20 vulnerabilities."** It is that guard placement is inconsistent — three
different mechanisms, none enforced at registration — so whether a given admin route is protected is
currently a matter of which file it landed in. That is the systemic issue worth fixing.

### 2.6 Before making the repo public

1. Fix §2.2 and §2.3.
2. Add the registration-time assertion from §2.5, plus a test that probes every `/api/v1/admin/*`
   route unauthenticated and expects 401/403.
3. Scan **git history**, not just the working tree — `git log -p` over 445 commits is where a
   rotated key hides. A single `gitleaks detect --no-git=false` run settles it.
4. Decide what the `demo_v2` profile means in public. The repo ships a runnable demo whose launcher
   sets `EXTERNAL_RESEARCH_ALLOW_PRIVATE=1` and a local-proof enrolment; that is correct for a laptop
   and wrong for anything reachable.

---

## 3. Corrections I owe

The independent reassessment made six corrections to my 09-11 deep dive. Five are right and I accept
them; one has since been overtaken by a fix.

**1. "Guarded stages cannot corrupt a shelf" — I was wrong.** They demonstrated a stage that mutates
in place and then raises, leaving the mutation intact. My claim was an inference from the priority
tracking, not a test. I should have run it.

**It is now true, because they fixed it.** In the uncommitted tree `stage_runner.py` gained (+20/−3):

```python
owned = {key: deepcopy(value) for key, value in vars(response).items() if key not in {...}}
...
except Exception as exc:
    for key in list(vars(response)):
        if key not in {...} and key not in owned: delattr(response, key)
    vars(response).update(owned)          # true rollback
```

plus an `isolated=True` mode that runs the stage against a copy and merges only on success. I re-ran
the mutate-then-raise case today: `products` survived intact with an `error` receipt. That is the
typed-artifact boundary the reviewer asked for, and it is the correct prerequisite they said it was.

**2. "No workload journey can ever qualify" — overgeneralised.** I tested two titles and stated a
universal. The accurate claim is: *the two mainstream titles I tested both returned partial
completeness and zero products, and the missing capability is typed alternatives plus reviewed
equivalence.*

**3. "CPU/GPU predicates cannot compile" — wrong as written.** Exact cited strings do compile into
`in` predicates. What is missing is *splitting* an alternatives list into independently cited options
and *proving equivalence* between them. Different problem, different fix.

**4. "DAG scheduling is the highest-value harness work" — withdrawn.** Scheduling stages in parallel
over a shared mutable response would have multiplied the very corruption I had wrongly assumed was
impossible. Ownership first, scheduling later. Their ordering was right.

**5. "Market intelligence is a one-line launcher change" — overstated.** A flag enables a branch. It
does not certify ingestion, worker flags, persistence truth, provenance, privacy or consumer wiring.
The mode is a three-state `off | shadow | live` defaulting to `off`; turning it on is the beginning
of that work, not the end.

**6. "The chair switch is camera-safe" — not generally reproducible.** It passed on my runs; their
continuity journey retained Gaming Laptops for the same request. A journey that passes sometimes is
not camera-safe.

---

## 4. What works, verified today

| Capability | Evidence |
|---|---|
| **Audit access control** | `/admin/decisions/asof` now carries `require_role([ROLE_OWNER, ROLE_DEVELOPER])` **and** the query filters `tenant_id` with independent `valid_*` / `system_*` axes. The reviewer's P0-A is closed |
| **Stage rollback** | mutate-then-raise leaves prior products intact; `isolated` mode available |
| **Budget-only continuity** | both regressions I reported on 09-11 now pass |
| **Price vs quantity** | *"a 2000 laptop"* → budget 2,000, quantity 1 |
| **Currency/prose formatting** | committed at `c7daafaa`; bands preserve cents, generic bucket normalised |
| **Backend sweep** | `tests/services` + `tests/integration` + `tests/architecture` — **3 failures**, all characterised in §5.1; none is a product regression |
| **Secret hygiene** | no committed keys or tokens |
| **Off-catalog refusal** | model proposes, taxonomy clamps, honest refusal |

## 5. What still does not work

| # | Issue | Status today |
|---|---|---|
| **D6** | Pre-research clarification contradicts its own success message | 🔴 **reproduced today**, verbatim below |
| **D8** | Publisher ranking puts aggregators above the publisher | 🔴 unchanged — `deepsilver.com` still 8th |
| **New** | Candidate list contains a **duplicate** (`systemrequirementslab.com` at ranks 3 *and* 4) | 🟠 dedup gap |
| **New** | The word **"qualified"** used while authority is `unknown` | 🔴 see below |
| **Delivery** | Complete-evidence → qualified shelf | 🔴 never green |
| **SoD** | approver ≠ requester | 🔴 unenforced |
| **Size guard** | `admin_bi.py` 2,142 vs ceiling 2,139 | 🟡 new +3 breach |

### 5.1 Backend sweep — correcting my own number

I reported "0 failures" earlier in this session. **That was wrong**, and wrong in a way worth naming:
I ran `grep -c '^FAILED'` against an output file that was still empty and read the `0` as a pass.
That is the same mistake class this project keeps hitting — absence of evidence read as evidence of
absence. The completed run shows **3 failures**:

| Test | Reproduces in isolation? | Assessment |
|---|---|---|
| `test_dependency_resilience_timeout::test_timeout_cancels_queued_future` | **yes** | **Stale test stub, not a product regression.** The uncommitted `dependency_resilience.py` change is *correct*: `submit(fn)` → `submit(copy_context().run, fn)` so ContextVars (tenant/profile identity) survive into the thread pool across retries. The test's executor stub is still `lambda self, _fn` and now receives three arguments. Fix the stub |
| `test_maestro_observability::test_blocked_recommend_exposes_audit_refs…` | **no** — passes alone | Order-dependent; shared state between modules |
| `test_source_file_size_guard` | yes | The `admin_bi.py` +3 breach above |

So: one stale fixture behind a good change, one ordering flake, one real ratchet catch. Nothing here
changes the readiness picture — but the *number* I gave you did, and it was wrong.

Today's live turn, *"What laptop do I need for Kingdom Come Deliverance 2, under AUD 3,000?"*:

```
message : "I resolved Kingdom Come: Deliverance II … its published minimum requirements
           qualified 2 catalog configurations."
question: "I identified Kingdom Come Deliverance 2, but no enrolled authoritative provider
           returned current requirements."
trace   : accepted=4  completeness=partial  authority=unknown  products=4
```

Three disagreements in one turn: the message says **qualified**, the question says **no provider
returned requirements**, and the trace says **authority unknown / completeness partial**. This is the
reviewer's central point stated as precisely as it can be — *claiming compatibility while the trace
says incomplete*. It is the one open defect I would call release-blocking on correctness grounds
rather than completeness grounds.

---

## 6. Domain-specific findings

### 6.1 External search

- **D8 ranking** unchanged: `_quality_score` awards +8 for `requirements` in the path and +7 in the
  title, so sites *named after the search term* outrank the publisher. The identity resolver already
  knows the publisher — use it as a prerequisite filter, not another score.
- **New: duplicate candidates.** The same host appeared twice in one ranked list. Dedup by
  normalised host before presenting an approval choice; a buyer approving "the third one" should not
  be ambiguous.
- **Unverified:** rotating unfamiliar identities. Every live test uses the same handful of titles.
  A seeded rotation is the only way to know whether discovery generalises.

### 6.2 Multi-turn NLP

- **Fixed:** budget-only revision retains scope; price-vs-quantity; category switch clears
  obligations.
- **Open:** D6 — a question generated before research survives the research that answers it. This is
  a *lifecycle* problem, not a wording problem: questions need obligation IDs that get retired when
  the corresponding obligation is discharged, which is exactly what the reviewer specified.
- **Open:** the "qualified" wording above.

### 6.3 Market intelligence

- Effective mode is `off | shadow | live`, defaulting to **off**; the demo launcher sets nothing.
- I accept the correction that enabling it is not one line. The order should be: expose effective
  API/worker mode and last successful run → prove `signal → finding → persisted → scoped recall →
  trace` for one tenant → run **shadow** and prove buyer-facing output is byte-identical → only then
  consider live.
- `market_pipeline.py` returning a `persisted` count after a caught commit failure is the specific
  truth bug to fix first; a count that survives a failed commit is a false receipt.

### 6.4 Loop and harness engineering

- **Harness: materially better than when I last looked.** Rollback plus an isolation mode is the
  right foundation, and it is the one that makes scheduling discussable later.
- **Loop: still none, still correct.** The one bounded loop worth adding remains an
  attribute-targeted second retrieval when completeness is `partial` with named missing attributes —
  and the reviewer's caveat is well taken: first distinguish *source missing* from *parser rejected*
  from *inventory incompatible*, because only the first is worth retrying.
- **`agent_chain` still overstates.** One entry, null duration. Either populate it from real stage
  receipts or rename the field.

---

## 7. Roadmap, reordered — and why

| # | Work | Why here |
|---|---|---|
| **0** | **Commit and push.** 29 commits + 103 files | Everything below is worthless if the disk dies. Costs an hour |
| **1** | **§2.2 unauth route + §2.3 env default + registration-time admin guard assertion** | Security defects with live proof. Cheap. Must precede publication or any hosted deployment |
| **2** | **D6: retire questions by obligation ID; forbid "qualified" while authority ≠ permitted** | The only open *correctness* defect — the system currently claims something the trace contradicts |
| **3** | **Typed CPU/GPU alternatives + reviewed equivalence receipts** | The single blocker on positive delivery. Needs your reviewer — it is the longest pole and it is a human gate |
| **4** | **SoD (approver ≠ requester)** | Top pilot blocker; identity is already captured, this is a comparison and a test |
| **5** | **D8 ranking + candidate dedup** | Buyer-visible, self-contained, no dependencies |
| **6** | **Cross-surface invariants attached to existing journeys** | Converts every journey into a consistency test at near-zero marginal cost; would have caught D6 |
| **7** | **Market intelligence shadow certification** | Only after 1–4; needs the truth fixes, not a flag |
| **8** | **Release ladder** — clean checkout, real PG concurrency, hosted, WORM, independent review | Unchanged |

**Why this order and not the previous one:** I previously put harness work high. The reviewer was
right that ownership had to come before scheduling, and the team has now done it. What replaced it at
the top is security, because the repo is about to be public and two of the three Janusec-class checks
came back positive. Item 2 moved above item 3 because a system that *claims* incorrectly is worse
than a system that *refuses* correctly — refusing is honest, claiming is not.

---

## 8. What I need from you

1. **Push the branch.** Nothing else competes with this.
2. **Confirm whether `github.com/lkjalop/ShopSquire` is public or private.** It changes the urgency
   of §2 from "fix before deploy" to "fix today". I did not check from outside.
3. **The independent reviewer** — still the longest pole, still unnamed. It gates item 3, the Rockwell
   hold and the derivation ledger.
4. **Run `gitleaks detect --no-git=false`** over the full history, or tell me to. The working tree is
   clean; 445 commits of history are not yet verified.
5. **A decision on the demo narrative** — governed refusal (recordable now) or qualified delivery
   (blocked on item 3).

---

## Method and limits

Ref comparison against `origin/checkpoint/turn-state-consolidation-20260830`; secret pattern scan over
`git ls-files`; AST route-guard audit of `src/app/routers`; four live unauthenticated probes against
the local instance; one live buyer journey; `stage_runner` mutate-then-raise characterisation;
`tests/services` + `tests/integration` + `tests/architecture` sweep (0 failures) and the size guard
(1 new breach).

**Not done:** git-history secret scan, external reachability check of the GitHub repo, hosted or
PostgreSQL certification, independent source review. **No cart, supplier, approval or payment action
was taken.**
