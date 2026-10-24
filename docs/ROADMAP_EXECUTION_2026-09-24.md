# Roadmap execution evidence — 24 September 2026

Implemented the operational and authority repairs authorized after the independent assessment. This is a **completed implementation batch, not certification that the entire P0–P3 roadmap is complete**. The workspace already contained substantial unrelated changes; nothing was committed or published.

## Status against the requested evidence

| Priority | Implemented and observed | Remaining evidence |
|---|---|---|
| P0 runtime | Transport leases survive caller timeouts until transport actually finishes; typed failure codes and per-execution timing survive projection. Shared local demo model settings, explicit database bootstrap and migrations. Isolated application lifespan and five real-model API cases completed. | Long-running soak, text/image/text residency testing, and deployment-platform verification. Driver crash causation remains unproven. |
| P0 authority | Explicit consent starts research; explicit denial overrides automatic policy and carried consent. Accepted official claims survive terminal commit. API narration no longer claims fit when its terminal contract holds or blocks products. Existing stale-evidence and qualification checks pass. | Browser-level live verification and broader replay coverage across every effect sink. Ordinary university browsing still holds qualification; this batch makes that outcome truthful rather than manufacturing a fit. |
| P1 research | Consented Blender research fetched the official origin, preserved one accepted requirement claim, and truthfully withheld full qualification. Denied enrollment and declined consent do not execute that research. Cold-start discovery can make its first bounded attempt. Private endpoint allowance is restricted to literal loopback; redirect following and response sizes are bounded. | General workload coverage remains incomplete. Emulate3D certification failed official-origin selection. Public-host DNS check/connection pinning is not implemented. |
| P1 extraction | Terminal projection, consent resolution and research-request construction moved out of chat. Added an AST function-size growth ratchet to CI. | Chat remains large: 4,482 lines in `_chat_query_impl`. Further extraction should retain the same boundary checks. |
| P2 market | Consumer-time provenance and validity checks withhold expired or unbounded findings from structured evidence/narration. Live ingestion receipts and watermarks retained. | **No operational market decision demonstrated.** The NWS observation is scoped to a California forecast zone, with no tenant route/SKU mapping. It must not influence Australian laptop recommendations merely because it was fetched. |
| P2 effects | Exact message/recipient/tenant/actor binding; expiring and revocable pending permits; atomic dispatch guards; changed content conflicts. Stale in-flight claims require reconciliation. Submission, acknowledgement and simulation have separate completion semantics. | This covers the outbound queue, not all commerce effects. Independent-person approval for real supplier delivery remains unavailable; the existing transport hold remains in place. Revocation after dispatch requires reconciliation. |
| P3 measurement | Frozen six-case real router smoke cohort run against 9B and 14B models; negative results retained. Data-readiness counts collected. | No held-out business-quality improvement established for retrieval, graph infrastructure or forecasting. Real labelled cases, tenant-relevant observations and outcome history are needed before those comparisons are meaningful. |

## Concrete changes

- `model_execution_gateway.py` hands lease release to transport completion, including the late-completion path. Predispatch failures release the lease immediately. `local_model_roles.py` emits typed failures and resets metrics for each execution.
- `recommendation_core/router_model_call.py` separates queue/verification/execution timing, preserves failure identity and prevents a late worker from rewriting the returned provider metrics.
- `config/local_demo_runtime.json`, `scripts/local_demo_runtime.ps1` and `scripts/start_local_ollama.ps1` define the canonical local profile: text `qwen3.5:9b-q4_K_M`, vision `qwen3-vl:8b`, context 4096, one loaded model and one parallel request. Server settings require launching Ollama with this profile; setting them in an API process cannot reconfigure an already-running server. Other historical launchers are not all consolidated.
- `scripts/bootstrap_demo_runtime.py` backs up an existing explicit SQLite target, migrates it, optionally seeds it and checks required tables. The proof used `.artifacts/roadmap-proof.sqlite3`, not the root `shopsquire.db`.
- `chat_research_entry.py` resolves one consent/policy snapshot and builds the governed request. Chat previously checked only automatic policy authorization, ignoring explicit buyer consent. It also looked for accepted claims under a field the enrolled-source response did not populate. Both defects are repaired.
- `chat_terminal_projection.py`, terminal narration and research-outcome reduction preserve claim counts, current revision identity and useful failure codes. A historical unknown-reachability diagnostic cannot override an executed discovery receipt.
- The HTTP discovery adapter narrows local endpoint access and streams bounded bodies. The first consented discovery operation can attempt transport when reachability is unknown; disabled policy and unenrolled tenants still deny dispatch.
- `market_evidence_admission.py` validates evidence when consumed, rather than assuming an ingestion watermark proves continuing freshness. Missing expiry/provenance now suppresses narration, which can reduce existing findings until upstream data supplies those fields.
- Outbound migration `20260877_outbound_effect_binding` adds digest, expiry and revocation fields. Existing unbound pending messages fail closed and require renewed authorization. Migration `20260878_outbound_ack_reference` preserves acknowledgement identity separately from the transport reference. A successful transport submission no longer projects the communication lifecycle as delivered. Migration 77 deliberately refuses an automatic downgrade that would discard binding data.

## Verification

**171 Python tests passed**, zero failures/errors: runtime authority, gateway, policy, discovery transport, market validity, outbound queue, communication lifecycle, chat delegation, terminal reconciliation/narration/qualification, architecture boundaries, open-world discovery and readiness. JUnit evidence: [roadmap-tests.xml](../.artifacts/roadmap-tests.xml).

**17 frontend oracle tests passed.** Function-size ratchet, undefined-name checks and whitespace diff checks passed. The file-size checker still reports existing oversized modules. These are targeted checks, not a complete repository test suite or a live browser test.

The final live API probe used an isolated SQLite database, temporary Redis on port 6385, a dedicated Ollama server on port 11435, and the existing SearXNG service on port 8888. It used actual models and network providers. All five cases returned HTTP 200, matching case/revision identity and `commerce_authority=none`:

| Case | Elapsed | Evidence outcome |
|---|---:|---|
| University laptop browse | 2.089 s | Held; no unsupported fit or budget assurance. |
| Consented Blender research | 6.244 s | One accepted official requirement; partial coverage; qualification blocked. |
| Blender without consent | 3.752 s | No server research dispatch or accepted claims. |
| Consented but unenrolled tenant | 3.204 s | `external_research_tenant_not_enrolled`; qualification blocked. |
| Unresolved publisher name | 17.089 s | Three completed discovery receipts, 25 returned results each; publisher acceptance still required; zero accepted claims. |

See [live summary](../.artifacts/roadmap-live-chat-summary.json), [full responses](../.artifacts/roadmap-live-chat.json), [probe script](../.artifacts/roadmap_chat_probe.py), and [startup/request log](../.artifacts/roadmap-live-chat.log). Application lifespan completed with process exit 0. Startup still warned about optional tracing configuration/exporter availability. No new `nvlddmkm` System events were found in the inspected period after 19:00 Sydney time; this short observation is not driver stability certification.

The additional official-source certification passed for Blender and failed for Emulate3D. Evidence: [Blender](../.artifacts/roadmap-blender-research.json), [Emulate3D](../.artifacts/roadmap-live-research.json).

## P2/P3 evidence limits and next release gates

The live NWS fetch retained one Red Flag Warning for `nws-zone:caz285`, with publisher provenance and an expiry. The recall endpoint failed DNS resolution; its unavailable receipt was retained without pretending a successful observation. These are acquisition proofs, not operational market-signal admissions or demonstrated decision improvement. See [weather observation](../.artifacts/roadmap-market-weather-proof.json) and [recall failure](../.artifacts/roadmap-market-proof.json).

The isolated proof database has zero `market_signal`, `market_finding`, `market_subject_mapping`, `commercial_outcomes`, `marketing_event_fact` and forecast/actual pairs. Public-source revision and ingestion receipt rows do exist. [Counts](../.artifacts/roadmap-data-readiness.json) apply to this isolated database, not every database in the workspace.

The 9B router scored **5/6** and the 14B router **4/6** on the frozen smoke cohort. Both missed the inventory case; the 14B run also missed the off-catalog case. The 9B run was warm while the 14B run included cold loading and an embedding timeout, so these results do **not** establish a fair latency or quality superiority claim. Keep the smaller model as a conservative local candidate, not a certified winner. See [9B results](../.artifacts/roadmap-router-9b.json), [14B results](../.artifacts/roadmap-router-14b.json), and `scripts/benchmark_local_router.py`.

Before declaring the roadmap complete: demonstrate a qualified buyer journey with complete scoped requirements; run browser and mixed text/image soak checks; bind a current governed observation to an actual tenant SKU or transport lane and record the resulting decision; cover remaining commerce sinks with exact-effect permits and independent completion receipts; then compare retrieval/graph/model/forecast candidates on frozen representative labels and real outcome history. None of those gates should be replaced by increased row counts or successful HTTP responses.

The temporary Redis container and dedicated Ollama server started for this work were stopped and removed/stopped after verification. Existing Ollama and SearXNG services were left running. No real supplier message was transmitted.
