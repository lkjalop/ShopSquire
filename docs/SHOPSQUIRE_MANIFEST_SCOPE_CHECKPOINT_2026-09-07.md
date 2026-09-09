# Manifest scope checkpoint and next roadmap

7 September 2026. Implementation checkpoint, not deployment certification.

## Implemented this turn

1. Added a frozen `RequirementScope`: tenant, taxonomy product type, relationship, manifest ID/content revision and required attributes.
2. Compiler no longer unions all installed verticals. Missing/unsupported/stale scope is rejected. Cross-category attributes are explicitly rejected.
3. Added declared allowed uses to existing attribute definitions. Electronics storage and OS retain their existing roles while explicitly permitting fit use.
4. Wired both compiler entry paths: the computer-host adapter uses its explicit computer-family relationship and active request tenant/profile; the general semantic stage uses the clamped decision product type and role. Provider claims do not select the manifest.
5. Compiled predicates and structured claim projections retain scope. The revision-bound research outcome carries scopes and missing attributes.
6. Scoped completeness checks the manifest obligations per provider group. Minimum/recommended document headings cannot conceal missing CPU/GPU/OS/storage evidence. A complete scoped group can establish completeness without those headings; this does not itself grant catalog or commerce authority.
7. The shared research summary renders missing attributes and a manifest-scope details section.

## Verification

- Scope tests initially failed at collection because the new module did not exist.
- Missing-obligation and positive completeness regressions failed before implementation.
- UI missing-obligation test failed before rendering was added.
- Final combined backend run: **335 tests passed, native exit 0**.
- Shared-summary UI tests: **2 passed**.
- Frontend production build: **passed**.
- `git diff --check`: passed, with existing LF/CRLF warnings.

Tests include unsupported profile/category/relationship, cross-category rejection, explicit storage use, stale/changed scope, tenant-context preservation, partial coverage and complete scoped coverage. This is not the full integration or browser suite.

Evidence logs: `C:/AI/ShopSquire-checkpoints/test-isolation-20260907/scope-*.log`.

## Important limitations

- The manifest snapshot is still file-backed and content-addressed, not an immutable published database manifest. It describes loaded registry definitions; live manifest publication/cache invalidation remains future work.
- The structured adapter pins the computer family (`el-6`); exact requested descendant binding and case-revision validation across every background path still need completion.
- This does not remove legacy unscoped outcome compatibility or every other requirement compiler in the platform.
- The hardware obligation set is a baseline. Conditional API/architecture/performance obligations, and capability-aware model comparison, remain unfinished.
- No production coffee/grocery/pharmacy capability was approved or installed. Cross-category positive fixtures and packaging tests remain next work.
- No full trace reconciliation, live browser rerun, API restart, clean PostgreSQL or hosted certificate was performed. The running backend has not been reloaded onto these changes.
- No source review, commit, push, reset or deletion occurred. Earlier dirty changes remain preserved.

## Next order and why

### 1. Finish scoped evidence delivery

Preserve literal CPU/GPU/OS/storage claims and exact source spans through the existing extractor and hardware adapter. Keep derived comparisons separate. Validate operators appropriate to model compatibility rather than pretending model strings have numeric ordering. Carry exact resolved product and workload IDs into the pinned scope. Verify its case revision and tenant when asynchronous results return.

Reason: correct scoping cannot manufacture missing compatibility evidence. The positive shelf gate remains blocked until accepted evidence really covers the applicable obligations.

### 2. Reconcile all trace surfaces

Use the terminal result for Summary, Why, Evidence and Raw current-state projections. Historical branches may remain, explicitly marked superseded. Remove misleading verified-slate/no-evidence summaries. Show unmet obligations and source/derivation authority consistently in chat, claims and trace.

Reason: the earlier 15-panel browser audit proved navigation, but also proved contradictory content.

### 3. Run the buyer-delivery browser gate

With zero configured retries: complete accepted evidence plus matching permitted stock must render a non-empty qualified shelf. Partial/held/incompatible evidence must remain restricted. Test budget shortfall independently of stock shortfall, then explicit draft-only sourcing acceptance and absence of supplier dispatch/cart mutations. Check all 15 trace panels against the same operation/revision, not simply visible tabs.

Reason: these are buyer outcomes; unit-level completeness is not purchasing suitability or frontend certification.

### 4. Prove category generality with explicit fixtures

Use test-only coffee/grocery manifests, declared pack relations and inventory. Cover coffee purchase versus laptop for a coffee business, tenant/category switches, unknown items, quantities versus prices, mass/count/pack conversions and invalid dimensional conversions. Regulated product behavior remains governed and independently reviewed; no clinical substitutions or suitability claims arise from inventory alone.

Reason: two reviewed configurations exercising the same mechanism are stronger evidence of an agnostic core than more application-name rules.

### 5. Publish durable manifests and extract

Add immutable database manifest publications and tenant/category bindings through real migrations, with reviewed import/export and cache keys pinned to publication revision. Extract terminal projection first and research orchestration second using existing boundaries. Preserve one logical execution and terminal compare-and-set. Keep architecture ceilings unchanged.

Reason: extraction should preserve a sealed behavior contract, not relocate unresolved contradictions.

### 6. Certify and consolidate

Complete affected/full suites in different orders, clean-checkout and PostgreSQL reproduction, rotating live discovery and failure injection, then hosted certification. Human source reviews remain independent. Make dependency-complete source checkpoints including new modules and tests, excluding runtime data and credentials.
