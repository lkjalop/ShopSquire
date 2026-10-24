# Price versus quantity correction — partial verification

## Reproduced

Screenshot 038: `need help with a 2000 laptop for digital twin?` bypassed the
budget grammar's verb-gated singular-price branch. Commercial parsing then
treated 2000 as quantity. Screenshot 039: `i mean a $2000 laptop?` rejected a
fresh conflicting count but inherited the erroneous prior count again.

## Changed

- Budget grammar recognizes the existing article-led price construction without
  a fixed list of preceding verbs/prepositions.
- BudgetParse exposes whether its source span describes a single item.
- Core honors this current singular fact before pending-question inheritance,
  provided no independent explicit bulk quantity was parsed. It sets quantity
  one and per-unit budget scope. No product-name exception was added.
- Added a seeded core regression with retained quantity 2000 and pending
  budget-scope question. It failed before the change and passes afterward.
- Added the exact three-turn real-browser regression with budget, quantity,
  terminal consistency, forbidden inflated totals and absent bulk controls.

## Verification

- 206 affected core/budget/continuity tests passed, no skipped tests in the
  reported run: screenshot-039-green.xml/log.
- Exact three-message browser test passed, one worker, zero retries, 1.1 minutes:
  price-correction-browser.log and price-correction-browser/.
- API restarted from verified PID 36108 to 45028 on the existing isolated demo
  profile. No other service was stopped.
- Saved terminal payloads retained the digital-twin research purpose across the
  correction and per-item reply. No 2000-unit or million-dollar narration appeared.

Artifacts are outside Git under C:/AI/ShopSquire-checkpoints. Existing dirty work
was preserved; no commits, source approvals, supplier sends or payments occurred.

## Remaining defect found by inspecting the passing browser test

The first answer says `$2,000 is ample for general` / `Strong fits start at $629`
while the same terminal research state is context-only and asks which named
digital-twin software and version must run locally. Retaining the workload's text
does not prove that the response uses it correctly. This semantic-role/research/
narration disagreement remains uncorrected; the price test is not a workload-fit
certificate. The next regression must reject confident compatibility/budget-fit
language while applicable workload obligations remain unresolved, without letting
historical workload evidence override a genuinely unrelated purchase.

The seeded backend test repairs a previously contaminated case; the live test
starts fresh. Live correction of a pre-existing contaminated stored case and
complete trace-leaf semantics are not separately certified by this run.

## Follow-up: context-only narration repair

The generic affordability answer survived because terminal narration returned early
for `PROCURE_SUBJECT`, even when the current exploration was explicitly context-only.
The purchased laptop and its unresolved host workload are not mutually exclusive.

`terminal_research_narration.py` now consumes the current exploration supplied by
chat's transition boundary. A case-matched `context_only` result suppresses earlier
fit/budget-sufficiency claims before the purchase-role shortcut. It does not use a
software-name rule, change accepted claims, or lower compatibility authority.
Historical exploration with a different case does not override the current answer;
the existing unrelated-purchase boundary clears current exploration.

Verification:

- Three new regressions failed before implementation; focused budget, transition
  and narration suite: 46 passed, zero failures/errors/skips.
- Research outcome, reconciliation and subject-switch suite: 31 passed, zero
  failures/errors/skips.
- Exact three-message browser journey: passed, one worker, zero retries, 1.1 minutes.
  Saved payloads at revisions 2/3/4 show quantity 1, retained digital-twin context
  and explicit inability to confirm compatibility or budget sufficiency.
- API restarted onto these changes, verified PID 45028 replaced by 22860; same
  isolated demo profile. Source-size guard and diff check exit zero, with existing
  size warnings and unchanged ceilings.
- Extended browser gate also passed (1.2 minutes, zero retries): exact rendered
  answer, trace revision and accepted/held counts after each correction turn,
  followed by a chair purchase that did not inherit the workload warning.
  Evidence: `context-narration-rendered-browser.log` and its trace/video directory.

Artifacts: `C:/AI/ShopSquire-checkpoints/context-narration-*` and
`context-reconciliation.*`. This is a narrow narration/continuity repair, not a
complete evidence-to-qualified-product or production certificate. Full trace-leaf
semantics, normalized obligation dispositions, typed compatibility and hosted
certification remain separate work. Existing dirty changes are preserved;
no commit, approval, supplier send or payment was performed.

## Formatter follow-up checkpoint

The later screenshot verification correctly identified two remaining direct-call
defects: `general` leaked into bulk prose and a float cap printed as `$2,000.0`.
Parser-independent regressions reproduced these before changes. Bulk prose now
normalizes the generic bucket; budget bands drop only redundant `.00` and preserve
cents in catalog prices and derived per-unit caps.

Checkpoint `c7daafaa` contains only the two formatter changes and their dedicated
regression file (three files). It excludes the earlier parser, routing, trace,
connector and browser changes, which remain uncommitted. No push occurred.

- Working-tree targeted suite: 59 passed, no failures/errors/skips.
- Isolated HEAD plus checkpoint: 57 passed, no failures/errors/skips (the working
  tree additionally has two prior budget-parity cases).
- An initial partial-staging offset error was caught by the clean-checkout tests;
  the corrected checkpoint was rerun successfully before committing.
- Real-model browser run: two tests passed in 1.7 minutes, one worker, zero retries.
  Covers the three correction turns plus chair switch, and a genuine 50-laptop
  AUD 60,000 total-budget request with rendered quantity/currency assertions.
- API restarted onto the changes (PID 52768). No supplier/cart/payment action.

Evidence remains outside Git: `C:/AI/ShopSquire-checkpoints/format-*.xml`,
`format-*.log`, `formatter-browser.log` and `formatter-browser/` (trace/video).
The isolated verification worktree is retained at `formatter-clean-check/` for
inspection. This checkpoint is not certification of the remaining dirty tree.
