"""Collect a bounded public-source observation with durable ingestion receipts."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--query-json', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from src.app.models.db import db_session
    from src.app.services.public_market_source_fetch import fetch_public_market_source
    from src.app.services.market_ingestion_observability import persist_run
    from src.app.services.market_signal_adapters import SourceBackfillReceipt
    started = datetime.now(timezone.utc).isoformat()
    tick = time.perf_counter()
    with db_session() as db:
        result = fetch_public_market_source(db, tenant_id=args.tenant, source_id=args.source,
                                           query=json.loads(args.query_json), enabled=True)
        finished = datetime.now(timezone.utc).isoformat()
        success = result['outcome'] in {'observed', 'cache_hit', 'not_modified'}
        observations = result.get('observations') or []
        receipt = SourceBackfillReceipt(source=args.source,
            status='completed' if success else 'source_unavailable',
            rows_read=len(observations), accepted=len(observations),
            outcomes={result['outcome']: len(observations)},
            error_code=None if success else result.get('error_code', result['outcome']),
            latency_ms=(time.perf_counter()-tick)*1000,
            watermark_after=finished if success else None)
        run_id = persist_run(db, tenant_id=args.tenant, receipt=receipt,
                             started_at=started, finished_at=finished)
        if not run_id:
            raise RuntimeError('market_ingestion_schema_missing')
        db.commit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'ingestion_run_id': run_id, 'tenant_id': args.tenant,
        'decision_scope': 'public_source_review_only_no_sku_exposure', **result}, indent=2), encoding='utf-8')
    print(json.dumps({'outcome': result['outcome'], 'observations': len(observations), 'run_id': run_id}))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
