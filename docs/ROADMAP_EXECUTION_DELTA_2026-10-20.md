# Execution checkpoint after `559aea5a` — 20 October 2026

Execution continues against the [complete roadmap](ROADMAP_DELTA_AND_IMPLEMENTATION_PLAN_2026-10-20.md). Ten application commits after `0d551213` change 67 files: 3,094 insertions and 889 deletions, including lockfile and test changes. These figures are not feature-completion percentages. The release gate remains **red**.

The [execution manifest](audits/2026-10-20-execution-delta.json) records commands, native exits, resource peaks and receipt hashes. Exact-source profiles overlap; do not sum their passes.

## Verified changes

| Commit | Result | Verification and limits |
| --- | --- | --- |
| `1d9a1408` | Release incident transactions before alert/trace writes; capture the owning engine, join scheduler shutdown and bind tenant per transaction. | Complete exported candidate: 22 passes. Distributed scheduler claims and wider error/locking paths remain open. |
| `da532ace` | Native buyer ownership/tenant guards, failure-closed membership lookup and frontend type prerequisites. | Exact candidate: 11 backend and 385 frontend passes; clean frontend install, types/build and audit pass. The complete authorization matrix remains separate. |
| `ec383e17` | Router outages retain pending workloads; literal replacement remains distinct. | Exact candidate: 54 passes; root targeted profile: 57. Full five-turn browser transition matrix passes. |
| `0474709b` | Trusted attachments retain their owned case despite an interpreter's switch suggestion. | Exact API regression passes; original PDF/text browser checks subsequently pass. |
| `3c19dd49` | Regenerate six upgraded Python profiles; repair lock-group markers, callbacks and nested admin authorization. | Exact candidate: 32 passes. Windows API/test installation matches all pins and passes `pip check`; six profile audits report zero matches. Vision namespace and Linux-install gates remain open. |
| `cd7df1e8` | First and replacement uploads bind proposal and response to the final owned case. | Three API cases pass on the exact exported source. Continuation keeps its case; genuine replacement gets a different case. |
| `b590323d` | Own ASGI worker cleanup, preserve startup errors, borrowed engines and process tracing, and bound metric cardinality. | Complete exported candidate: 26 passes, including real lifespan shutdown and required-startup failure. |
| `36007573` | Initialize SQLite compatibility schema once per live pool; retry failure, correct table/column order and preserve duplicate-insert integrity. | Exact combined candidate: 28 passes. Opening a subsequent request session emits no schema writes while another writer owns a transaction; before repair it attempted 128. Explicit upsert still works. |
| `037a9028` | Deliver scoped current market citations; distinguish blocked evidence from provider failure; remove schema mutation from finding reads. | Exact upgraded-runtime candidate: 72 passes. Controlled stored evidence does not certify live external coverage. |
| `559aea5a` | Ordinary chat delivers drafts and market reads without advancing the material revision. Client ordering accepts a new read at that revision and rejects stale/duplicate responses. | Exact candidate: 31 backend and 386 frontend passes; clean frontend install, types and build pass. Live conversation replay passes with unchanged application-source fingerprint and commercial-effect snapshot. |

After the handoff, four additional browser profiles pass: six conversational qualification cases, four upload cases, the transition matrix and the simulated supplier-enquiry journey. These are 12 named cases, not a replacement for the broad browser gate.

## Requested workflow: observed behavior

The live replay submits 30 FreeCAD laptops, consents to external search, amends to 40 units at AUD 1,500 per unit for Sydney, requests a draft and market intelligence, and checks recall after reload. Identity and those facts survive. Draft and market reads preserve the material revision and create no commercial effects.

That replay produces a **provisional 40-unit draft**: it has no accepted product selection or supplier contact, so its exact shortfall is unresolved. The response names the missing inputs. A separate API case with a current accepted 40-unit selection and a real 25-unit reservation produces the exact **15-unit** draft. Expired reservations, foreign tenants and similar-looking IDs cannot supply coverage. A fully covered request does not draft a zero-unit quote.

The live market result is **blocked: `no_current_scoped_evidence`**, without invented citations. Controlled API/provider tests deliver current cited findings in the same owned case. An enabled live source yielding useful current market observations remains work. A blocked result does not close that requirement.

No email, purchase, payment or ERP action was authorized by these reads. No commits were pushed.

## File and line assessment

The refreshed [file inventory](audits/2026-10-20-execution-file-inventory.csv) mechanically reads and fingerprints **5,648 eligible files and 973,663 text lines**. Generated October audit outputs are excluded to avoid counting the inventory itself. Eligibility differs slightly from the earlier snapshot, so totals are not a clean code-growth comparison. This is not manual semantic certification of every line.

All eligible Python files parse. Structural priorities remain:

| Current source | Size of main operation | Why it remains work |
| --- | ---: | --- |
| [Chat](../src/app/routers/chat.py) | `_chat_query_impl`: 4,527 lines, 561 branch nodes including nested code. | Routing, evidence, persistence and response construction remain coupled. |
| [Application factory](../src/app/main.py) | `create_app`: 2,205 lines, 352 branch nodes including nested code. | Targeted ownership repairs do not establish every startup/error path. |
| [Email security](../src/app/security/email_security.py) | `evaluate_email_security`: 2,021 lines, 315 branch nodes including nested code. | Detection, policy and persistence need independently tested boundaries. |
| [Turn router](../src/app/services/recommendation_core/turn_router.py) | `_route_turn_raw`: 1,343 lines, 205 branch nodes including nested code. | Many fallback paths still interact. |
| [Merchant dashboard](../src/app/routers/merchant_dashboard.py) | `merchant_email_lab`: 2,328 lines, largely markup. | Extract presentation; size alone does not demonstrate a logic defect. |

There remain **99 production functions over 200 lines**, **5,605 broad exception handlers** and **2,044 pass-only handlers**; the earlier snapshot had 2,116 pass-only handlers. These are review candidates, not proved defects or a quality percentage. The direct-call async heuristic finds zero matches; it does not detect every indirect call or synchronous SQL operation.

The inventory observed **574 dirty paths: 280 tracked changes and 294 untracked paths**, with none staged. Runtime evidence changes that count between observations. Existing work is preserved; the remaining tree is not an integrated release.

## Gaps and why

| Roadmap | Remaining work | Why targeted results do not close it |
| --- | --- | --- |
| W00 integration | Review remaining module, router, migration, fixture and CI dependency groups; export/test coherent candidates. | Root success can depend on uncommitted modules. Hundreds of mixed changes remain. |
| W01 runtime | Failing requests/security writes, competing transactions, remaining scheduler owners and endurance. | The historical 151.56-second security request is not closed by the schema cache. A separate early task implementation hit its backstop under the old environment; its stack did not establish a SQL cause. Required persistence arguments were corrected and successful paths now pass, but general exception-path coverage is still needed. |
| W02 dependencies | Resolve the combined vision environment's shared OpenCV namespace, exercise image/OCR capabilities and Linux clean installs, assess remaining optional/ML packages. | Zero advisory matches and `pip check` do not validate shared binary namespaces, models or every Poetry package. |
| W03–W04 evidence/transitions | Stale response, foreign owner, double acceptance, reload and enabled official-research cases. | Offline acceptance remains provisional; successful corroboration requires its separate provider profile. |
| W05 draft | Exact accepted-stock shortage in the ordinary browser path; mixed amendments, provider faults and recovery. | Exact 15-unit output passes API/stock tests. The live conversation has no accepted selection and correctly remains provisional. Sending requires its separate explicit approval workflow. |
| W06 market | Useful cited live observations; conflicting/expired/foreign evidence and failed sources; unchanged commercial state. | Controlled citation delivery passes; live market replay has no admissible current findings. |
| W07 privacy/memory | Multiple HTTP workers, erasure during failure, worker replacement/recovery and every retained data plane. | Earlier owned-Redis tests do not certify complete API erasure or backup policy. |
| W08–W10 commerce | Existing inventory reconciliation, concurrency/expiry, approvals, supplier recovery and restore/rollback. | Simulated targeted journeys do not establish every operational invariant. |
| W11–W13 security/architecture/CI | Required security profiles, broader browser contracts, service boundaries and clean-checkout checks. | Historical failures/skips and mixed-tree prerequisites remain. |
| W14–W15 release | Freeze one integrated source/dependency candidate; run full required suites, restore/rollback and endurance. | No final-source full release run has passed. Historical Python had 7,836 passes, 36 failures and eight errors; historical broad browser accounting was 49 passes, 80 failures and 32 skips. Do not combine these with targeted current passes. |

OpenCV's maintainers specify that only one wheel distribution should supply the shared `cv2` namespace. The combined locked vision profile currently installs three. This compatibility gap remains even if metadata/advisory checks pass. [OpenCV packaging instructions](https://pypi.org/project/opencv-python/)

## TDD and the meaning of green

A named gate is green only when its intended assertions run on the identified source and installation, the native command exits zero, required cases are not skipped and resource limits hold. Zero selected tests, missing fixtures, unavailable required providers, timeouts and changed source snapshots cannot certify a gate.

Valid red-before evidence covers scheduler transactions, membership failure, workload continuity, evidence binding, lifecycle cleanup, duplicate inserts/schema contention, market delivery and ordinary chat task output. Invalid setup attempts remain separate evidence: a missing test filename and an unbound SQL fixture parameter are not product regressions.

One runtime-candidate rerun initially reused the previous JUnit destination, overwriting that failing XML. Both native logs/receipts survive; the successful XML was copied to the complete profile with an explanation. The runner now rejects a JUnit destination outside its current profile. This evidence limitation remains recorded.
