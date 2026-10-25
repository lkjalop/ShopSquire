# Independent review of Claude's publication, security and roadmap assessment

15 September 2026. Reviewed current working tree at HEAD `c7daafaa`, remote refs, the public GitHub page, source code, isolated security reproductions, the source-size guard and a fresh KCD2 browser journey. This is an assessment, not a deployment or implementation instruction. No application code was changed or pushed during this review.

## Verdict

Claude is right to elevate security and contradictory qualification claims. However, parts of the report are stale, several assurances exceed the evidence, and two proposed fixes are too narrow. The largest newly verified security concern is a demo route disclosing the configured owner credential under a spoofable local-host check. The main correctness concern remains a terminal response that claims qualification without qualifying evidence.

My own previous seven passing browser journeys did not cover KCD2. They remain valid receipts for those scenarios, not proof that all workloads are consistent. The source-size guard also currently fails; my earlier targeted validation did not include it.

## What I confirmed or corrected

| Claude's claim | Current assessment |
|---|---|
| 29 unpublished commits, 267 files, +21,943 / -2,894 | Confirmed relative to `origin/checkpoint/turn-state-consolidation-20260830`. Remote still reports `87987967` for that branch. |
| That is the published tip | Too broad. GitHub's default branch is `wip/docker-real-env-20260213`, with remote HEAD `7256df31`. Publication comparisons must name the branch. |
| Repository visibility unknown | It is **public**, verified without authentication on [GitHub](https://github.com/lkjalop/ShopSquire). Public source does not establish that an application deployment is internet-accessible. |
| 103 dirty files; 445 commits to scan | The current pre-report working-tree count was 104. Local HEAD has 1,897 reachable commits; all local refs have 1,910. A complete history scan cannot be described as 445 commits without explaining that scope. |
| No committed secrets | Not established. A limited current-file pattern scan supports only “no matching secrets found by that scan.” History, other refs, logs, recordings, personal data and unsupported credential formats remain outside that assurance. I did not run a full secret scanner; no `gitleaks` executable was available. |
| Unauthenticated DMARC summary | Confirmed in an isolated router reproduction. No credentials returned 200. A zero threshold triggered the intercepted SIEM emitter. No real SIEM message was sent. The current registration is in `main.py:2225`, not the cited admin router group. |
| Missing environment activates default credentials | Confirmed for unset **and empty** `APP_ENV`. Explicit production and a misspelling such as `prodution` reject the fallback: the report's assertion that a misspelling also restores it is incorrect. |
| Stage rollback now works | Supported within response-owned state. It is not rollback of shared-envelope mutations, database commits or external effects. |
| Typed CPU/GPU alternatives still need splitting | Stale. Current grounding splits slash/“or” alternatives with individual source spans. Reviewed hardware equivalence and broader grammar coverage remain open. |
| Complete-evidence delivery never green | Stale as an integration claim. Seven browser contracts passed, including live Steam evidence delivering a visible qualified **synthetic** configuration. Real sellable inventory qualification remains unproven. |
| KCD2 claims qualification while evidence is incomplete | **Reproduced on the repaired runtime.** Details below. |
| `admin_bi.py` exceeds its size ceiling by three lines | Confirmed: 2,142 against 2,139. This is a real failing repository guard, though not itself a security vulnerability. |
| Separation of duties is a comparison and a test | Underestimated. Shared API keys produce `key:<role>` identities. Independent-person approval requires authenticated principals, tenant membership, immutable requester identity and revision-bound approval. |
| Market pipeline can falsely report persistence | Confirmed in code. It returns its precomputed counts after a caught commit failure. Separate history writes can already have committed, adding a partial-durability problem. |

## Security priority: broader than the DMARC endpoint

### A. Configured owner key disclosed by the email-lab handler

Evidence:

- [Local-host test](../src/app/routers/merchant_dashboard.py:59) trusts the caller's Host header using `startswith`.
- [Email-lab route](../src/app/routers/merchant_dashboard.py:871) accepts that result without a role dependency or an explicit development-environment requirement.
- [Credential loading](../src/app/routers/merchant_dashboard.py:882) reads `OWNER_API_KEY`.
- [Cookie response](../src/app/routers/merchant_dashboard.py:3201) returns that key with `httponly=False`.

In an isolated handler test, with `APP_ENV=production`, a synthetic remote client and a synthetic owner key, a Host value starting with `localhost` was accepted. The response was 200 and contained the configured synthetic key in the JavaScript-readable API-key cookie. No actual credential was printed or copied into the evidence.

This is more serious than a broken development-key literal: it can disclose the **configured** credential. External exploitability depends on ingress routing and network exposure, which were not tested. A reverse proxy can also make peer-address-only “local” checks unreliable. Disable the route outside explicit development and remove automatic credential disclosure; do not rely on Host or peer locality as operator authentication.

Claude's suggestion to replace literal keys with runtime-injected keys is unsafe if it means inserting a server owner secret into browser code. Use an authenticated session or a deliberately provisioned, appropriately scoped credential instead.

### B. DMARC needs authentication, tenant scope and truthful metrics

[The handler](../src/app/routers/admin_dmarc.py:30) needs authorization, but that alone is insufficient. [The summary service](../src/app/services/dmarc_ingest.py:132) has no tenant filter, ignores its `days` argument and aggregates the whole dataset. Its fail-rate calculation divides failed message counts by report counts, mixing units; that ratio can exceed one.

Recommended contract:

1. Unauthenticated callers fail before the handler, database access or emitter executes.
2. Authenticated tenant A cannot read tenant B's reports.
3. The requested reporting window is applied.
4. Fail rate uses a consistent message denominator and has explicit no-data semantics.
5. Reading a dashboard does not itself produce repeatable SIEM alerts. Alerting runs through a bounded, deduplicated job with server-owned thresholds.

### C. Registration enforcement must cover actual mounted routes

Audit the final FastAPI route/dependency graph, including nested dependencies, mounts and all HTTP methods. Use explicit, reviewed identity-bootstrap exceptions where required. An AST rule looking only for `require_role` in a route signature misses inherited guards and alternative authentication mechanisms.

The email-lab finding is outside `/api/v1/admin`, so an admin-prefix-only assertion would not catch it. Enforce privileged capability boundaries as well as route naming. Exercise unauthorized requests in isolated tests with handlers and external effects intercepted; do not blindly POST to every real route.

## Fresh KCD2 result and why it matters

Query: “What laptop do I need for Kingdom Come Deliverance 2, under AUD 3,000?”

The current isolated browser returned:

```text
accepted claims:        5
rejected claims:        2
missing requirement:    os
completeness:           partial
catalog authority:      unknown
failure code:           publisher_not_yet_accepted
qualified shelf items:  0
visible message:        published minimum requirements qualified 2 catalog configurations
question:               no enrolled authoritative provider returned current requirements
```

The contradictory qualification sentence appears both in the terminal/read-model response and on screen. Claude's exact count of four accepted claims is stale, but the defect is current.

Relevant weaknesses:

- [Research outcome](../src/app/services/research_outcome.py:429) converts partial completeness to a blocked result only when incoming authority was already `permitted`; unknown authority follows another path.
- [Terminal narration](../src/app/services/terminal_research_narration.py:61) has early returns and a narrow `requirements_incomplete` failure-code branch. Another failure code can preserve an unsupported earlier sentence.
- [Terminal catalog gate](../src/app/services/terminal_research_reconciliation.py:86) does not generally distinguish exploratory candidates from qualified recommendations when authority is unknown.
- `TerminalCatalogGate.recommendation_status` infers “qualified” from nonempty products/shelves under permitted authority, rather than checking individual qualified fit verdicts. Permission to evaluate the catalog is not proof of product compatibility.

**Fix the semantic contract, not a keyword.** “Not qualified” is valid narration, and removing the word “qualified” would still leave equivalent unsupported claims such as “this runs your workload.” Compute explicit qualified configuration IDs from current, tenant-bound fit evidence. Narration, cards, counts, questions and actions consume that one revision-bound result. Commerce permission remains a separate gate.

Retire obligations individually. Five accepted attributes mean “no provider returned requirements” is inaccurate, but an unresolved OS requirement must remain visible. Ask for the missing requirement or source decision rather than deleting all clarification questions.

## Discovery and real product delivery

The [discovery scoring](../src/app/services/open_world_research_discovery.py:98) still uses lexical hints, including “requirements” in titles and paths. I verified the mechanism, not a fresh external ranking proving Deep Silver is exactly eighth.

The candidate map deduplicates by raw URL, not by publisher identity. Two URLs on the same host are not necessarily duplicate evidence. Canonicalize tracking/fragment variants and group approval choices by verified publisher identity/origin, while retaining distinct version/language/platform documents. Blind host-only deduplication can discard the needed requirements page. A known publisher name is not itself a verified publisher-domain mapping.

For delivery, prefer a small, evidence-complete real catalog cohort before broad equivalence work. Exact CPU/GPU names, mobile versus desktop variants, OS/architecture, storage, stock, price and workload version all matter. More VRAM alone is not evidence of GPU equivalence. An independent reviewer may be needed for the chosen governance policy; not every literal parser improvement requires human approval.

## My reordered roadmap

| Priority | Work | What counts as green |
|---|---|---|
| **0A — preserve now** | Make an access-controlled off-device backup of commits **and dirty/untracked work**, then validate restoration. | A recoverable snapshot exists independently of this laptop. A push of existing commits alone does not preserve dirty files. |
| **0B — security containment** | Remove email-lab credential disclosure; guard DMARC; make unset/empty environment fail closed consistently; review other local/demo bypasses. | Synthetic hostile-host, unauthenticated, invalid-credential and cross-tenant tests fail before any privileged read/write. No privileged server key is returned to browsers. |
| **1 — publication hygiene** | Scan current tree and complete reachable history; inspect logs, traces and documents for secrets and personal data. Commit reviewed slices and publish to the intended branch. | Scanned, reviewable commits; remote SHAs match; clean checkout reproduces them. Publication is separate from deployment. |
| **2 — terminal truth** | Repair the KCD2 authority/narration/question inconsistency and add cross-surface invariants in the same change. | Unknown/blocked/partial cases make no positive compatibility claim; qualified count matches actual fit verdicts; unresolved obligations remain accurate. Include multiple titles and renamed/unfamiliar subjects. |
| **3 — real evidence cohort** | Supply fresh exact-configuration evidence for a small real catalog; add only evidence-backed equivalences. | At least one real product completes the live journey; missing, stale, conflicting or incompatible evidence cannot qualify it. |
| **4 — approval integrity, before sends** | Enforce stable requester/approver identities, separation of duties, content/revision binding and tenant membership. | Same requester, shared/unknown identity, stale approval, changed payload and cross-tenant approval are rejected. Distinct authorized principals succeed once. |
| **5 — discovery quality** | Publisher identity receipts, canonical URL handling, grouped candidate choices and seeded unfamiliar-workload coverage. | Approved-origin choices are unambiguous; distinct evidence documents survive deduplication; ranking cannot grant authority. |
| **6 — market durability and shadow** | Repair commit receipts and separate-sink consistency before enabling market use. | Commit failure cannot report durable success; retries are idempotent; tenant-scoped shadow execution does not alter buyer decisions or actions. |
| **Release track — start early, require before autonomy** | Fix source-size guard; run clean-checkout CI, full PostgreSQL migration/restore checks, HTTP concurrency and measured-quality gates; enforce hosted required checks. | Actual workflow runs pass, approved evaluator measurements exist, restore succeeds and repository protections prevent bypass. |

Separation of duties moves ahead of item 3 whenever real supplier sends are being enabled. Source-size cleanup belongs in the next affected commit, not at the expense of security or correctness. WORM retention is a later policy-driven control; it does not compensate for false receipts or weak authorization.

## Assessment limits and evidence

No public app exploitation, cart/supplier/payment actions, real SIEM emission, source-code fix, commit or push was performed during this review. Public repository visibility was checked; public application reachability was not. I did not rerun the entire backend suite or certify the entire repository free of secrets or authorization defects.

Receipts under `C:/AI/ShopSquire-checkpoints/audit-2026-09-15`:

- `claude-review-kcd.json` / `.log`: terminal result, read model and visible browser text.
- `claude-review-security.log`: isolated DMARC and credential-default checks.
- `claude-review-email-lab.log`: production-mode synthetic credential-disclosure reproduction.
- `claude-review-size.log`: current failing source-size guard.
- `repair-browser-final.json`: earlier seven passing journeys, with their narrower scenario coverage.

**Overall:** retain Claude's security-first and truth-before-capability principles. Replace “push everything first,” “secrets clean,” “alternatives not implemented,” and “SoD is one comparison” with the evidence and boundaries above. The next investment should make claims and authority consistent across the product, not add more agents or parallel stages.
