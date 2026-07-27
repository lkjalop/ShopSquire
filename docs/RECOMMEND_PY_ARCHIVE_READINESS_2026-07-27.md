# `recommend.py` archive readiness — 2026-07-27

## Current cutover state

- Production application wiring imports `src.app.routers.recommend_compat`; it no longer
  registers `src.app.routers.recommend`.
- `/api/v1/recommend/suggest` is a deprecated compatibility route backed by the typed V2
  facade. It emits `Deprecation`, `Sunset`, successor `Link`, and engine headers.
- `legacy_recommendation_delegate.py` delegates to the V2 compatibility service and has no
  production import of `recommend.py`.
- The embeddable storefront widget now posts to `/api/v1/chat/query`; no production frontend
  caller invokes the deprecated suggest route.
- Compatibility traffic and dispatch outcomes are exported through
  `shopsquire_recommend_compatibility_requests_total` and
  `shopsquire_recommendation_dispatch_total`.
- Inventory DB truth, prompt-injection refusal behavior, model-theft ingress, off-domain,
  support/order claims, and damaged-image support routing have V2 compatibility coverage.

## Passing retirement evidence

| Evidence | Result |
| --- | ---: |
| Recommendation V2 core/facade suites | 207 passed |
| Frozen compatibility response contract | 7 passed, 2 intentional skips |
| Inventory parity | 2 passed |
| Compatibility/API/architecture boundary checks | 9 passed |
| Targeted prompt-injection security | 3 passed, 3 environment skips |
| Model-theft + deprecation compatibility | 5 passed |
| V2 multimodal trace + image-forensics | 6 passed |
| Procurement service suites | 22 passed |
| Golden workload matrix | 16 passed, 1 failed |

## Blocking parity evidence

These are not deletion-safe yet. Several old tests patch legacy candidate retrieval and must
be rewritten around authoritative V2 taxonomy fixtures; others expose genuine missing V2
behavior.

| Area | Result | Main gaps |
| --- | ---: | --- |
| Reference acceptance matrix | 17 passed, 4 failed | V2 taxonomy fixture/product buckets; durable incident evidence; timing envelope; multi-use-case tags |
| Follow-up suite | 3 passed, 3 failed | V2 session budget carry-forward; legacy complexity-helper assertion |
| Legacy multimodal + bulk endpoint pack | 8 passed, 17 failed | image-brand constraints, QR status/security matrix, NQE generation/persistence, persona, image relationship, bulk availability |
| Golden workload | 16 passed, 1 failed | Stable Diffusion response lacks explicit GPU/VRAM/cloud honesty |

## Remaining source dependency

There are no production Python imports of `src.app.routers.recommend`. Thirteen test modules
still import legacy private helpers (the architecture test only contains the module name as a
boundary assertion). Those tests must be moved to one of:

1. a V2 service contract after extracting the helper to its owning service;
2. a compatibility-route contract when the behavior is externally required; or
3. immutable characterization data when the behavior is intentionally not carried forward.

Until those imports reach zero, deleting the module destroys characterization evidence and
breaks collection.

## Rollback observation gate

Local tests cannot satisfy a production rollback window. Keep the file unregistered during the
window and observe:

- compatibility request volume and status mix;
- V2 unavailable/blocked/degraded rate by lane;
- empty-result rate and P50/P95 latency;
- prompt-injection/model-theft blocks;
- support, image, inventory, bulk and follow-up contract error rates.

Archive/delete only after the agreed window has:

- zero production import/call evidence for the legacy module;
- no blocker-level parity differences;
- an acceptable V2 unavailable/degraded rate;
- successful rollback rehearsal from the deployment artifact; and
- zero remaining test imports of legacy private helpers.

## Archive decision

`recommend.py` is dead in production routing but **not deletion-ready**. The cutover mechanics
are mostly complete; capability parity and test migration remain the critical path.
