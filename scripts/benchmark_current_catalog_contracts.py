"""Evaluate retrieval against frozen current catalogue facts, not subjective relevance labels."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def evaluate(facts, retrieve):
    snapshot = json.dumps(facts, sort_keys=True).encode()
    cases = []
    # Labels use independent equality/range predicates over frozen fields.
    # Missing catalogue metadata remains missing and is reported, never inferred.
    brands = sorted({r['brand'].lower() for r in facts if r['brand']})
    for brand in brands:
        for cap in (1000, 2000):
            expected = sorted(r['sku'] for r in facts if (r['brand'] or '').lower() == brand and r['active'] != 0
                              and r['price_cents'] is not None and r['price_cents'] <= cap*100)
            runs = []
            for _ in range(3):
                start = time.perf_counter()
                rows = retrieve(brand, brands=[brand], budget_max=cap, limit=len(facts)+1)
                runs.append({'elapsed_ms':round((time.perf_counter()-start)*1000,3),
                             'skus':[r['sku'] for r in rows]})
            missing = set().union(*(set(expected)-set(r['skus']) for r in runs))
            unsupported = set().union(*(set(r['skus'])-set(expected) for r in runs))
            cases.append({'brand':brand,'cap_aud':cap,'expected_skus':expected,'runs':runs,
                          'missing':sorted(missing),'unsupported':sorted(unsupported)})
    timings = [r['elapsed_ms'] for c in cases for r in c['runs']]
    passed = bool(cases) and all(not c['missing'] and not c['unsupported'] for c in cases)
    result = {'catalog_sha256':hashlib.sha256(snapshot).hexdigest(), 'catalog_count':len(facts),
              'missing_brand_count':sum(not r['brand'] for r in facts),
              'missing_category_count':sum(not r['category'] for r in facts),
              'cases':cases,'passed':passed,
              'status':'insufficient_data' if not cases else ('passed' if passed else 'failed'),
              'median_ms':statistics.median(timings) if timings else None,
              'promotion_authorized':False,
              'scope':'Current-catalogue brand/budget retrieval contracts. Not semantic relevance, buyer outcomes, tenant isolation, stock freshness, or an infrastructure comparison.'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    dbpath = args.database.resolve()
    con = sqlite3.connect(dbpath.as_uri()+'?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    facts = [dict(r) for r in con.execute('SELECT sku,name,brand,category,price_cents,active FROM products ORDER BY sku')]
    con.close()
    snapshot = json.dumps(facts, sort_keys=True).encode()
    os.environ.update(APP_ENV='local', DATABASE_URL='sqlite:///'+dbpath.as_posix(),
                      DATABASE_URL_RO='sqlite:///'+dbpath.as_posix())
    from src.app.services.candidate_retriever import from_db
    result = evaluate(facts, from_db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.catalog.json').write_bytes(snapshot)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
