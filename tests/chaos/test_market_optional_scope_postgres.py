"""Optional taxonomy lookups must preserve a caller's actual PostgreSQL transaction."""
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.chaos.test_request_database_owner_postgres import native_owners
from tests.services.test_market_admission_budget import market_finding
from src.app.services.market_analysis import _FINDING_DDL, persist_findings
from src.app.services.market_intelligence_agent import gather_market_context


@pytest.mark.parametrize('classification', ['absent', 'incomplete', 'complete'])
def test_optional_market_scope_preserves_pending_business_work(native_owners, classification):
    engine = native_owners[0]
    with engine.begin() as connection:
        connection.execute(text(_FINDING_DDL))
        connection.execute(text('CREATE TABLE pending_business(value INTEGER)'))
        if classification == 'incomplete':
            connection.execute(text('CREATE TABLE product_classification(sku TEXT)'))
        elif classification == 'complete':
            connection.execute(text('CREATE TABLE product_classification(tenant_id TEXT,sku TEXT,node_handle TEXT,status TEXT)'))
            connection.execute(text("INSERT INTO product_classification VALUES ('lab-market-tenant','SKU-MARKET','el-6-6','approved')"))
    finding = market_finding('CURRENT_ADMITTED_RECORD')
    if classification == 'complete':
        finding = replace(finding, entity_ref='native-family', evidence={**finding.evidence,
            'subject_type': 'taxonomy', 'subject_id': 'el-6-6', 'taxonomy_node': 'el-6-6'})
    with Session(engine) as db:
        assert persist_findings(db, [finding], tenant_id='lab-market-tenant') == 1
        db.commit()
        db.execute(text('INSERT INTO pending_business VALUES (17)'))
        result = gather_market_context(db, query='Market intelligence for this request',
            result_skus=['SKU-MARKET'], tenant_id='lab-market-tenant', force=True, include_graph=False)
        assert result['delivery_status'] == 'available'
        assert result['market_findings'][0]['scope'] == ('taxonomy' if classification == 'complete' else 'this_item')
        assert 'CURRENT_ADMITTED_RECORD' in result['narration_note']
        assert db.scalar(text('SELECT value FROM pending_business')) == 17
        with engine.connect() as observer:
            assert observer.scalar(text('SELECT COUNT(*) FROM pending_business')) == 0
        db.rollback()
    with engine.connect() as observer:
        assert observer.scalar(text('SELECT COUNT(*) FROM pending_business')) == 0
