# Memory, RAG Privacy, and Supply-Signal Freshness

Date: 2026-07-30

This is an engineering research note, not a claim of legal compliance or legal
advice. ShopSquire should describe these as GDPR-supporting technical controls
until counsel, contracts, operations, and an independent review cover the whole
processing system.

## Product-pattern review

The major assistant products converge on four useful patterns:

1. Conversation history and extracted long-term memory are separate products.
2. Users can disable or reset memory without deleting every conversation.
3. A temporary/incognito mode avoids adding a turn to durable memory.
4. Deletion is asynchronous and bounded rather than physically instantaneous.

Official product documentation reviewed:

- OpenAI separates saved memories from chat history, offers controls to delete
  or disable memory, and documents a generally 30-day deletion schedule for
  deleted and Temporary Chats:
  <https://help.openai.com/en/articles/8590148-memory-faq>
  and
  <https://help.openai.com/en/articles/8983778-chat-and-file-retention-policies-in-chatg>
- Anthropic describes project-separated memory, incognito chat, pause/reset
  controls, and removal of deleted conversations from memory synthesis:
  <https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context>.
  Its privacy documentation describes deletion from backend storage within a
  bounded period, subject to stated exceptions:
  <https://privacy.claude.com/en/articles/7996878-can-you-delete-data-sent-via-claude>
- xAI documents history controls, Private Chat, training controls, and a
  generally 30-day deletion process with stated security/legal exceptions:
  <https://x.ai/legal/faq>

The defensible ShopSquire design is not to imitate hidden provider
implementation details. It is to make the lifecycle explicit and testable.

## Required memory contract

Every conversational or retrieval artifact must be addressed by:

```text
tenant authority
  + pseudonymous subject identity
  + session epoch
  + artifact family
  + schema/embedding/model/prompt/policy versions
```

The contract must prevent:

- one tenant reading another tenant's context;
- a new session inheriting an expired or reset epoch accidentally;
- cache hits across incompatible embeddings, prompts, policy versions, access
  scopes, or source revisions;
- raw PII appearing in Redis keys, vector IDs, logs, or citation identities;
- extracted preferences overwriting authoritative Party/account facts.

The current implementation now provides tenant/subject/session-epoch memory
keys, a subject erasure index, bounded TTLs, versioned semantic-cache identity,
stable citation identities, and tenant/epoch-scoped durable chat messages.

## Deletion and control plane

GDPR principles that materially shape the implementation include storage
limitation (Article 5), transparent rights handling and the normal one-month
response period (Article 12), erasure and its exceptions (Article 17), and data
protection by design/default (Article 25):
<https://eur-lex.europa.eu/eli/reg/2016/679/oj>.

A production DSR should be a state machine:

```text
requested -> identity_verified -> scoped -> purge_queued
          -> primary_deleted -> derivatives_invalidated
          -> backup_expiry_recorded -> completed
          -> rejected_or_held (with reason and authority)
```

The purge fan-out must cover:

- relational chat rows and extracted observations;
- Redis memory, pending clarifications, and idempotency artifacts;
- vector chunks and retrieval indexes;
- semantic/RAG caches and citation manifests;
- object evidence where erasure is permitted;
- analytics copies and derived user-level features;
- provider-side data where ShopSquire is responsible for initiating deletion.

Completion needs an auditable receipt containing counts, stores contacted,
failures/retries, retention exceptions, legal-hold authority, and the latest
backup-expiry date. The receipt must not reproduce deleted content.

Still required before a compliance claim:

- operator DSR workflow and independently tested deletion receipts;
- authenticated tenant-scoped export/delete authorization;
- retry/dead-letter handling for every purge adapter;
- documented backup expiry and legal-hold precedence;
- data-processing records, contracts, transfer controls, and legal review;
- a browser proof for temporary/no-memory mode, reset, export, and deletion.

## Stable RAG citations

A citation is an identity, not a display URL. Its stable ID should derive from:

```text
tenant + source authority + source document ID + source revision
+ chunk boundary/version + normalization version
```

Retrieval results additionally record the query, access scope, embedding
version, index revision, retrieved-at time, score, and policy version. A source
revision invalidates dependent cache entries; it does not silently reuse the
old citation for changed text.

Temporal evaluation must enforce:

```text
source.available_at <= evaluation.origin_at
```

This prevents future revisions or outcomes leaking into historical retrieval
and forecast evaluation.

## Connecting public signals to real exposure

Public market information is advisory until a tenant-authorized mapping joins
it to the tenant's real exposure:

```text
signal scope
  -> material/component/commodity/index
  -> product/variant or BOM dependency
  -> supplier and facility
  -> logistics lane
  -> inventory/customer location
  -> contract, quote, lead-time, and substitution constraints
```

Without that path, the safe statement is “this is a market scenario worth
checking,” not “this product will rise by X%.”

Source cadence must drive freshness:

- USGS Mineral Commodity Summaries are annual, versioned structural evidence:
  <https://pubs.usgs.gov/publication/mcs2026>
- USDA WASDE is a scheduled, revised agricultural outlook:
  <https://www.usda.gov/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report>
- World Bank commodity price data is published as a monthly Pink Sheet:
  <https://www.worldbank.org/en/research/commodity-markets>
- EIA weekly petroleum publications have an explicit release schedule:
  <https://www.eia.gov/petroleum/supply/weekly/schedule.php>
- Eurostat trade data has publication lag and revisions:
  <https://ec.europa.eu/eurostat/web/international-trade-in-goods/information-data>
  and
  <https://ec.europa.eu/eurostat/data/data-revision-policy>
- GS1 EPCIS provides interoperable event semantics for supply-chain visibility:
  <https://ref.gs1.org/standards/epcis/2.0.1/>

Every stored signal therefore needs source ID, licence, release/revision ID,
effective period, retrieved/available times, expected next release, freshness
deadline, geographic/product scope, units, and contradiction group.

Stale handling is deterministic:

1. Serve a cached revision only inside its declared freshness window.
2. Mark stale-but-visible evidence as degraded; never present it as current.
3. Exclude stale evidence from authority-increasing decisions.
4. Keep the previous revision immutable and link corrections/supersession.
5. Group conflicting sources by comparable scope rather than averaging unlike
   units, geographies, periods, or definitions.
6. Require fresh supplier/BOM/location evidence before changing procurement
   authority.

## Evidence threshold for more autonomy

Memory quality, synthetic replay, and public signals cannot alone justify more
autonomy. The next authority level requires a tenant-authorized shadow dataset,
sealed forecasts and baselines, temporal leakage tests, calibrated uncertainty,
guardrail outcomes, and measured effects on forecast value added, service
level/stockouts, inventory investment, waste, margin, and operator workload.
