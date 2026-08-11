# ShopSquire workload-fit execution status

Date: 8 August 2026  
Decision: keep `/api/v1/recommend/suggest` as a deprecated V2 compatibility transport. Retirement is not yet eligible.

## Outcome

The platform now has a versioned workload contract, exact product-configuration identity, typed requirement/capability/behavioral evidence, a deterministic fit reducer, an adversarial critic, a shadow-only LLM renderer, five infrastructure-class alternatives, and an evidence-led responsive product explanation UI.

The cart/explain failures in screenshots 50–53 are covered by executable regression tests:

- `add 30 ... ASUS; clear 30 ... Lenovo` produces two grounded operations: ASUS `30 -> 60` and removal of the Lenovo line.
- `why ... add 30 more ... in 4 days` retains and answers explanation, quantity, and deadline obligations in one turn.
- A selected or carted product suppresses the contradictory “I didn't find a match—what budget?” clarifier.
- Cart changes remain proposed, enumerated, expiring and confirmation-only. A newer proposal durably supersedes the prior proposal and the old plan cannot be applied.
- Deadline narration states known facts, missing proof, responsible owner, and recovery actions; it does not promise delivery from stock counts.

This is not a production-promotion declaration. Human relevance review, operator source approval/credentials, hosted voice providers, and real pilot identities remain genuine external gates.

## Gate ledger

| Gate | Current evidence | Status |
|---|---|---|
| Compatibility preserved | Deprecated route and ownership/compatibility tests pass | Pass; retain endpoint |
| Honest human relevance labels | Eight-case, 43-product review packet and blank template generated; labels still name no human reviewer | Blocked on independent human |
| Fit semantics and exact identity | Canonical decision object separates compatibility, performance and scale; strong identifier + configuration hash + form factor required for full qualification | Implemented |
| Extended contracts | Requirement tier/scope/version/freshness, exact capability identity, behavioral distance/configuration, quantity/deadline/budget/constraints, decision and critic contracts | Implemented |
| Official source governance | Five workload publishers and seven product publishers have explicit HTTPS entry points, domains, claim policies and SLAs | Contract valid; 0 operator-approved and no credentials |
| Deterministic reducer and critic | Unknowns cannot become passes; unverified requirements cannot fail a product; full qualification requires exact configuration and named artefact | Implemented and tested |
| Shadow LLM narration | Direct local Ollama certification: 1,223 ms, 1,063 ms and 830 ms; all accepted, buyer-visible=false | Local shadow gate pass |
| Evidence UX | Responsive Decision Object, fit receipt, unknowns, alternatives, sources and critic details; frontend tests/build pass | Implemented |
| Real image provider | Two concurrent `qwen3-vl:8b` calls succeeded; forced disconnect failed closed in 592 ms | Local gate pass |
| Physical microphone | Real two-second capture had non-zero signal; raw WAV deleted after hashing | Physical capture pass |
| Hosted ASR/TTS | Adapters honestly returned `unavailable` | Blocked on credentials/policy |
| Pilot rollback | Tenant-qualified ephemeral identity admitted; wrong/bare identities rejected; `off` rollback observed | Control path pass; real pilot blocked |
| Compatibility retirement | Preceding gates are not all passed | Not eligible |

The current AI relevance draft remains provisional. Its previously reported Precision@10 `0.222` and NDCG@10 `0.592` must not be represented as human truth or sealed merely to make a gate pass.

## Runtime decision path

```text
buyer utterance
    |
    v
workload contract
  outcome, named artefact/version, execution shape,
  quantity, deadline, budget, scale, constraints, unknowns
    |
    v
hypothesis scatter
  digital twin -> OT cyber lab | predictive-maintenance model |
                  Omniverse/Isaac scene | remote/cloud client
    |
    +-- branches produce same product verdict --> answer with bounded assumption
    |
    `-- branches change the verdict ------------> ask one discriminating question
    |
    v
gap-targeted evidence plan
    +-- official workload requirements
    +-- exact OEM configuration
    +-- component compatibility
    +-- exact/near/far behavioral evidence
    +-- inventory, price and dated fulfilment
    `-- infrastructure alternatives
    |
    v
normalise units + bind MPN/MTM/GTIN + resolve contradictions
    |
    v
deterministic reducer
  per row: meets minimum | meets recommended | below minimum |
           unknown | contested | not applicable
    |
    v
adversarial critic
  blocks stronger language when identity, artefact or claim authority is missing
    |
    v
Decision Object
    +-- deterministic copy -> buyer surface
    `-- bounded LLM copy -> shadow audit only
```

The external search query must target a requirement gap, never “best laptop for X”. Examples:

- `GNS3 Windows hardware requirements` plus the exact device-count question.
- `Hyper-V host hardware requirements` and supported host OS edition.
- `Isaac Sim <version> system requirements` or the named Omniverse artefact.
- `<exact model-card revision> PEFT/QLoRA requirements`, followed by a code-derived memory estimate with its assumptions.
- `Nolvus <version/preset> requirements`, including target resolution.

Canonical source entry points are recorded in `config/official_workload_sources.json`. They remain pending operator review. A live fetch may create evidence only after tenant consent/allowlist, credential and publisher policy checks; retrieved facts must carry artefact version, source revision, retrieval time, freshness, scope caveat and claim ID.

## LLM narration contract

The LLM renders; it does not select a product, calculate fit, mutate a cart, promise performance, infer delivery, or add numbers. Its only input is the bounded Decision Object. The deterministic narration remains authoritative while the model runs in shadow.

Recommended copy order:

1. Verdict and exact stated scope.
2. The two or three decision-driving checks, each as required versus observed.
3. Material unknowns or contested facts.
4. Behavioral evidence distance: exact configuration, near configuration, far, or inferred.
5. Budget/value consequence, only from deterministic arithmetic.
6. One useful next action.

Example—ambiguous digital twin:

> I can't qualify this laptop for “digital twin” yet because that could mean a local OT virtual lab, an Omniverse scene, or a remote client, and those branches have different RAM, GPU and OS requirements. Which named application and approximate model or VM scale will you run? I can still compare laptop, workstation, server and cloud paths without changing your cart.

Example—bounded OT lab:

> Conditional for a small GNS3 lab. The accepted GNS3 checks show this configuration meets the recorded CPU, memory and storage floor. The device count and virtualization path are still unresolved, and Windows edition compatibility has not been verified for the exact path, so I cannot qualify an unbounded cyber range. Next: confirm the hypervisor and approximate concurrent node count.

Example—AI fine-tuning:

> Unresolved for fine-tuning until the base model, precision, adapter method, sequence length and batch target are named. The GPU and VRAM in inventory are catalog facts; they are not proof that the training run will fit. After those inputs are fixed, ShopSquire can derive a memory estimate and distinguish local laptop, workstation and cloud options.

Example—fully modded Skyrim:

> Conditional for the named Nolvus version and preset. The exact configuration meets the accepted RAM/storage checks, but the target resolution and exact laptop GPU power/performance evidence are still missing. I can confirm compatibility from the official requirement page; sustained frame-rate remains unverified until matched behavioral evidence exists.

Prohibited copy includes “good choice”, “will handle”, “future-proof”, “60 units in four days”, or a hard fail based on an unverified/community requirement.

## Desktop wireframe

```text
+-- ShopSquire Assistant -------------------+-- [Fit] [Cart] [Delivery] --------+
|                                           |                                   |
| You: Why is this good for an OT cyber     | RETAINED PURPOSE                  |
| lab? Add 30 more and clear the Lenovo.    | OT cyber-attack simulation        |
| I need it in four days.                   | Artefact: GNS3 / version unresolved|
|                                           | [Edit purpose]                    |
| CONDITIONAL for the stated scope          |                                   |
| Exact identity and virtualization path    | DECISION                          |
| still need verification.                  | [CONDITIONAL]  critic: PASS       |
|                                           | Compatibility  partial            |
| Quantity: proposed, not applied.           | Performance    unknown            |
| ASUS 30 + 30 = 60; Lenovo 30 -> 0.        | Scale          unresolved         |
| Use the Cart tab to apply both.            |                                   |
|                                           | FIT RECEIPT                       |
| Four days: cannot confirm from stock       | RAM        32 >= 32  [MEETS MIN]  |
| counts. Request a dated commitment or      | Storage     1TB >= 80 [MEETS REC] |
| split available units now.                 | Virt ext    unknown   [UNKNOWN]   |
|                                           | OS path     contested [CONTESTED] |
| [Check approved sources] [Compare paths]   |                                   |
|                                           | MATERIAL UNKNOWNS (2)             |
|                                           | - concurrent VM/device count      |
|                                           | - hypervisor / OS-edition path    |
|                                           |                                   |
|                                           | ARCHITECTURE ALTERNATIVES         |
|                                           | laptop | mobile WS | fixed WS      |
|                                           | server | cloud                    |
|                                           |                                   |
|                                           | [Evidence & claim IDs v]          |
+-------------------------------------------+-----------------------------------+
| PENDING CART CHANGE - nothing applied yet                                     |
| plan cmp-... | expires in 04:12                                                |
| 1. ASUS ProArt        30 -> 60  (+30)  deterministic line-price delta          |
| 2. Lenovo Legion      30 ->  0  (remove) deterministic line-price delta        |
| Net cart delta: calculated by code                                             |
| [Apply both] [Discard]    Newer instructions explicitly supersede this plan    |
+-------------------------------------------------------------------------------+
```

## Mobile wireframe

```text
+----------------------------------+
| ShopSquire        [Cart 2] [Fit] |
+----------------------------------+
| CONDITIONAL                      |
| OT cyber lab / GNS3 unresolved   |
|                                  |
| Meets: RAM, storage              |
| Unknown: virtualization path     |
| [Open fit receipt]               |
|                                  |
| CART CHANGE - NOT APPLIED        |
| ASUS     30 -> 60                |
| Lenovo   30 -> 0                 |
| Expires 04:12                    |
| [ Apply both ]   [ Discard ]     |
|                                  |
| 4-DAY REQUEST                    |
| Cannot confirm from stock counts |
| [Request dated commitment]       |
| [Ship available now / split]     |
|                                  |
| [Compare laptop/workstation/     |
|  server/cloud]                   |
+----------------------------------+
| Message...                 [Send]|
+----------------------------------+
```

On mobile, the verdict, pending mutation and deadline recovery move stay above the fold. Detailed ledger rows, claim IDs, critic output and infrastructure trade-offs use disclosure panels. Confirmation never relies on a prose-only message.

## Evidence artifacts

- `tmp/relevance_human_review_packet.md` — complete independent-review worksheet.
- `tmp/relevance_human_review_template.json` — hash-bound blank human grading template.
- `tmp/workload_narration_shadow_certification.json` — three real local shadow runs.
- `tmp/live_image_provider_certification.json` — real concurrent image and disconnect observations.
- `tmp/physical_voice_certification.json` — physical capture metadata and honest hosted-provider status; no raw audio retained.
- `tmp/pilot_rollback_certification.json` — nonproduction identity and rollback observation.

## Verification record

- 91 consolidated affected-area backend tests passed, covering decisions, contracts, exact identity, source governance, screenshot cart/explain regressions, vision budgets, voice flags, compatibility and endpoint ownership.
- New Python modules and certification scripts pass Ruff and byte-code compilation.
- `ProductWhyEvidence` passes four component tests and the production Vite build succeeds.
- `git diff --check` is clean for the working tree.
- A monolithic `pytest -q` run was attempted twice but exceeded local shell ceilings (2 minutes and then 10 minutes) without a completion summary or emitted failure trace. It is inconclusive and is not represented as a pass. CI should shard the full suite rather than treating this local timeout as evidence of correctness.

## Remaining roadmap, in order

1. An independent human reviews all eight slates, corrects the draft, signs the attestation and runs the existing seal workflow. Do not tune against the test split.
2. An operator reviews the canonical source list, supplies the official proxy/API credentials, publisher policy ID and exact tenant allowlist, then captures successful freshness/provenance evidence.
3. Run representative named workloads through the complete requirement-to-exact-SKU pipeline. Include version changes, stale sources, contradictions, blank OEM fields, family-versus-configuration mismatches and no-result recovery.
4. Supply hosted ASR/TTS credentials under provider-transfer policy; repeat real microphone -> hosted ASR and deterministic response -> hosted TTS, including disconnect, timeout, silence, malformed audio and concurrent-provider cases.
5. Name real pilot `tenant:subject` identities. Observe shadow, pilot admission, metrics, explicit `off` rollback and old-plan/old-session behavior in a controlled window.
6. Re-run the complete quality/reliability/security suite with sealed labels and production source evidence. Promotion requires relevance, latency, timeout/fallback, authorization, classification and rollback gates together.
7. Only then write a compatibility retirement proposal. Until approval and a measured migration window exist, preserve the endpoint and deprecation headers.

## 8 August execution delta: ambiguous-intent research path

The following vertical-agnostic slices are now implemented and tested. They do
not make external research mandatory for a normal, sufficiently covered shopping
request.

1. `ResearchTriggerDecision` separates research eligibility, buyer/tenant
   authorization, and the selected execution route. A known workload, fresh
   accepted cache hit, immaterial ambiguity, denied tenant policy, or missing
   consent cannot dispatch an external provider.
2. Evidence scheduling now reports internal `effort` separately from provider
   calls and paid-call accounting. The semantic path admits the jointly selected
   concept-resolution (3) and web-discovery (5) legs with an allowance of 8.
   Admission rejection is a wiring status, not a knowledge or spend statement.
3. Provider usage counts only calls dispatched in the current turn. A cache hit,
   an unconfigured provider, or pre-dispatch cancellation reports zero external
   calls; paid-call count stays `not_recorded` unless billing class is explicitly
   governed.
4. Buyer-supplied OCR/text produces only provisional, unverified requirement
   claims. RAM and VRAM are unit-separated; minimum, recommended, preferred and
   acceptable-alternative tiers remain distinct. Suspicious OCR is quarantined
   and produces no claims.
5. `WorkloadHypothesisCompilation` accepts one to three model proposals but
   grounds them only through accepted compiled claim IDs. It computes the exact
   shared requirement intersection, divergent axes, and one highest-information
   eligible question. Wholly ungrounded hypotheses are rejected.
6. `ProductShelfProjection` deterministically emits a shared shelf and optional
   hypothesis shelves, with top 3 plus next 5 paging and explicit within-budget
   versus stretch bands. Verified hard failures are excluded; evidence gaps stay
   conditional. Exact-configuration identity prevents evidence transfer between
   visually similar variants.
7. Shadow narration is checked against the canonical decision. The critic rejects
   unsourced hardware floors, invented benchmark/performance claims, unsupported
   Windows Pro advice, conditional-fit overstatement, omitted budget conflict,
   and omitted exact ledger gaps.

Verification recorded for this delta:

- 116 combined backend tests passed across trigger, evidence, governance, OCR,
  hypothesis, shelf, decision, narration and multi-turn contracts.
- Four multimodal chat integration tests passed, including trusted requirement
  extraction and malicious-OCR quarantine.
- The real Chromium five-turn semantic-resolution journey passed in 49.3 seconds.
- Four consecutive local `qwen3:14b` calls measured 3,221 ms, 3,090 ms,
  3,241 ms and 3,445 ms. The three-consecutive-under-8-seconds model-call gate
  passed; median was 3,231 ms. Provider-internal and transport overhead are now
  attributed separately.

This does not promote LLM narration to buyer-visible authority and does not make
the compatibility endpoint eligible for retirement. The UI still needs the full
review-and-accept interaction for uploaded claims and progressive multi-shelf
rendering; official live sources, hosted voice credentials, independent relevance
labels and named pilot identities remain external gates.

### Screenshot 55 upload-path correction

The first implementation stopped at the downstream claim parser and was not an
end-to-end Phase 3 completion. Screenshot 56 exposed three live wiring defects:

1. the storefront erased OCR unless the upload was classified as a product photo;
2. the fast filename-only triage result was sent to chat before deep OCR completed;
3. the global GPU OCR setting overrode the explicitly selected bounded local OCR
   provider, and URL-like publisher text was mislabeled as prompt injection.

The corrected path now identifies a requirements/document upload, waits for
bounded OCR, forwards a clean OCR channel independently of product-photo identity,
restores flattened hardware section boundaries, and renders a provisional review
card. The exact screenshot at `dump/ecommerce/New -screenies/55 - product specs
ocr.png` produced a clean 298-word Tesseract observation and ten deduplicated
claims. A real Chromium upload certification passed in 27.1 seconds. No product
was qualified and no cart action occurred.

This completes OCR-to-review, not review-to-recommendation. Typed acceptance,
correction persistence, requirement compilation, catalog reranking and progressive
shelf rendering remain the next integrated slice.
