# ShopSquire — Agnostic Commerce Data Model, Margin Economics & Integration Strategy
**2026-06-26 · design + research note**

Answers four questions you raised:
1. The supplier draft / case should compute **what the platform makes, the discount we can give the buyer, the supplier's price to us, and the profit.** Where does that math live?
2. **Will this be in a SQL DB?**
3. **How do real ecommerce platforms actually store data** — ERP, data lake, SQL vs NoSQL?
4. **What agnostic data / inventory schema** should ShopSquire adopt for easy integration with ecommerce platforms *and* suppliers' stock?

---

## 1. The margin economics — what I built today

The economics is pure arithmetic over two numbers we already hold on a procurement case:

- **wholesale** = what the supplier charges *us* per unit → `validated_quote.unit_amount_cents` (operator-only; already redacted from the buyer).
- **retail** = what we list to the *buyer* per unit → derived from the buyer's selected fulfilment option.

New module [`services/fulfillment/economics.py`](../src/app/services/fulfillment/economics.py) computes, in <4 s, for the operator:

| metric | formula |
|---|---|
| gross profit | `retail − wholesale` (× qty) |
| margin % | `gross / retail` |
| **buyer-discount headroom** | `retail − wholesale/(1 − floor)` — the biggest discount that still clears the floor margin |
| profit after full discount | `wholesale · floor/(1 − floor)` |
| clears_floor? | `margin ≥ floor` |

Exposed at `GET /api/v1/fulfillment/cases/{id}/economics` (operator role only — **never** buyer-facing) and surfaced behind a **Deal economics** button in the operator room. It invents nothing: if there's no validated quote yet, it returns `{}`.

> This is the *calculation*. The *durable place* the inputs come from is question 4 — today wholesale lives on the case JSON and retail is derived from the option; once the canonical price/supplier tables below exist, the same `compute()` runs off a clean JOIN instead.

---

## 2 & 3. How real ecommerce platforms store data — and is it SQL?

**Short answer: the transactional core is relational SQL. Everything else is polyglot.** Real platforms run *polyglot persistence* — the right store per job, not one database:

| Concern | What real platforms use | Why | Source of truth? |
|---|---|---|---|
| Orders, payments, inventory ledger, POs, customers | **Relational SQL** (Postgres, MySQL; ERPs: NetSuite, SAP, Dynamics 365 BC) | Money + stock need **ACID, constraints, joins, transactions**. You cannot oversell or double-charge. | ✅ **Yes** |
| Product catalog / attributes (**PIM**) | Relational **+ JSONB**, or document store (Akeneo=MySQL, commercetools=API-first hybrid, Salsify, Shopify=MySQL) | Catalog attributes are **sparse + heterogeneous** across categories; JSON columns hold the variable part without 200 nullable columns. | ✅ Yes (for catalog) |
| Real-time stock / hot reads | **Redis / in-memory**, fronting the SQL ledger | Stock is read constantly; the cache absorbs reads, SQL stays the ledger. | ❌ cache |
| Search & discovery | **Elasticsearch / OpenSearch / Algolia** (inverted index = a NoSQL read model) | Full-text, facets, ranking. **Denormalized read model**, rebuilt from SQL. | ❌ projection |
| Analytics, forecasting, market-intel | **Data warehouse** (Snowflake, BigQuery, Redshift) + **data lake** (S3 / Delta / Iceberg), fed by **CDC/ETL** | Columnar, append-only, cheap scans over history. Models train here. | ❌ derived |
| Event backbone | **Kafka / Kinesis** streams | Decouple producers from consumers; replayable. | ❌ log |

**So: SQL vs NoSQL is the wrong framing — it's "right store per concern."**
- **SQL (Postgres)** = the system of record for anything involving money or stock. ShopSquire is *already* on Postgres — keep it there.
- **JSONB inside Postgres** = the agnostic escape hatch for vertical-specific attributes (this is exactly ShopSquire's "core agnostic, flavour in data" rule, expressed in the schema).
- **NoSQL document/search/columnar** = read models and analytics fed *from* the SQL truth — not a replacement for it.
- ShopSquire's `market_signal` stream is already the **append-only analytics feed** (the "data lake inflow" in miniature); it can later sink to a warehouse without changing the transactional core.

**The architecture stack real platforms layer (and where ShopSquire sits):**

```
Storefront / Agent  ─┐
                     ├─ OMS (order mgmt) ─┐
ShopSquire (intel +  │                    ├─ ERP (finance, master inventory, PO) ── SQL
 shift-left security)─┘   PIM (catalog) ──┘     WMS (warehouse) · Supplier EDI/API
        │
        ├─ Redis (hot reads/sessions)        ← ShopSquire already uses
        ├─ Search (discovery read model)
        └─ Warehouse/Lake (market-intel, forecasting)  ← market_signal feeds this
```

ShopSquire is **not** the ERP/OMS — it's the **intelligence + security layer on top**. That means its job is a **canonical agnostic model + adapters**, not owning the merchant's master data.

---

## 4. The agnostic schema ShopSquire should adopt

**Principle:** one vertical-blind canonical model in Postgres; per-platform/supplier **adapters** map external shapes → canonical (the same StoreProfile/adapter pattern already in the codebase). Variable attributes go in **JSONB**, never new columns per vertical.

### Canonical entities (separate *identity*, *price*, *stock*, *supply* — they change independently)

```
product            identity/marketing            (id, tenant_id, title, brand, category, attributes JSONB, gtin, status)
  └─ variant       the sellable SKU              (id, product_id, sku, attributes JSONB, gtin, status)
price_book_entry   retail price per channel/ccy  (variant_id, channel, currency, list_cents, sale_cents, valid_from/to)  ← bitemporal-friendly
inventory_level    stock per SKU per location    (variant_id, location_id, on_hand, reserved, available, source, updated_at)
supplier           who supplies                  (id, name, domains, reliability…)   ← EXISTS (supplier_catalog)
supplier_offer     supplier's price/terms per SKU(supplier_id, variant_id|sku, wholesale_cents, lead_time_days, moq, on_time_rate)  ← EXISTS-ish
external_ref       mapping to the source system  (entity_type, entity_id, platform, external_id, raw JSONB)  ← the adapter join table
```

Key design choices (and *why*):
- **Price is its own table, not a product column.** Prices are channel/currency/time-specific and change often; a `price_book_entry` keeps history (pairs naturally with the bitemporal pattern already used in `fulfillment_case_version`).
- **`supplier_offer.wholesale_cents` + `price_book_entry.list_cents` = the margin economics**, by JOIN. The `economics.compute()` I shipped today becomes a query over these instead of case JSON.
- **`inventory_level` separates on_hand / reserved / available** — the only honest way to avoid overselling; "available = on_hand − reserved." This is what `cart.py`'s stock gate and the fulfilment `availability_assessed` step both want.
- **`external_ref`** is the integration seam: one row per (canonical entity ↔ platform external id), with the raw payload retained for audit/debug. Adapters write here; nothing in core references a platform.
- **`attributes JSONB`** holds GPU/refresh-rate/produce-grade/whatever — flavour stays in data, enforced by the existing `test_no_flavour_in_core.py` ratchet.

### Integration adapters (read + write, idempotent)

- **Ecommerce platforms:** Shopify Admin API (products/variants/`inventory_levels`, webhooks), Magento, WooCommerce, BigCommerce. Pattern already exists: `market_signal_adapters.backfill_from_db` (periodic) + webhook (real-time), both **idempotent via a dedup key**.
- **Supplier stock/price:** modern REST/CSV feeds, or **EDI** for enterprise suppliers — X12 **846** (inventory advice), **850** (PO), **855** (PO ack), **810** (invoice). ShopSquire's `fulfillment/external_comms` is already the bounded inbound/outbound boundary; an EDI/API adapter slots in behind it.
- **Standards to speak (interoperability):** **GS1 GTIN** (global product id), **schema.org/Product**, **Google Merchant feed** spec, **GDSN** for supplier master data. Storing `gtin` on product/variant makes cross-platform matching deterministic.

### What to build next (recommended order)
1. ✅ **DONE** (`6890a9e`) `price_book_entry` + `inventory_level` (`services/commerce_catalog.py`, alembic `20260626_commerce_catalog`, drift-tested, single head). Flag: `COMMERCE_CATALOG_ENABLED` (default-OFF).
2. ✅ **DONE** (`6890a9e`) Shopify adapter (`services/shopify_catalog_adapter.py`) — products+inventory → canonical, idempotent. (`external_ref` table still **TODO** — the adapter currently maps `inventory_item_id → sku` in-memory; a persistent mapping table is the next hardening.)
3. ✅ **DONE** (`6890a9e`) `economics.from_case` re-pointed: retail = override > price_book JOIN (flag-gated) > selected option. The calc is unchanged.
4. ✅ **DONE** (`5995db2`) `product` + `variant` + `external_ref` (`services/catalog_entities.py`, alembic `20260626_catalog_entities`); Shopify adapter persists `external_ref`; a **Magento** adapter writes the same canonical tables (seam proven platform-blind); `supplier_catalog.cheapest_wholesale_cents` wholesale fallback wired into `economics.from_case`.
5. ✅ **DONE** (`<this batch>`) inventory-source adapter (`services/inventory_source.py`) — `availability_agent` reads canonical `inventory_level` (per-sku overlay) when `COMMERCE_CATALOG_ENABLED`, so a real catalog shortfall drives the buyer procurement case.
6. **TODO** Sink `market_signal` to a warehouse table/export for the forecasting detectors (Track B) when volume warrants — *not before*.

---

## TL;DR
- **Yes, SQL** — Postgres stays the system of record for money/stock/orders; JSONB carries vertical attributes; NoSQL/search/warehouse are *read models* fed from it, not replacements.
- ShopSquire is the **intelligence + security layer**, so its asset is a **canonical agnostic model + adapters**, mirroring the StoreProfile pattern already enforced by the no-flavour ratchet.
- The margin economics is **already computable today** (`economics.py`, operator-only); the canonical `price_book_entry` + `supplier_offer` tables turn it from "derived off case JSON" into a clean JOIN, and unlock the same margin/discount math everywhere.
