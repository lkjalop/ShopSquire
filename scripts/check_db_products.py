"""Quick DB product count check for tmp/e2e.sqlite."""
import os, sqlite3

db_path = os.path.join(os.path.dirname(__file__), "..", "tmp", "e2e.sqlite")
if not os.path.exists(db_path):
    print("DB NOT FOUND:", db_path)
    raise SystemExit(1)

con = sqlite3.connect(db_path)
total = con.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0]
print(f"Total active products: {total}")

for brand in ("msi", "apple", "asus", "dell", "lenovo"):
    rows = con.execute(
        "SELECT name, price_cents FROM products WHERE active=1 AND lower(name) LIKE ? ORDER BY price_cents LIMIT 5",
        (f"%{brand}%",)
    ).fetchall()
    if rows:
        print(f"\n{brand.upper()} ({len(rows)} shown):")
        for r in rows:
            print(f"  ${r[1]/100:.0f}  {r[0]}")

inv = con.execute(
    "SELECT p.name, i.stock FROM products p JOIN inventory i ON i.product_id=p.id "
    "WHERE p.active=1 AND lower(p.name) LIKE '%msi%'"
).fetchall()
print("\nMSI inventory:")
for r in inv:
    print(f"  stock={r[1]} {r[0]}")

con.close()
