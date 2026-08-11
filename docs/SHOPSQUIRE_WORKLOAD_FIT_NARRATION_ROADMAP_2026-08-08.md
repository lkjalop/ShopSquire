# ShopSquire workload-fit evidence, narration, UX, and release roadmap

**Date:** 2026-08-08  
**Scope:** Assessment of `shopsquire-workload-fit-architecture.md`, the current ShopSquire implementation, the nine supplied retailer listings, and the work required before LLM narration can safely qualify a product for a workload.

---

## Executive decision

Do **not** make the LLM the workload expert or let it write a free-form “why this is a good choice” answer from product titles and search snippets.

The next milestone should be a versioned **Workload Decision Object** produced by deterministic code from two separately governed ledgers:

1. an artefact/version-specific requirement ledger; and
2. an exact-configuration product capability ledger.

The LLM may propose interpretations, choose a high-value clarification, and render an already-authorized decision. It may not create a requirement floor, turn missing evidence into a pass, silently select one meaning of “digital twin”, or claim behavioral performance from component names.

The downloaded architecture note is strong in its central thesis—“a workload phrase is not a requirement”—but the roadmap needs revision because parts of its code assessment are already stale and some of its verdict/narration contracts still mix distinct questions.

### Recommended release posture

- Keep the V2 compatibility endpoint.
- Keep deterministic narration as the synchronous response.
- Put LLM narration in shadow or asynchronous enhancement mode until claim-level validation and latency certification pass.
- Do not certify workload recommendations until official requirement and product-capability providers are genuinely enrolled with credentials, publisher policies, tenant allowlists, freshness SLAs, and retained response evidence.
- Treat the existing persona KB as discovery/ranking hints only—not authoritative workload floors.

---

## 1. What to retain, change, and reject from the downloaded note

### Retain

- Requirement floors keyed to a named artefact and version, not a broad persona.
- Bounded hypothesis generation followed by one maximally discriminating question when interpretations would change the recommendation.
- Concurrent, gap-directed evidence collection.
- Separation of requirement evidence, product capability evidence, compatibility, behavioral performance, inventory, and fulfilment.
- An adversarial critic before buyer-facing narration.
- Explicit `UNKNOWN` and `CONTESTED` states.
- Exact MPN/configuration and laptop-versus-desktop GPU identity.
- Budget applied after capability qualification.
- A narrator that receives only a bounded Decision Object, never raw web pages.
- Inline evidence plus a full audit ledger.

### Change

1. **Use two verdict layers, not one six-value enum.** “Good”, “marginal”, “over-spec”, and “unknown” combine row truth, product suitability, performance, and commercial judgment.

   Requirement-row verdicts:

   - `MEETS_MINIMUM`
   - `MEETS_RECOMMENDED`
   - `BELOW_MINIMUM`
   - `UNKNOWN`
   - `CONTESTED`
   - `NOT_APPLICABLE`

   Overall decision states:

   - `NOT_QUALIFIED`
   - `CONDITIONAL`
   - `QUALIFIED_FOR_STATED_SCOPE`
   - `OVER_SPEC_FOR_STATED_SCOPE`
   - `UNRESOLVED`

2. **“Will run well” needs behavioral evidence.** An official minimum or recommended table can establish compatibility/sizing tiers. It cannot prove frame rate, training throughput, thermal sustain, or VM density on an exact laptop. That requires a reproducible exact-configuration test or a clearly labelled inference.

3. **Do not hard-code the narrator model.** The note names `Qwen3.6:14b`, while the repository currently profiles other model identifiers and 20–45 second narration timeouts. The contract must be model-independent. A model earns the role through certification.

4. **Validate claims, not raw numeric tokens.** A regex rule saying every output number must appear literally in a ledger will mishandle prices, dates, quantities, ranges, and validated arithmetic. Narration blocks should reference claim IDs. Derived values need a typed derivation record with operands and rule ID.

5. **Make search continuation-friendly.** The current plan defaults to a 2,000 ms total research deadline. Real official sources should normally be cached by `(artefact, version, locale)`; live availability remains fast and fresh. A cold multi-provider lookup should return a visible research continuation, not make the user wait behind hidden provider/model overhead.

6. **Make `OVER_SPEC` preference-sensitive.** A high-capability product is not over-spec merely because it exceeds a minimum. It is over-spec only if a materially cheaper, available option meets the buyer’s complete stated target and the extra capability does not serve another stated preference.

### Reject

- A model-generated generic floor such as “digital twin → RTX 4070+”.
- Generic “AI laptop” qualification based only on VRAM.
- Uncalibrated numerical evidence-distance scores that imply measured precision.
- Retailer marketing prose as workload authority.
- Family-level GPU or CPU facts silently copied onto an exact SKU.
- “Closest match” presented as a recommendation when every option fails a hard minimum.
- A single “best laptop” while surviving interpretations disagree.

---

## 2. Current ShopSquire state

### Already present and worth preserving

| Capability | Current evidence | Assessment |
|---|---|---|
| Authoritative requirement compiler | [`requirement_compiler.py`](../src/app/services/recommendation_core/requirement_compiler.py) accepts only authorized authorities, provenance, confidence, registered attributes, and operators | Strong enforcement primitive |
| Tri-state catalog fit | [`fit.py`](../src/app/services/recommendation_core/fit.py) preserves `meets / unknown / fails` and normalized observations | Strong but its buyer copy is too broad |
| Product fit ledger | [`product_fit_explanation.py`](../src/app/services/recommendation_core/product_fit_explanation.py) retains requirement and product evidence references and says qualification is bounded | Good start; schema needs scope/version/class fields |
| Fit UI | [`ProductWhyEvidence.tsx`](../frontend/src/components/ProductWhyEvidence.tsx) renders the ledger and unknowns | Already implemented; not merely a trace-drawer concept |
| Concurrent evidence | [`evidence_orchestrator.py`](../src/app/services/evidence_orchestrator.py) has budgets, tenant concurrency, cancellation, timeout/degraded health | Note’s timeout criticism is now stale |
| Research contracts | [`research_contracts.py`](../src/app/services/recommendation_core/research_contracts.py) types needs, queries, material slots, plans, claims, and compiled requirements | Extend rather than replace |
| Exact product identity support | [`product_identity.py`](../src/app/services/product_identity.py) and [`product_capability_evidence.py`](../src/app/services/connectors/product_capability_evidence.py) support MPN/MTM/GTIN identity | Note’s “MPN does not exist” statement is stale |
| Capability source policies | [`product_capability_sources.json`](../config/product_capability_sources.json) declares Lenovo PSREF, Intel ARK, and NVIDIA domains | Contracts exist; endpoints/evidence do not |
| Infrastructure alternatives | [`infrastructure_alternative_projection.py`](../src/app/services/infrastructure_alternative_projection.py) types laptop, mobile workstation, fixed workstation, server, and cloud | Built; must be integrated into the workload decision/UI |
| Narration latency modes | [`recommend_narration_stage.py`](../src/app/services/recommend_narration_stage.py) supports blocking, skip, async, timeout, guard, and deterministic fallback | Use `skip`/`async` until certified |

### Material gaps

1. **Two fit paths remain.** `recommendation_core/fit.py` is registry-backed and general; `workload_fit.py` is a coarse RAM/VRAM projection. They can disagree and should not both be authoritative.
2. **The persona KB still contains invented generic floors.** For example `ai_ml_workstation` supplies a generic 32 GB RAM / 8 GB VRAM shape. It is useful as a hypothesis/cache seed, not as evidence that an unnamed model and fine-tuning method will fit.
3. **`meets all N requirements` is unsafe copy.** In `fit.py`, it can sound like full workload qualification even when only two dimensions were checked.
4. **Requirement metadata is incomplete.** The compiled contract lacks artefact ID/version, requirement class, scope caveat, publisher revision, freshness status, and supersession.
5. **Capability metadata is incomplete in the final ledger.** It needs exact configuration identity, form factor, claim class (`ATTESTED`, `DERIVED`, `BEHAVIORAL`), source tier, confidence band, and conflict history.
6. **Official providers are not operationally enrolled.** The registry correctly fails closed unless endpoint, credentials, reviewed source policy, publisher policy ID, freshness SLA, tenant allowlist, and domains exist. This is production-contract code without production evidence.
7. **Per-hypothesis fan-out is incomplete.** The system can gather by evidence need, but ambiguous workload branches are not yet reliably populated and compared before catalog authority is granted.
8. **The LLM can still be expensive without adding authority.** Current model profiles allow large blocking timeouts. Narration should not sit on the critical path merely to paraphrase deterministic facts.
9. **Behavioral evidence is not a first-class ledger.** Exact-laptop TGP, sustained thermals, frame-rate/settings, training throughput, and workload-scale benchmarks need separate handling.
10. **The new five-class infrastructure projection is not yet part of the Decision Object.** It should surface when local laptop qualification is weak, expensive, or unresolved—not appear as generic prose on every turn.

### Focused verification performed for this assessment

The current primitives passed 41 focused tests covering the requirement compiler, product fit explanation, evidence orchestrator, fit-ledger characterization, and KB drift. This validates the existing contracts, not the missing production evidence or end-to-end buyer claim.

---

## 3. The decision model ShopSquire needs

### 3.1 Keep four questions separate

| Buyer question | Decision type | Minimum evidence |
|---|---|---|
| Can it run? | Compatibility/minimum | Versioned official requirement + attested exact-product capability |
| Will it run well? | Behavioral performance | Recommended/target requirement + exact or near-form-factor benchmark, with settings |
| Is it right for my scale? | Workload sizing | Buyer scale variables + requirement curve or validated estimator |
| Should I buy it? | Commercial decision | All applicable above + price, availability, deadline, priorities, and alternatives |

### 3.2 Proposed typed objects

```text
WorkloadContract
  workload_id
  buyer_outcome
  artefact: {name, edition, version, locale}
  execution_shape: local | remote_client | hybrid | cloud
  scale_inputs[]
  target_inputs[]
  assumptions[]
  material_unknowns[]
  surviving_hypotheses[]

RequirementClaim
  claim_id
  artefact_id + artefact_version
  attribute_key + operator + value + unit
  requirement_class: MINIMUM | RECOMMENDED | TARGET | OPTIMAL
  scope_caveat
  source: {publisher, url, revision, retrieved_at, observed_at}
  authority_tier
  verification_status
  freshness_status
  supersedes_claim_id?

CapabilityClaim
  claim_id
  product_identity: {sku, mpn/mtm/gtin, configuration_hash, form_factor}
  attribute_key + value + unit
  claim_class: ATTESTED | DERIVED | BEHAVIORAL
  source + observed_at
  confidence_band: EXACT | NEAR | FAR | INFERRED
  settings/scope_caveat
  conflict_set_id?

FitLedgerRow
  requirement_claim_ids[]
  capability_claim_ids[]
  row_verdict
  comparison_rule_id
  explanation_key
  resolvers[]

WorkloadDecision
  decision_id + version
  workload_contract
  product_configuration
  fit_ledger[]
  compatibility_status
  performance_status
  scale_status
  overall_decision
  qualification_scope
  budget_status
  availability_status
  architecture_alternatives[]
  critic_result
  authorized_narration_blocks[]
```

### 3.3 Deterministic invariants

- No named artefact/version and branch disagreement → `UNRESOLVED`, not a synthesized floor.
- No attested exact-configuration capability → `UNKNOWN`, never `MEETS_*`.
- Unverified requirement → cannot produce `BELOW_MINIMUM`.
- Recommended/optimal values cannot be relabelled as minimum.
- Laptop and desktop GPU claims never unify without form factor.
- A timed-out material evidence lane produces an unresolved row and degraded research state.
- A hard minimum failure removes the product from the qualified slate.
- If every in-budget product fails, return no qualified in-budget result and offer architecture/budget alternatives.
- Availability can expire independently without invalidating near-static requirement claims.
- A product title, retailer description, or model narration cannot mint an authoritative requirement.
- Cart mutation is a separate authorization; explaining fit never changes quantity or SKU.

---

## 4. How external search should work

### 4.1 Search is for evidence, not recommendations

The external search planner should never issue “best laptop for digital twin” and summarize SEO pages. It should generate bounded evidence needs tied to unknown Decision Object cells.

```text
buyer utterance
   |
   v
extract purpose + named artefacts + scale + target + constraints
   |
   v
generate 2–5 hypotheses (non-authoritative)
   |
   +-- do all hypotheses yield the same product decision? -- yes --> state assumption
   |
   no
   |
   +-- can one buyer answer resolve the split? -------------- yes --> ask one question
   |
   no / user authorizes research
   v
gap-directed scatter/gather
   |
   +-- DISCOVERY: identify official artefacts/editions/versions
   +-- REQUIREMENT: minimum/recommended/target claims
   +-- COMPATIBILITY: OS, drivers, hypervisor, framework, extensions
   +-- PRODUCT: OEM facts for exact MPN/configuration
   +-- PERFORMANCE: exact/near laptop measurements with settings
   +-- INVENTORY: internal SKU, price, quantity, location, freshness
   +-- FULFILMENT: deadline evidence per allocation line
   |
   v
normalize -> resolve conflicts -> deterministic reducer -> critic
   |
   v
Decision Object -> deterministic copy -> optional guarded LLM copy
```

### 4.2 Example bounded queries

For “digital twin to simulate an OT cyber attack”:

- Discovery: official definitions/docs for the buyer-named simulator or, if unnamed, identify plausible artefacts without treating them as selected.
- Requirements: `GNS3 <version> official Windows hardware requirements`; or the selected EVE-NG/VMware/Proxmox alternative.
- Compatibility: selected hypervisor host OS/edition, nested virtualization, device image licensing, and BIOS virtualization requirements.
- Product: exact MPN OEM page for CPU cores, upgradeable RAM ceiling, storage slots, OS edition, Ethernet, and virtualization capability.
- Performance: only if “how many nodes/VMs” or a response-time target is requested and suitable reproducible data exists.

For “AI fine-tuning”:

- First resolve base model and revision, method (full/LoRA/QLoRA), precision/quantization, sequence length, batch/gradient accumulation, framework/version, dataset scale, target time, and whether CPU/offload is acceptable.
- Retrieve the official model card and framework method docs.
- Run a validated memory estimator or exact benchmark. Do not use a universal “parameter count → VRAM” lookup as a hard truth.

### 4.3 Source policy

| Tier | Allowed use |
|---|---|
| A — official software/OEM/component/model publisher | Requirements, compatibility, attested specs |
| B — official project documentation/repository/release notes | Requirements and version behavior when publisher-owned |
| C — reproducible exact laptop/configuration benchmark | Behavioral performance |
| D — professional review with disclosed configuration/settings | Supporting performance evidence, not hard requirement |
| E — forum/community report | Risk flag or query refinement only |
| F — affiliate/SEO content | Never a decision claim |

Search results can discover a source; the source must then pass domain, publisher, licence, tenant, freshness, identity, and claim-type policy before its claims enter a ledger.

---

## 5. The nine supplied products: what the evidence already teaches us

This is not a final workload ranking. It is an identity and evidence-readiness review as of 2026-08-08.

| Supplied listing | Current observation | Decision-system implication |
|---|---|---|
| Lenovo LOQ Ryzen 7 170 / RTX 3050 | Supplied retailer URL was not reliably retrievable in this review | Keep all capability cells unknown until the exact MPN/configuration is attested |
| Lenovo Legion 5i, `83LY001SAU` | JB Hi-Fi currently exposes i9-14900HX, 32 GB RAM, 1 TB SSD, RTX 5070 Laptop 8 GB, Windows 11 Home | Good worked example: strong numeric specs do not solve Hyper-V Home incompatibility or 8 GB behavioral limits ([retailer listing](https://www.jbhifi.com.au/products/lenovo-legion-5i-15-1-wqxga-165hz-oled-gaming-laptop-intel-core-i9geforce-rtx-5070)) |
| Lenovo Legion 9i supplied as RTX 5080 | Search currently also exposes an RTX 5090 configuration under a near-identical product family and different exact model | Never resolve by family title; bind the supplied SKU to exact MPN and configuration hash ([current RTX 5090 listing](https://www.jbhifi.com.au/products/lenovo-legion-9i-18-wquxga-240hz-gaming-laptop-intel-core-ultra-9-275hxgeforce-rtx-5090)) |
| MSI Crosshair 16 HX / RTX 5070 | Supplied URL did not yield enough independent configuration evidence | Unknown until exact model/MPN source is enrolled |
| MSI Thin A15 supplied as Ryzen 7 | Search exposes a similar Ryzen 5 / 8 GB / RTX 3050 4 GB listing | Slug/title similarity is unsafe; require exact identity ([similar current listing](https://www.jbhifi.com.au/products/msi-thin-a15-15-fhd-144hz-gaming-laptop-ryzen-5-geforce-rtx-3050)) |
| HyperX OMEN / RTX 5070 | Retailer catalogue evidence identifies 24 GB RAM, 1 TB and RTX 5070 8 GB for an exact retailer model, but the product page is only partly crawlable | Treat as retailer-observed until OEM configuration evidence corroborates it ([retailer page](https://www.jbhifi.com.au/products/hyperx-omen-15-3-wqxga-gaming-laptop-intel-core-i7geforce-rtx-5070)) |
| ASUS ROG Zephyrus Duo `GX651AX-SR004W` | ASUS Australia identifies the exact configuration family: Ultra 9 386H, RTX 5090 Laptop 24 GB, Windows 11 Home; exact RAM/storage must remain configuration-bound | OEM page can attest capabilities; retailer page supplies price/availability ([ASUS specs](https://rog.asus.com/au/laptops/rog-zephyrus/rog-zephyrus-duo-2026/spec/)) |
| Gigabyte AORUS Master 16 `6ZJM6AUE64SH` | Scorptec currently describes Ryzen 9 9955HX3D, 32 GB, 1 TB, RTX 5090 Laptop 24 GB, Windows 11 Home | High GPU memory still does not imply every workload, OS, or scale fits ([Scorptec listing](https://www.scorptec.com.au/product/laptops-and-notebooks/gigabyte-laptops)) |
| MSI Titan 18 HX `A2WJ-1038AU` | Scorptec exposes Ultra 9 290HX Plus, 64 GB, 2 TB, RTX 5090 Laptop 24 GB at up to 175 W, Windows 11 Pro, 128 GB memory ceiling | Rich exact-config evidence makes stronger bounded claims possible, but performance still needs workload/settings evidence ([Scorptec listing](https://www.scorptec.com.au/product/laptops-%26amp%3B-notebooks/gaming-laptops/126982-titan-18-hx-a2wj-1038au)) |

Prices and availability are observations with short TTLs, not stable product capabilities. The same product family can contain different GPU, RAM, storage, OS, panel, and regional configurations.

---

## 6. What the narration should sound like

### 6.1 Ambiguous digital twin

Bad:

> This powerful RTX laptop is a great choice for digital twins and cyber simulation.

Proposed first response:

> “Digital twin” can mean different workloads that favour different hardware. Are you mainly building **an OT/SCADA lab with virtual machines**, **a 3D machine model in Omniverse/Unreal**, **a predictive-maintenance model from sensor data**, or a combination? If you name the software and approximate scale, I can check this exact laptop against official requirements and your stock/deadline.

If branch decisions already agree, avoid the question:

> I’m assuming a small local OT lab because you mentioned attack simulation. All surviving interpretations need more than a generic gaming label, so I’ll verify virtualization, RAM, OS edition, and storage before calling any model suitable.

### 6.2 OT cyber lab using GNS3 + Client Hyper-V

Assume the buyer selected the Legion 5i `83LY001SAU` and confirmed a small GNS3 lab hosted with Client Hyper-V.

> **Conditional—not ready as sold for the host you named.** The exact listing records 32 GB RAM, a 24-core i9-14900HX, 1 TB SSD, and Windows 11 Home. Those hardware facts are promising for a small lab, but Microsoft says Client Hyper-V requires Windows Pro or Enterprise and cannot be installed on Windows Home. Your VM/node count and image requirements are still unresolved, so I cannot confirm the scale yet.  
> **Ways forward:** budget for a Windows Pro upgrade, choose another supported hypervisor after checking its requirements, or compare a workstation/server option if this lab must grow.

Evidence basis: Microsoft’s current Hyper-V installation documentation explicitly excludes Windows Home, while GNS3 describes its published hardware floor as a small-environment minimum ([Microsoft](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/Install-Hyper-V), [GNS3](https://docs.gns3.com/docs/getting-started/installation/windows)).

### 6.3 3D digital twin in Omniverse USD Composer

Assume the same Legion 5i and the buyer selects USD Composer.

> **Meets the published minimum; below the published “Good” GPU-memory tier.** The exact listing reports 32 GB RAM and 8 GB GPU memory. NVIDIA’s current USD Composer table lists 16 GB RAM / 8 GB VRAM as minimum and 32 GB RAM / 24 GB VRAM as “Good”. That supports a bounded compatibility claim, not a promise about your scene. I still need scene size, render mode, resolution, and target frame rate before estimating how it will perform.  
> If large scenes or sustained rendering matter, compare a 24 GB laptop configuration, a fixed workstation, or cloud rendering before paying for portability.

Evidence basis: [NVIDIA USD Composer requirements](https://docs.omniverse.nvidia.com/composer/latest/requirements.html).

### 6.4 Predictive maintenance for mining equipment

> This splits into two very different jobs: **classical analytics on telemetry** and **deep-learning training on images/waveforms**. The first is usually driven by dataset size, CPU/RAM, and storage; the second can be constrained by GPU memory and training time. What software/model are you using, how large is one training window or dataset, and do you need to train locally? Until that is known, I can describe the laptop’s capabilities but not honestly label it fit.

After resolution, the copy must name the branch and scale:

> **Qualified for the stated prototype scope:** the accepted requirements for `<artefact/version>` are met on RAM, storage, OS, and required libraries. **Production retraining throughput remains unverified** because no exact-laptop benchmark was found. A cloud training option avoids paying for peak GPU capacity that may sit idle, while this laptop remains the field/development client.

### 6.5 AI fine-tuning

> “AI fine-tuning” is not enough to size hardware. Please name the base model/revision and whether you mean full fine-tuning, LoRA, or QLoRA; also give precision/quantization, sequence length, and intended batch size. Hugging Face notes that PEFT reduces trainable parameters but is **not automatically memory-efficient**, and quantization/checkpointing trade memory against other costs. I won’t convert “8 GB” or “24 GB” into a guaranteed model size without a validated estimator or exact benchmark.

Evidence basis: [Hugging Face PEFT memory guidance](https://huggingface.co/docs/peft/main/developer_guides/memory_efficient_training) and [quantization guidance](https://huggingface.co/docs/peft/main/developer_guides/quantization).

Once resolved:

> **Conditional for local QLoRA, not qualified for the full-training interpretation.** This verdict applies only to `<model revision>`, `<method>`, `<precision>`, `<sequence>`, and `<batch>`. The capability ledger confirms `<VRAM/RAM/storage>`. The memory estimate has `<confidence band>` and leaves `<unknowns>`. The lower-cost alternative is to develop locally and run the training job on cloud/server infrastructure.

### 6.6 Fully modded Skyrim

> “Fully modded” needs a named modlist and preset. Is this Nolvus v6 Redux, Ultra, Ultimate, or a custom list, and at what resolution/FPS target? Nolvus’s own guidance distinguishes presets and warns that 8 GB VRAM/16 GB RAM should not be treated as sufficient for the full Ultra configuration. I can check the exact preset once selected; I should not turn “RTX 5070” into a frame-rate promise.

Evidence basis: [Nolvus official guide](https://www.nolvus.net/guide/asc/setup) and [official FAQ](https://www.nolvus.net/catalog/gamefaq).

### 6.7 Budget failure

> I found **no available laptop under AUD 2,500 that clears the accepted minimum for `<artefact/version and scale>`**. I have not relabelled the cheapest failing option as a recommendation. You can: increase the device budget, reduce the workload scale/target, use a laptop as a remote client with cloud/server compute, or request sourcing for an exact qualified configuration.

### 6.8 Narration block contract

Every buyer-facing explanation should render these blocks, in order:

1. **Verdict + exact scope**
2. **Why**: strongest passes and material failures
3. **Unknowns/contested claims**
4. **Assumptions and artefact/version**
5. **Budget/availability/deadline consequence**
6. **Next best resolver or architecture alternative**
7. **Evidence access**

The LLM may vary tone and compression but not block truth, claim values, verdicts, or scope.

---

## 7. Proposed desktop UX wireframe

### 7.1 Ambiguity first: do not rank yet

```text
┌──────────────────────── ShopSquire Assistant ─────────────────────────┬──────── Evidence / inventory ────────┐
│ YOU                                                                  │ Workload                            │
│ I need a laptop for a digital twin to simulate an OT cyber attack.   │ “digital twin” — unresolved         │
│                                                                      │ 3 plausible readings                │
│ ASSISTANT                                                            │                                      │
│ That phrase points to workloads with different bottlenecks.          │ Evidence status                      │
│ One answer will prevent me recommending the wrong architecture:      │ Discovery       ready / consent ✓    │
│                                                                      │ Requirements    waiting on branch   │
│ ┌─ Which describes the work? ──────────────────────────────────────┐ │ Inventory       9 exact SKUs loaded  │
│ │ ○ OT/SCADA lab — VMs, hypervisor, device images                  │ │                                      │
│ │ ○ 3D twin — Omniverse/Unreal, scenes and rendering               │ │ Why no ranked list?                  │
│ │ ○ Predictive maintenance — sensor data/model training            │ │ The surviving readings can select   │
│ │ ○ A combination                                                  │ │ different products.                 │
│ └──────────────────────────────────────────────────────────────────┘ │                                      │
│ [Continue]  [Show the differences first]                             │ [View hypothesis trace]              │
│                                                                      │                                      │
│ No product has been qualified and your cart is unchanged.            │                                      │
└──────────────────────────────────────────────────────────────────────┴──────────────────────────────────────┘
```

### 7.2 Selected product: inline fit receipt

```text
┌──────────────────────── ShopSquire Assistant ─────────────────────────┬──────── Selected product ────────────┐
│ ASSISTANT                                                            │ Lenovo Legion 5i                    │
│ CONDITIONAL — small GNS3 lab with Client Hyper-V                     │ MPN 83LY001SAU                      │
│                                                                      │ AUD 3,599 · availability observed   │
│ The hardware clears the accepted small-environment checks, but the   │                                      │
│ listed Windows 11 Home edition cannot host Client Hyper-V. Scale is  │ ┌─ FIT FOR YOUR STATED SCOPE ──────┐ │
│ still unresolved because I do not know the VM/node count.            │ │ Compatibility  ✕ conditional      │ │
│                                                                      │ │ Performance    ? unverified       │ │
│ ┌─ Fit receipt ────────────────────────────────────────────────────┐ │ │ Scale          ? VM count needed   │ │
│ │ RAM          required ≥ …   observed 32 GB      ✓ minimum        │ │ │ Commercial     ◐ OS upgrade cost  │ │
│ │ CPU/virt     required …     observed …          ✓ / evidence     │ │ └──────────────────────────────────┘ │
│ │ Host OS      Pro/Ent        Windows 11 Home     ✕ below          │ │                                      │
│ │ VM scale     buyer input    not supplied        ? unknown        │ │ [Why?] [Compare architectures]     │
│ └──────────────────────────────────────────────────────────────────┘ │ [Add only after review]             │
│                                                                      │                                      │
│ Resolve this                                                         │ Cart unchanged                      │
│ [I can upgrade to Pro] [Use another hypervisor] [About 12 VMs]       │                                      │
│                                                                      │                                      │
│ Alternatives: [Mobile workstation] [Fixed workstation] [Server/cloud]│                                      │
│ [Open full evidence ledger]                                          │                                      │
└──────────────────────────────────────────────────────────────────────┴──────────────────────────────────────┘
```

### 7.3 Branch comparison when one question is not yet answered

```text
┌─ SAME PHRASE, DIFFERENT DECISIONS ──────────────────────────────────────────────────────────────────────────┐
│                                                                                                             │
│ OT / SCADA virtual lab                3D Omniverse twin                   Predictive-maintenance training     │
│ Primary constraints                   Primary constraints                 Primary constraints                │
│ RAM · CPU cores · OS · hypervisor     VRAM · RAM · driver · scene scale   method · model · data · runtime     │
│                                                                                                             │
│ Legion 5i       CONDITIONAL           Legion 5i       MINIMUM ONLY         Legion 5i       UNRESOLVED          │
│                 Win Home conflict                      8 GB vs 24 GB good                    no model/method     │
│                                                                                                             │
│ Titan 18 HX     QUALIFIED*            Titan 18 HX     GOOD-TIER INPUTS*    Titan 18 HX     UNRESOLVED          │
│                 scale still needed                     perf unverified                       no model/method     │
│                                                                                                             │
│ *Scope-bounded; not a behavioral guarantee.                                                                     │
│                                                                                                             │
│ [VMs/hypervisors]  [3D scenes/rendering]  [sensor/model training]  [combination]                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.4 Full evidence ledger

```text
┌─ DECISION LEDGER · dcn_01J… · version 4 ────────────────────────────────────────────────────────────────────┐
│ Workload: GNS3 <version> + Client Hyper-V · small lab · assumption: 8–12 nodes                              │
│ Product: 83LY001SAU · configuration hash … · Laptop                                                         │
│                                                                                                             │
│ ATTRIBUTE   CLASS          REQUIRED             OBSERVED             VERDICT       SOURCES                   │
│ Host OS     minimum        Win Pro/Enterprise   Windows 11 Home      BELOW MIN     req-17 · cap-42           │
│ RAM         minimum        ≥ … GB               32 GB                MEETS MIN     req-18 · cap-43           │
│ RAM         recommended    ≥ … GB               32 GB                …             req-19 · cap-43           │
│ VM count    scale input    8–12                 buyer supplied       accepted      buyer-7                    │
│ Throughput  behavioral     target not stated    no exact benchmark   UNKNOWN       resolver: benchmark       │
│                                                                                                             │
│ Source health: REQUIREMENT fresh ✓ · PRODUCT exact ✓ · PERFORMANCE not requested · INVENTORY 3 min old ✓    │
│ Critic: PASS — no unknown promoted, caveats retained, laptop GPU identity exact                              │
│                                                                                                             │
│ [Open source] [Show conflict history] [Export decision] [Report an error]                                   │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.5 Architecture alternative drawer

```text
┌─ WHERE SHOULD THIS WORKLOAD RUN? ───────────────────────────────────────────────────────────────────────────┐
│ No architecture is selected automatically. These are comparison classes, not substitute SKUs.              │
│                                                                                                             │
│ CLASS                BEST WHEN                         TRADE-OFF / OPEN EVIDENCE                             │
│ Laptop               portability is mandatory         thermals, upgrades, local GPU ceiling                │
│ Mobile workstation   certified drivers/ECC matter     cost and weight                                      │
│ Fixed workstation    sustained local performance      not portable                                         │
│ Server               shared VMs/data/governance       admin, network, licensing                            │
│ Cloud                 burst/rare peak compute          recurring cost, data transfer, tenancy               │
│                                                                                                             │
│ [Compare total cost] [Keep laptop as remote client] [Return to product]                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Proposed mobile wireframe

```text
┌──────────────────────────────┐
│ ShopSquire        Evidence 3 │
├──────────────────────────────┤
│ Digital twin is ambiguous    │
│ No product ranked yet        │
│                              │
│ Which describes your work?   │
│ ┌──────────────────────────┐ │
│ │ OT/SCADA lab            │ │
│ │ VMs · hypervisor        │ │
│ └──────────────────────────┘ │
│ ┌──────────────────────────┐ │
│ │ 3D twin                 │ │
│ │ scenes · rendering      │ │
│ └──────────────────────────┘ │
│ ┌──────────────────────────┐ │
│ │ Predictive maintenance  │ │
│ │ telemetry · ML          │ │
│ └──────────────────────────┘ │
│ [Combination]                │
├──────────────────────────────┤
│ Why I’m asking               │
│ These branches rank the nine │
│ products differently.        │
└──────────────────────────────┘

After selection:

┌──────────────────────────────┐
│ Legion 5i · 83LY001SAU       │
│ CONDITIONAL                  │
├──────────────────────────────┤
│ ✓ RAM       32 GB            │
│ ✕ Host OS   Windows Home     │
│ ? Scale     VM count needed  │
│ ? Perf      no exact test    │
├──────────────────────────────┤
│ This is not ready for Client │
│ Hyper-V as sold.             │
│                              │
│ [Resolve OS]                 │
│ [Compare architectures]      │
│ [Full evidence]              │
├──────────────────────────────┤
│ Cart unchanged               │
└──────────────────────────────┘
```

UX rules:

- On mobile, show verdict, one failure, and one unknown before any prose.
- Keep evidence source links behind a sheet, but never hide the qualification scope.
- A research continuation must show which lanes are pending/timed out.
- “Add” remains separate from “qualify”; never imply the cart changed.
- Preserve the resolved workload and product identity across turns.

---

## 9. Test strategy before LLM narration continues

### 9.1 Contract and invariant tests

- Same exact MPN against five artefact/version floors produces five different decisions with no core code change.
- Unknown capability never passes.
- Unverified requirement never fails a product.
- Laptop/desktop GPU ambiguity is a resolution error.
- Requirement class and scope caveat survive compiler → decision → UI → narration.
- Timed-out material lane results in `UNKNOWN`/degraded, not catalog sufficiency.
- Budget never upgrades a failing product into a recommendation.
- Unavailable product never becomes the primary purchasable recommendation.
- Superseded source revisions invalidate only affected decision rows.
- Infrastructure projection always returns all five classes and selects none without buyer authority.

### 9.2 Product identity tests

- Exact MPN/MTM/GTIN match.
- Same family with RTX 5080 versus RTX 5090 remains distinct.
- Regional suffix/configuration differences remain distinct.
- Retailer structured specs versus prose contradiction produces `CONTESTED`.
- Missing structured table may fall back to prose only as a lower-confidence observation, never an OEM-attested fact.
- Product capability claim cannot be copied from a family page unless the exact configuration is explicitly in scope.

### 9.3 Workload golden matrix

Build reviewed fixtures across all nine supplied products and at least these branches:

1. OT lab: GNS3 + Hyper-V, GNS3 + another selected hypervisor, small/medium/large node counts.
2. 3D twin: USD Composer version + minimum/good tiers + scene/target unknowns.
3. Predictive maintenance: classical CPU pipeline versus deep vision/time-series training.
4. AI: inference, LoRA, QLoRA, and full fine-tuning with named model revisions/settings.
5. Skyrim: named Nolvus version/preset/resolution/FPS.

For each fixture, humans label:

- surviving interpretation(s);
- material question;
- authoritative claims and disallowed claims;
- row verdicts;
- overall scope-bounded decision;
- acceptable architecture alternatives;
- copy claims that may/may not appear.

This is separate from—and must not bypass—the eight relevance slates in `tests/golden/relevance_labels.json`. Those slates need honest human review before sealing.

### 9.4 Metamorphic tests

- Changing only the workload flips fit while product facts stay constant.
- Changing only the product configuration flips affected rows only.
- Changing budget does not change compatibility truth.
- Changing availability does not change capability truth.
- Removing a source changes a pass/fail row to unknown, not its opposite.
- Changing “digital twin” to a named artefact removes the generic branch question.
- Follow-up pronouns (“it”, “that laptop”) preserve exact product and workload state.

### 9.5 Narration tests

- Every sentence-level factual claim references authorized claim IDs.
- No product, price, unit, deadline, requirement, or performance result absent from the Decision Object.
- Unknown and contested material facts are mentioned.
- Overall wording matches decision enum and scope.
- No “good choice”, “will handle”, “future-proof”, or frame-rate promise without the needed evidence class.
- Deterministic fallback covers every decision state.
- LLM rejection leaves the deterministic answer in place.
- Compound explain/cart messages return an explanation and a separate pending mutation plan.

### 9.6 Live and end-to-end tests

- Cold/warm official provider calls with captured response evidence and TTL behavior.
- Provider timeout, disconnect, invalid publisher, stale revision, wrong tenant, credential failure, conflict, and recovery.
- Real nine-product identity ingestion followed by OEM corroboration.
- Browser journey: ambiguous ask → one question → research consent → evidence progress → selected product → follow-up → cart confirmation.
- Required multi-turn regression: workload and exact MPN survive at least five turns.
- Deadline journey: quantity/needed-by produces per-allocation evidence and one merged confirmation.
- Accessibility: keyboard selection, screen-reader verdict/state changes, focus return from evidence drawer.

### 9.7 Performance and model certification

Measure these separately:

```text
T_interpret
T_provider_each + T_provider_total
T_normalize_reduce_critic
T_template
T_model_queue + T_model_generation
T_total_first_answer
T_research_continuation
```

Certification gate:

- three consecutive warm runs under 8 seconds for the **model stage and total buyer response**, reported separately;
- deterministic first response remains available when the model is cold, queued, absent, or rejected;
- no unexplained residual “provider overhead”—every provider attempt has queue/connect/TTFB/parse timing and a status;
- quality gate passes all golden narration invariants, not just latency.

---

## 10. Reordered roadmap

### Gate 0 — Preserve truth and rollback now

1. Keep `recommend_compat.py` until every later gate passes.
2. Keep recommendation core/cart/pilot flags independently reversible.
3. Finish human review of the eight relevance slates; do not seal draft labels merely to turn CI green.
4. Record the current deterministic response and workload-fit golden traces before schema changes.

**Exit:** reviewed labels, reproducible baseline, rollback tested in non-production.

### Gate 1 — Unify semantics and identity

1. Choose `recommendation_core/fit.py` as the single authoritative reducer; retire or demote the RAM/VRAM-only `workload_fit.py` projection.
2. Remove authoritative use of persona KB floors. Keep personas as hypothesis/cache/ranking metadata.
3. Add exact configuration identity/hash to every product capability decision.
4. Replace “meets all N requirements” with “meets the N checks currently verified” plus coverage status.
5. Finish per-hypothesis fan-out and max-information clarification behavior.

**Exit:** ambiguous workload cannot authorize a product; exact configuration persists across turns.

### Gate 2 — Extend the evidence schemas

1. Add artefact/version, requirement class, scope caveat, revision/freshness, and supersession to requirement claims.
2. Add claim class, form factor, configuration identity, confidence band, settings, and conflict sets to capability claims.
3. Add a behavioral performance evidence contract.
4. Integrate the five-class infrastructure projection into the Decision Object.
5. Implement claim-reference-based narration blocks and typed derivations.

**Exit:** one serializable Decision Object answers compatibility, performance, scale, and commercial questions separately.

### Gate 3 — Enrol real sources

1. Enrol concept discovery as hypothesis-only.
2. Enrol official requirement sources for the first narrow artefact set: GNS3/selected hypervisor, USD Composer, Hugging Face/model cards, and Nolvus.
3. Enrol product sources: Lenovo PSREF plus OEM/configuration sources for ASUS, Gigabyte, MSI, HP, Intel, and NVIDIA where licensing permits.
4. Configure credentials, publisher review, tenant allowlists, domain allowlists, licence/robots policy, claim-type policy, and freshness SLA.
5. Store raw response hashes/metadata and normalized claims for replay.

**Exit:** successful and deliberately failed live-provider evidence, with freshness and tenant isolation proven.

### Gate 4 — Deterministic decision and critic

1. Implement the two-layer verdict model.
2. Add conflict/supersession and gap-directed retry.
3. Apply capability gate → budget gate → availability/deadline gate in that order.
4. Add adversarial critic invariants.
5. Build the reviewed workload/product golden matrix.

**Exit:** deterministic template copy is honest and useful without an LLM.

### Gate 5 — LLM narration in shadow

1. Narrator receives only authorized narration blocks/claim IDs.
2. Run deterministic and LLM copy side by side; never let shadow copy mutate recommendations or cart.
3. Evaluate unsupported-claim rate, omitted-unknown rate, verdict contradiction, clarity, latency, and guard rejection.
4. Isolate provider execution from model execution and certify three consecutive sub-8-second warm responses.
5. Use async enhancement if the model cannot reliably meet the synchronous budget.

**Exit:** zero critical unsupported claims on the reviewed golden set and live pilot traces; latency gate met.

### Gate 6 — UX integration

1. Ship ambiguity branch card, inline fit receipt, full evidence ledger, and source-health states.
2. Integrate architecture alternative drawer.
3. Merge quantity and fulfilment into one confirmation decision.
4. Preserve workload, artefact/version, exact MPN, and pending mutations across turns.
5. Validate desktop/mobile/accessibility journeys.

**Exit:** screenshots 50–53 classes remain fixed and workload explanations remain traceable across five turns.

### Gate 7 — Platform-wide pre-pilot evidence

These are required before the broader product pilot, but should not block isolated workload-fit development:

- real IMAGE disconnect/concurrent-provider tests;
- physical microphone and hosted ASR/TTS tests;
- real fulfilment/deadline evidence;
- operator dashboards for stale/conflicting sources and narration rejection;
- security/privacy review of external queries and retained source material.

**Exit:** evidence exists from real devices/providers, not only fixtures.

### Gate 8 — Pilot identities and deliberate rollback

1. Configure named pilot tenants/users and source policies.
2. Start with deterministic narration; enable guarded LLM narration for a small cohort.
3. Deliberately trigger and observe rollback independently for research, narration, recommendation core, and cart mutation.
4. Review decision traces with humans before increasing exposure.

**Exit:** rollback is observed, not assumed; no critical claim or commerce-authority incident.

### Gate 9 — Compatibility retirement decision

Only after Gates 0–8 pass should the deprecated V2 compatibility endpoint be reconsidered. Retirement is an explicit migration decision with traffic evidence and rollback, not an automatic cleanup task.

---

## 11. Immediate next sprint

The highest-value next sprint is not “improve the prompt.” It is:

1. Define `WorkloadContract v1`, extended `RequirementClaim v2`, `CapabilityClaim v2`, `BehavioralClaim v1`, and `WorkloadDecision v1`.
2. Make exact product configuration and artefact/version mandatory for a qualified decision.
3. Demote generic persona floors and unify the two fit paths.
4. Replace “meets all N requirements” throughout API/UI copy.
5. Build five reviewed fixtures using two exact products first:
   - Legion 5i `83LY001SAU` as the constrained/mid-tier case;
   - Titan 18 HX `A2WJ-1038AU` as the high-capability/Windows Pro case.
6. Implement the deterministic copy blocks and critic.
7. Only then wire the narrator in shadow against the same Decision Object.

This produces a narrow vertical slice that can prove the architecture before source and product coverage expands to all nine listings.

---

## Final product principle

ShopSquire should not answer “Is this laptop powerful?” It should answer:

> **For this named workflow, version, scale, target, and execution shape, which facts are established, which checks pass, what remains unknown, and what purchase or architecture decision follows?**

That distinction is the defensible product.
