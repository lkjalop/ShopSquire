# Conversation and merchant evidence

Scope: bounded fictional-shop demonstrations. These results do not establish
arbitrary long-context recall, real supplier truth or a model quality winner.

## Conversation restoration

`frontend/e2e/memory-restart.spec.ts` prepares a tablet request with GBP budget,
Osaka delivery and a correction from six to nine units. After an actual backend
restart, the browser restores the case and verifies API, terminal and visible
facts. Different tenants, users, epochs and temporary sessions do not inherit it;
an explicit subject change starts another case without old accepted requirements.

The browser exposed two genuine bugs: currency/destination corrections were not
committed consistently, and duplicate-message detection omitted tenant identity.
Regression tests now cover both. Shared procurement schemas validate the retained
facts; product-specific facts and research authority are not copied into memory.

Artifacts under `.artifacts/roadmap-execution-2026-10-01/`:

- `recall-green.xml`: 49 passing focused backend tests.
- `delivery-green.xml`: 40 passing reducer/continuity/stock tests.
- `delivery-browser.json`: currency and destination correction journey passes.
- `restart-prepare.json`: preparation before the actual restart passes.
- `merchant-memory-browser.json`: restart/isolation and merchant journeys both
  pass, zero skipped or flaky tests; browser traces and videos accompany it.

Earlier failed runs remain preserved. The broader 20-turn quantity test is also
retained; these checks are not a sustained mixed-model soak.

## Governed merchant context

`scripts/enrich_merchant_pilot_evidence.py` ran the installed local Qwen model
against one fictional supplier note. It extracted two numeric observations in
13,219 ms. Exact quotations, numeric values and frozen synthetic review labels
were checked before an immutable snapshot was appended. The extraction receipt
records the model digest; the labels are fixture review, not independent customer
validation.

`merchant_evidence_retrieval.py` filters tenant/SKU scope, expiry, revocation and
review bindings before retrieval. It combines lexical and local embedding ranks,
returns source citations, reports semantic-provider failure explicitly, and blocks
conflicting evidence from decision use. The browser exercised the actual local
embedding provider and read-only card. Supporting prose cannot authorize purchases
or silently replace the typed reorder baseline.

- `merchant-extraction.json`: model receipt and appended snapshot identity.
- `merchant-context-tests.xml`: 11 passing extraction/retrieval/snapshot tests.
- Additional injection fixture verifies source instructions cannot self-approve
  claims and raw canary-bearing source content is not projected as authority.
- `merchant-memory-browser.json`: visible citations, model retrieval, wrong-scope
  absence and anonymous-access rejection pass against the real API.

Independent relevance labels, external-data usefulness and representative model
comparisons remain roadmap work. Evidence must be refreshed after its expiry;
the fictional quote is not permanently current.
