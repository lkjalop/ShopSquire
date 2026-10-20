# Execution checkpoint - 20 October 2026

Later execution is recorded in the [21 October checkpoint](ROADMAP_EXECUTION_STATUS_2026-10-21.md). The figures below describe this earlier snapshot.

Execution continues against the [complete roadmap](ROADMAP_DELTA_AND_IMPLEMENTATION_PLAN_2026-10-20.md). Through `18e3f469`, seventeen local commits follow `0d551213`: sixteen implementation/test commits and one documentation checkpoint. The production-source delta is 26 files, 1,341 insertions and 492 deletions; tests change 26 files, with 1,876 insertions and 220 deletions. Frontend changes span 15 files, with 76 insertions and 14 deletions. Lockfiles, generated requirements and documentation add further text changes. None of these figures measures feature completion. The release gate remains **red**.

The [execution manifest](audits/2026-10-20-execution-delta.json) records commands, native exits, resource peaks and receipt hashes. Exact-source profiles overlap; do not sum their passes.

## Latest runtime and dependency delta

| Commit | Result | Verification and limits |
| --- | --- | --- |
| `ea4442a6` | Rebuild task display projections from canonical facts instead of a saved view. | Exact candidate: 18 passes. Corrupt and schema-valid stale views cannot replace the current quantity or restore cached commerce authority. |
| `ab4b7296` | Observer persistence owns its engine, tenant and sessions; waits until the caller's outer transaction ends. | Exact candidate: 14 passes. Pending business work and active shared-connection SQLite transactions survive rollback; an asynchronous worker does not retain the request. |
| `f24159df` | Replace collection-time security-test database mutation with a runtime fixture. | Exact candidate: 22 passes across chat/evidence and security tests. The preceding combined run had three failures and six setup errors because collection selected a 69-table database without case tables. |
| `8adeddf2` | One OpenCV distribution; PaddleOCR 3 adapter, local model integrity checks, disposable bounded CPU worker and pinned bootstrap profiles. | Exact combined Windows candidate: 98 passes. Fresh Linux candidate: 84 passes. Both installations match 162 pins, have one `cv2` owner and pass metadata checks. Real CPU OCR reads both RAM and storage values offline on Windows and network-disconnected Linux. |
| `5a84ac43` | Limit asynchronous observers to four process-wide workers; own application shutdown and preserve the database while work remains active. | Exact complete candidate: 121 passes. Startup failure survives cleanup; a failed shutdown remains visible and retryable. Saturation is explicitly rejected and logged, not durably queued. |
| `18e3f469` | Restore UTF-8 diagnostics/comments accidentally changed while preparing the previous candidate. | Exact lifecycle candidate: 22 passes; code structure is unchanged apart from text constants. The candidate-export encoding mistake and correction remain in history. |

Pass counts overlap and must not be added. Initial native OCR failed despite mocked adapter tests passing: the pinned Paddle CPU graph rejected a oneDNN operator. Disabling that execution path restored actual inference. Windows native verification took 5.5 seconds; the final Linux OCR check took 6.639 seconds, each with confidence 0.9886 on the controlled two-line image. This proves that bounded fixture, not arbitrary document accuracy. Models were supplied as local files with recorded SHA-256 digests; no default model download was allowed during inference.

All eight declared Linux/Windows API, vision, test and bootstrap profiles pass generation checks and advisory queries. The fresh installed Windows union also reports zero advisory matches. A separate query of **all 272 distinct locked package versions**, without host-platform filtering, finds **29 package-advisory matches across ten package names**, with no query errors or skips. This includes variants outside the installed profiles and duplicate advisory aliases. The entire lockfile is **not** clear: LangChain-related packages, langgraph-sdk and Tornado have listed upgrades; RAGAS and diskcache have no listed patched version. [RAGAS advisory](https://github.com/advisories/GHSA-95ww-475f-pr4f), [diskcache advisory](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v).

The historical Docker installation still omits the lockfile and several CI jobs use unpinned installs or a missing `requirements.txt`; deployment/install wiring therefore remains work. Two host suspensions invalidated native-profile wall-clock budgets. Those failed receipts remain separate; the final Linux install/test run completed within its unchanged limits. Test controllers now hold a temporary idle-sleep lease released on process exit, without changing persistent power policy.

The latest fresh-environment browser batch passes six qualification, four upload, one transition and one supplier-enquiry case with an unchanged 1,529-file application/browser source fingerprint. Its additional live-memory case skipped because the fixture was offline; that batch is explicitly incomplete. A separate correctly configured live rerun passes with zero skips and the same source fingerprint, giving passing evidence for all 13 named critical cases across the two profiles. Its amended 40-unit case still produces a provisional draft and blocked market result, as described below. These root-working-tree checks do not certify all remaining uncommitted dependencies.

The [runtime source map](audits/2026-10-20-runtime-source-map.csv), [new file inventory](audits/2026-10-20-runtime-file-inventory.csv) and continued section of the [execution manifest](audits/2026-10-20-execution-delta.json) identify the source, line counts and evidence.

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

The earlier [file inventory](audits/2026-10-20-execution-file-inventory.csv) records the `559aea5a` snapshot. The latest [file inventory](audits/2026-10-20-runtime-file-inventory.csv), captured at `18e3f469` before this report update, mechanically reads and fingerprints **5,656 eligible files and 974,317 text lines**. Generated October audit outputs are excluded to avoid counting the inventory itself. Eligibility differs slightly from the earlier snapshot, so totals are not a clean code-growth comparison. This is not manual semantic certification of every line.

All eligible Python files parse. Structural priorities remain:

| Current source | Size of main operation | Why it remains work |
| --- | ---: | --- |
| [Chat](../src/app/routers/chat.py) | `_chat_query_impl`: 4,527 lines, 561 branch nodes including nested code. | Routing, evidence, persistence and response construction remain coupled. |
| [Application factory](../src/app/main.py) | `create_app`: 2,215 lines, 354 branch nodes including nested code. | Targeted ownership repairs do not establish every startup/error path. |
| [Email security](../src/app/security/email_security.py) | `evaluate_email_security`: 2,021 lines, 315 branch nodes including nested code. | Detection, policy and persistence need independently tested boundaries. |
| [Turn router](../src/app/services/recommendation_core/turn_router.py) | `_route_turn_raw`: 1,343 lines, 205 branch nodes including nested code. | Many fallback paths still interact. |
| [Merchant dashboard](../src/app/routers/merchant_dashboard.py) | `merchant_email_lab`: 2,328 lines, largely markup. | Extract presentation; size alone does not demonstrate a logic defect. |

There remain **99 production functions over 200 lines**, **5,593 broad exception handlers** and **2,037 pass-only handlers**; the earlier snapshot had 2,116 pass-only handlers. These are review candidates, not proved defects or a quality percentage. The direct-call async heuristic finds zero matches; it does not detect every indirect call or synchronous SQL operation.

The inventory observed **572 dirty paths: 278 tracked changes and 294 untracked paths**, with none staged. Runtime evidence changes that count between observations. Existing work is preserved; the remaining tree is not an integrated release.

## Gaps and why

| Roadmap | Remaining work | Why targeted results do not close it |
| --- | --- | --- |
| W00 integration | Review remaining module, router, migration, fixture and CI dependency groups; export/test coherent candidates. | Root success can depend on uncommitted modules. Hundreds of mixed changes remain. |
| W01 runtime | Failing requests/security writes, competing transactions, remaining scheduler owners and endurance. | The historical 151.56-second security request is not closed by the schema cache. A separate early task implementation hit its backstop under the old environment; its stack did not establish a SQL cause. Required persistence arguments were corrected and successful paths now pass, but general exception-path coverage is still needed. |
| W02 dependencies | Remediate remaining locked optional/ML variants and align Docker/CI installs with the verified profiles. The shared OpenCV namespace, selected OCR capability and Linux clean-install checks now pass. | Zero advisory matches and `pip check` do not validate shared binary namespaces, models or every Poetry package. |
| W03–W04 evidence/transitions | Stale response, foreign owner, double acceptance, reload and enabled official-research cases. | Offline acceptance remains provisional; successful corroboration requires its separate provider profile. |
| W05 draft | Exact accepted-stock shortage in the ordinary browser path; mixed amendments, provider faults and recovery. | Exact 15-unit output passes API/stock tests. The live conversation has no accepted selection and correctly remains provisional. Sending requires its separate explicit approval workflow. |
| W06 market | Useful cited live observations; conflicting/expired/foreign evidence and failed sources; unchanged commercial state. | Controlled citation delivery passes; live market replay has no admissible current findings. |
| W07 privacy/memory | Multiple HTTP workers, erasure during failure, worker replacement/recovery and every retained data plane. | Earlier owned-Redis tests do not certify complete API erasure or backup policy. |
| W08–W10 commerce | Existing inventory reconciliation, concurrency/expiry, approvals, supplier recovery and restore/rollback. | Simulated targeted journeys do not establish every operational invariant. |
| W11–W13 security/architecture/CI | Required security profiles, broader browser contracts, service boundaries and clean-checkout checks. | Historical failures/skips and mixed-tree prerequisites remain. |
| W14–W15 release | Freeze one integrated source/dependency candidate; run full required suites, restore/rollback and endurance. | No final-source full release run has passed. Historical Python had 7,836 passes, 36 failures and eight errors; historical broad browser accounting was 49 passes, 80 failures and 32 skips. Do not combine these with targeted current passes. |

OpenCV's maintainers specify that only one wheel distribution should supply the shared `cv2` namespace. The previous combined profile installed three; the committed profile and both fresh tested installations now have one owner. [OpenCV packaging instructions](https://pypi.org/project/opencv-python/)

## TDD and the meaning of green

A named gate is green only when its intended assertions run on the identified source and installation, the native command exits zero, required cases are not skipped and resource limits hold. Zero selected tests, missing fixtures, unavailable required providers, timeouts and changed source snapshots cannot certify a gate.

Valid red-before evidence covers scheduler transactions, membership failure, workload continuity, evidence binding, lifecycle cleanup, duplicate inserts/schema contention, market delivery and ordinary chat task output. Invalid setup attempts remain separate evidence: a missing test filename and an unbound SQL fixture parameter are not product regressions.

One runtime-candidate rerun initially reused the previous JUnit destination, overwriting that failing XML. Both native logs/receipts survive; the successful XML was copied to the complete profile with an explanation. The runner now rejects a JUnit destination outside its current profile. This evidence limitation remains recorded.
