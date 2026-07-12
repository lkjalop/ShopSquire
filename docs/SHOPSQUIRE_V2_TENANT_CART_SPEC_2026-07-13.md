# R10.2 — Tenant-Cart Identity Threading Spec (2026-07-13)

**STEP 1 LANDED (this commit): `draft_orders.tenant_id TEXT NOT NULL DEFAULT 'default'`** —
schema.sql + models/db.py guarded ALTER + alembic `20260713_draft_orders_tenant` + index
`(tenant_id, customer_id, status)`. Additive, zero behavior change; every existing row backfills
to `'default'` (today's single-tenant truth).

**STEP 2 (next session, fresh context): thread tenant through every read/write.** Doing half the
surfaces in one sitting creates a split-brain identity (review-6 #5 class) — thread ALL of these
in one change, then one test sweep:

## The threading map (every `draft_orders` touch point)
| Surface | What changes |
|---|---|
| `routers/cart.py` `_get_or_create_cart(uid)` :117 | → `(tenant, uid)`; SELECT + INSERT gain tenant_id. **The chokepoint — most handlers flow through it.** |
| `routers/cart.py` `_save_cart` :136 / `_load_cart_row` :154 / `_save_cart_versioned` :167 | scope WHERE by tenant; INSERT stamps it |
| `routers/cart.py` :453 (cart-age read) | WHERE + tenant |
| `services/recommendation_facade.py` `_read_cart_slice` :158 | already receives tenant upstream — add param + WHERE |
| `services/cart_mutation_service.py` :17 (apply path reads cart via _load_cart_row) | thread tenant from the PLAN row (plans are already tenant-keyed — the plan's tenant is the authority) |
| `routers/orders.py` (INSERT at checkout) | stamp tenant_id from X-Tenant-Id |
| `routers/account.py` (UPDATE customer_id merge) | WHERE + tenant (guest→account merge must not cross tenants) |
| `routers/privacy.py` :290/291/328/369/370 (export/delete) | WHERE + tenant (privacy ops are per-tenant!) |
| `routers/returns.py` :60/79 | WHERE + tenant |
| `routers/recommend.py` :2571 | WHERE + tenant |
| `services/checkout_upsell.py` (2 reads) | WHERE + tenant |
| `services/multi_intent_live.py` | WHERE + tenant |
| `services/retention_sweeper.py` | sweeps stay GLOBAL (cross-tenant retention is correct) — annotate, don't scope |
| `routers/admin_inventory.py` (ops list) | global admin view OK today; add tenant column to output |

## Rules
- Tenant source = `X-Tenant-Id` header convention (P0.3) — never client body, never derived from uid.
- INSERTs stamp tenant; SELECT/UPDATE/DELETE add `AND tenant_id = :t`. No dual-read fallback needed
  (backfill already normalized every row to 'default').
- Undo/redis keys (`cart:undo:{uid}`-style) get the same `{tenant}:{uid}` namespacing in this pass —
  grep `undo` in cart.py + cart_mutation_service.py.
- Tests: cross-tenant isolation proof (cart created under t1 invisible to t2 same uid); the
  existing cart/mutation suites re-run green; privacy export scoped.

## Explicitly NOT in scope
`orders`/`returns` table identities (separate debt), per-user auth identity (SoD blocker), any
behavior change while only step 1 is landed.
