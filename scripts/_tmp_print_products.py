from src.app.models.db import db_session
from sqlalchemy import text
import json

with db_session() as d:
    rows = d.execute(text('SELECT sku, image_url FROM products LIMIT 6')).mappings().all()
    print(json.dumps(rows, indent=2, default=str))
