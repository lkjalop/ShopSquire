# PowerBI .pbix Starter (Manual Steps)

Creating a `.pbix` file requires PowerBI Desktop. I can't generate the binary here, but this guide produces a starter report that uses the BI views in `db/views/shopSquire_bi_views.sql`.

## 1) Apply BI views
```sql
-- Run in Postgres
\\i db/views/shopSquire_bi_views.sql
```

## 2) Open PowerBI Desktop
1. Get Data → PostgreSQL.
2. Server: `localhost`
3. Database: `shopsquire`
4. Choose **Import** mode.
5. Enter credentials: `postgres / postgres` (or your own).

## 3) Select views
Select:
- `bi_orders_daily`
- `bi_decisions_daily`
- `bi_security_daily`
- `bi_inventory_top`

## 4) Create basic visuals
- Line chart: `bi_orders_daily` (Axis: day, Values: order_count, Legend: status)
- Line chart: `bi_decisions_daily` (Axis: day, Values: decision_count)
- Line chart: `bi_security_daily` (Axis: day, Values: event_count, Legend: severity)
- Table: `bi_inventory_top` (sku, name, stock)

## 5) Save
Save as `ShopSquire_BI_Starter.pbix` in your preferred directory.

## Optional
Use the SQL in `docs/POWERBI_CONNECTOR.md` for custom queries.
