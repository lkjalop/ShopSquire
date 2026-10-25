"""Create a new isolated SQLite portfolio shop from the August source document.

Existing paths are refused. Run as a module from the repository root.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scripts.seed_inventory_from_txt import parse_inventory
from src.app.models.orm import Product
from src.app.services.electronics_shop_scenario import seed_scenario, assess_request, _scenario
from scripts.backfill_brand_from_title import _brand_list, match_brand


# Reviewed source-section metadata for this fictional electronics importer.
# These nodes permit category retrieval only, never compatibility or stock authority.
SOURCE_CATEGORY_NODES = {
    'laptop': 'el-6-6', 'monitor': 'el-17-1', 'bag': 'lb-15',
    'hard_drive': 'el-7-9-14-4', 'router': 'el-12-1', 'tablet': 'el-6-8',
    'headset': 'el-2-2-7', 'printer': 'el-13-4', 'all_in_one': 'el-6-12',
    'mini_pc': 'el-6-3', 'desktop_tower': 'el-6-3',
}


def enrol_source_category(db, row, *, tenant_id):
    """Enrol admitted source metadata; unknown categories and held prices stay held."""
    from src.app.services.taxonomy_registry import upsert_classification, add_sold_node

    handle = SOURCE_CATEGORY_NODES.get(row['category'])
    if handle is None or row['price_cents'] is None:
        return False
    for function, kwargs in (
        (upsert_classification, dict(sku=row['sku'], node_handle=handle,
                                    status='approved', confidence=1)),
        (add_sold_node, dict(node_handle=handle)),
    ):
        if not function(db, tenant_id=tenant_id, source='simulation:source-category',
                        approved_by='synthetic-fixture-only', **kwargs):
            raise RuntimeError('source_category_enrolment_failed')
    return True


def add_product(db, row):
    """Keep source category and conservative, reviewed title metadata at ingestion."""
    product = Product(sku=row['sku'], name=row['name'], price_cents=row['price_cents'],
                      currency='AUD', specs=row['specs'], active=True)
    db.add(product)
    db.flush()
    # These migrated projection columns are not mapped by the legacy Product ORM.
    db.execute(text('UPDATE products SET brand=:brand, category=:category WHERE id=:id'),
               dict(brand=match_brand(row['name'], _brand_list()),
                    category=row['category'], id=product.id))
    return product


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=Path('docs/2026-08-08 laptop-products-aug.txt'))
    args = parser.parse_args()
    path = args.database.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects all existing databases, including previous demos.
    with path.open('xb'):
        pass
    url = 'sqlite:///' + path.as_posix()
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True,
                   env={**os.environ, 'APP_ENV': 'local', 'DATABASE_URL': url, 'DATABASE_URL_RO': url})
    rows = parse_inventory(args.source.read_text(encoding='utf-8'))
    fixture = _scenario()
    engine = create_engine(url)
    reports = []
    held = []
    with Session(engine) as db:
        for row in rows:
            if row['price_cents'] is None:
                held.append(row)
                continue
            add_product(db, row)
            seed_scenario(db,tenant_id='synthetic-electronics',sku=row['sku'],retail_cents=row['price_cents'])
            enrol_source_category(db, row, tenant_id='synthetic-electronics')
        db.flush()
        from src.app.services.portfolio_qualification import seed_configuration
        seed_configuration(db)
        example = next(row for row in rows if row['category'] == 'laptop' and row['price_cents'] is not None)
        for quantity in (30, 40):
            reports.append(assess_request(db,tenant_id='synthetic-electronics',sku=example['sku'],
                quantity=quantity,now=datetime.fromisoformat(fixture['effective_from'])))
        db.commit()
    engine.dispose()
    report = dict(simulation_only=True,database=str(path),source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                  admitted_snapshot_products=len(rows)-len(held),held_records=held,
                  scenario_time=fixture['effective_from'],requests=reports,
                  limits=['unverified catalogue snapshots','fixed illustrative stock per SKU',
                          'no order execution, compatibility certification or live supplier contact'])
    path.with_suffix('.report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('held_records','requests')}))


if __name__ == '__main__':
    main()
