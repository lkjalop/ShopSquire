from sqlalchemy import create_engine, text
e = create_engine('sqlite:///tmp/e2e.sqlite')
with e.connect() as c:
    sql = "SELECT sku, price_cents, name FROM products WHERE LOWER(name) LIKE '%apple%' OR LOWER(name) LIKE '%macbook%' ORDER BY price_cents"
    rows = c.execute(text(sql)).fetchall()
    for r in rows:
        print(f"{r[0]:20s} ${r[1]/100:.0f}  {r[2]}")
    print(f"Total apple/macbook: {len(rows)}")
    sql2 = "SELECT sku, price_cents, name FROM products WHERE LOWER(name) LIKE '%samsung t7%' ORDER BY price_cents"
    rows2 = c.execute(text(sql2)).fetchall()
    for r in rows2:
        print(f"T7: {r[0]:20s} ${r[1]/100:.0f}  {r[2]}")
