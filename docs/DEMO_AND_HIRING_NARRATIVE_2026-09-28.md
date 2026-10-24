# ShopSquire demo and hiring narrative

## What the project is

ShopSquire is an AI-assisted commerce and procurement prototype, evaluated as a fictional
electronics shop. It uses a reconciled catalogue, synthetic operational data and fake external
providers. The engineering focus is preserving evidence, buyer intent and authorization across
changing requirements and uncertain execution.

It is a portfolio project, not a deployed retailer. The work can be valuable without real customers,
real supplier access or payments. Synthetic data supports reproducible correctness experiments;
it cannot establish real demand prediction, business ROI or production adoption.

## What can be shown now

| Demo | What to show | Accurate claim |
|---|---|---|
| Scoped fictional recommendation | Open `http://127.0.0.1:5177/?surface=qualified-shop`, start a case, select Fictional Memory Lab, inspect the product shelf and trace, reload, expire the evidence, then revoke selection. | The actual compiler and catalogue projection support a bounded RAM-only fictional qualification. Persisted selection and evidence validity control the result. It does not certify Blender or any real product. |
| Bulk request arithmetic | Open `http://127.0.0.1:5177/?surface=electronics-shop`; compare 30, 40 and 100 units. | Existing catalogue identities connect to illustrative stock and supplier terms. Quantity changes update shortfalls and totals without authorizing purchases. These are read-only scenarios, not accepted order amendments. |
| Recoverable requirement loading | Show the `requirement-load-recovery.spec.ts` Playwright recording and test. | A deliberately failed read displays an error; explicit retry reloads real API state and permits subsequent selection. The test injects the network fault and does not mock a successful response. |
| Inventory and authorization integrity | Walk through focused tests and their database assertions: concurrent reservations, duplicate return, rollback, self-approval through two credentials, revoked grant and uncertain send. | These service boundaries have regression evidence. Complete authenticated operator UI and connected checkout/supplier workflows remain unfinished. |
| Honest endurance investigation | Show the failed overnight status, cycle 352 trace, browser error, new resource sampling and rerun status. | The original run passed 351 cycles before a browser network-buffer failure after 7h11m51s. It did not pass eight hours. The original cause remains unresolved; UI recovery is not proof that resource exhaustion is fixed. |

The demo URLs require the isolated local API and frontend running. Historical recordings are useful
fallbacks but should be identified as recordings, with the code/data version and date retained.

## A six-minute demo today

1. **30 seconds:** describe the fictional shop and the engineering question: can an AI-assisted workflow
   keep evidence and permission correct when the request or environment changes?
2. **Two minutes:** run the fictional qualification journey. Show the explicit scope, supporting trace,
   reload, evidence expiry and revocation. Explain why a qualified recommendation grants no commerce authority.
3. **One minute:** compare the 30/40/100 scenarios. Explain why a volume discount can lower unit cost while
   increasing total spend and why supplier capacity is different from stock on hand.
4. **One minute:** show a focused test for concurrent no-oversell and a test rejecting one person's second
   credential as independent approval. Explain the durable state assertions, not just the green test count.
5. **One minute:** show the overnight failure and the diagnostic response. Explain what was observed,
   what remains unknown and what the next run measures.
6. **30 seconds:** state the next integration milestone: accepted buyer revision through stock,
   supplier conversation, separate approval and recovery, using fake providers.

## What becomes demonstrable after the remaining gates pass

The intended connected demonstration is:

**Buyer specifies needs → evidence-backed scoped recommendation → optional compatible bundle →
30-unit order with a shortfall → simulated supplier enquiries and reviewed replies → buyer accepts
40 units → stock, delivery and total cost recalculate → an independently authenticated simulated
operator approves the exact action → fake provider times out after possible acceptance → operator
reconciles the outcome without a duplicate action → merchant explains a replenishment decision.**

Prove each arrow through actual API/UI behavior and durable state assertions before presenting it
as implemented. During the demo, also try self-approval, a stale quote, revoked consent and an injected
supplier instruction. Unsupported actions should be blocked with inspectable reasons.

Once those gates pass, an accurate claim would be: “I built and evaluated an end-to-end simulated
commerce workflow with evidence-backed recommendations, revision-aware procurement, independent
approval and recovery from uncertain provider outcomes.” Qualify the tested scenario and providers.
Do not convert that into a claim of production readiness or general safety against all attacks.

## How to articulate the engineering experience

Use statements you can personally explain and defend. Development used coding-agent assistance;
describe your own architecture decisions, review, debugging and validation rather than implying
every line was independently hand-written.

| Skill | Defensible wording | Evidence to explain |
|---|---|---|
| TDD | “I used test-first changes for selected failure boundaries, recording a failing regression before implementing the fix.” | Requirement-load cancellation/retry, dispatch-time approval expiry, inventory replay/rollback and reconciliation. Do not claim the entire repository was built through TDD. |
| Testing | “I combined service tests, transaction/concurrency tests and real-API Playwright clickthroughs, with synthetic providers at external boundaries.” | Explain which tests use mocks, which use a real database/API, and what each cannot prove. |
| Harness engineering | “I built reproducible fixtures and a duration-aware browser harness that preserves traces, failures, source fingerprints and resource measurements.” | The harness must fail on source changes or failed cycles. Actual long-run results and harness unit tests are different evidence. |
| Loop engineering | “I designed and tested bounded propose–validate–approve–execute–observe/recover behavior, including stale-state rejection and stopping conditions.” | Show the implemented boundaries; describe the full integrated loop as unfinished until its connected tests pass. The term has no single standard definition, so explain the behavior. |
| Reliability engineering | “I investigated a long-running failure, preserved the failing trace and added diagnostics rather than declaring a shorter run successful.” | Chromium `ERR_NO_BUFFER_SPACE`, the missing historical resource measurements and the instrumented rerun. Do not claim the cause is fixed yet. |
| Security engineering | “I separated untrusted content from authority and tested tenant, identity, exact-effect and revocation boundaries.” | Two credentials belonging to one person cannot satisfy independent approval. A supplier reply does not grant purchase authority. Full adversarial evaluation remains open. |
| CI/CD | “I have experience building local validation and CI workflow definitions; remote pipeline and release/rollback evidence are still being completed.” | Observed remote runs, enforced branch checks and demonstrated deployment/rollback are needed before claiming mature CI/CD operation. |

### Interview introduction

“I’m building ShopSquire, an AI-assisted electronics commerce prototype. My focus is making the
workflow inspectable and controlled: recommendations need scoped evidence, changing requirements
invalidate old decisions, and external actions require explicit authorization. I use regression
tests and real-browser checks to validate those boundaries. It runs against a fictional shop with
synthetic providers, so I distinguish demonstrated software behavior from claims about real customers
or production performance. One useful lesson came from an overnight browser run that failed after
seven hours: I retained the failure and added resource diagnostics rather than calling it a pass.”

### Possible CV bullets today

- Developed an AI-assisted commerce prototype with persisted requirement contracts, evidence-validity
  checks and inspectable recommendation traces, validated through real-API Playwright journeys.
- Implemented and regression-tested transactional inventory effects and exact-message approval
  boundaries covering concurrency, replay, rollback, revocation and same-person multi-credential rejection.
- Built a duration-aware browser evaluation harness and investigated a failure after 351 successful
  cycles; added request recovery and process/network resource diagnostics for follow-up testing.

Avoid “production-grade,” “autonomous purchasing platform,” “eight-hour certified,” “proven ROI,”
“best model,” “fully prompt-injection-proof” or “complete CI/CD” unless specific later evidence supports
the wording. Current qualification is explicitly fictional; no real product was newly qualified.
