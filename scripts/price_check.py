import sqlite3
conn = sqlite3.connect('tmp/e2e.sqlite')
rows = conn.execute("SELECT sku, name, price_cents FROM products WHERE sku GLOB 'LAP-*' ORDER BY sku").fetchall()
for r in rows:
    print(f"{r[0]} | ${r[2]/100:.0f} | {r[1][:60]}")
conn.close()
