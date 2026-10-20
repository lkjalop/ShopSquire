"""Real migration and restore boundaries against disposable, populated SQLite."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = '20260874_post_purchase_satisfaction'
HEAD = '20260893_security_tenant_policy'


def migrate(database, target, *, direction='upgrade', check=True):
    env = os.environ.copy()
    env.update(APP_ENV='test', DATABASE_URL='sqlite:///' + database.as_posix(),
               DATABASE_URL_RO='sqlite:///' + database.as_posix(),
               PYTHONPATH=str(ROOT), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    result = subprocess.run([sys.executable, '-m', 'alembic', direction, target],
                            cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=30)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture()
def baseline(tmp_path):
    database = tmp_path / 'upgrade.sqlite3'
    migrate(database, BASE)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO products(id,sku,name,price_cents,currency,active) "
                   "VALUES('legacy-product','OWNED-UPGRADE','Existing product',120000,'AUD',1)")
        db.execute("INSERT INTO shopping_cases(id,case_id,tenant_id,uid,status,retained_purpose) "
                   "VALUES('legacy-case','sc-owned-upgrade','upgrade-tenant','buyer-before-upgrade',"
                   "'active','40 devices for an existing workload')")
        db.execute("INSERT INTO conversation_case_state(id,tenant_id,case_id,session_epoch,subject_ref,"
                   "state_json,created_at,updated_at) VALUES('legacy-state','upgrade-tenant',"
                   "'sc-owned-upgrade','epoch','owned-subject',?, '2026-10-21','2026-10-21')",
                   (json.dumps({'requested_quantity': 40, 'currency': 'AUD'}),))
        db.execute("INSERT INTO ragas_eval_results(eval_id,faithfulness) VALUES('legacy-eval',0.95)")
        db.execute("INSERT INTO security_events(id,details) VALUES('legacy-security-event','{}')")
        db.execute("INSERT INTO outbound_message(id,tenant_id,recipient,subject,body,idempotency_key,"
                   "created_at,updated_at) VALUES('legacy-message','upgrade-tenant',"
                   "'supplier@example.test','Existing draft','Existing body','legacy-idempotency',"
                   "'2026-10-21','2026-10-21')")
    return database


def retained_rows(database):
    with sqlite3.connect(database) as db:
        return {
            'product': db.execute('SELECT id,sku,name,price_cents,currency FROM products').fetchall(),
            'case': db.execute('SELECT case_id,tenant_id,uid,status,retained_purpose FROM shopping_cases').fetchall(),
            'state': db.execute('SELECT case_id,tenant_id,state_json FROM conversation_case_state').fetchall(),
            'draft': db.execute('SELECT id,tenant_id,recipient,subject,body,idempotency_key,status FROM outbound_message').fetchall(),
        }


def test_upgrade_preserves_existing_case_money_and_draft_without_granting_a_permit(baseline):
    before = retained_rows(baseline)
    migrate(baseline, 'head')
    migrate(baseline, 'head')
    assert retained_rows(baseline) == before
    with sqlite3.connect(baseline) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == (HEAD,)
        assert db.execute('SELECT tenant_id,evaluation_status FROM ragas_eval_results').fetchone() == (None, 'legacy_unverified')
        assert db.execute("SELECT tenant_id FROM security_events WHERE id='legacy-security-event'").fetchone() == (None,)
        assert db.execute('SELECT effect_digest,permit_expires_at,permit_revoked_at,person_approval_id FROM outbound_message').fetchone() == (None, None, None, None)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'dmarc_reports', 'dmarc_records', 'shopping_case_contract_selections',
                'inventory_reservation', 'person_effect_approval', 'outbound_recovery_observation',
                'supplier_enquiry_request', 'buyer_supplier_quote_selection'} <= tables


def test_contract_history_is_unique_per_tenant_case_revision(baseline):
    migrate(baseline, 'head')
    sql = ('INSERT INTO shopping_case_contract_selections '
           '(id,tenant_id,case_id,uid,case_revision,contract_id,contract_revision,context_json,selected_at) '
           "VALUES(?,?,'same-case','buyer',1,'contract','v1','{}','2026-10-21')")
    with sqlite3.connect(baseline) as db:
        db.execute(sql, ('first', 'tenant-a'))
        db.execute(sql, ('other-tenant', 'tenant-b'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql, ('duplicate', 'tenant-a'))
        assert db.execute('SELECT COUNT(*) FROM shopping_case_contract_selections').fetchone() == (2,)


@pytest.mark.parametrize("target", [BASE, "-14", "base"])
def test_protected_downgrade_is_rejected_before_any_history_is_dropped(baseline, target):
    migrate(baseline, 'head')
    with sqlite3.connect(baseline) as db:
        db.execute("INSERT INTO buyer_supplier_quote_selection VALUES("
                   "'owned-quote','upgrade-tenant','sc-owned-upgrade','buyer-before-upgrade',"
                   "1,'quote-1','digest','{\"audit\":\"RETAIN-ME\"}','2026-10-21')")
    before = retained_rows(baseline)
    response = migrate(baseline, target, direction='downgrade', check=False)
    assert response.returncode != 0
    with sqlite3.connect(baseline) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == (HEAD,)
        assert db.execute('SELECT quote_json FROM buyer_supplier_quote_selection').fetchone() == ('{"audit":"RETAIN-ME"}',)
    assert retained_rows(baseline) == before


def test_preupgrade_backup_restores_to_a_separate_database_and_can_upgrade_again(baseline, tmp_path):
    restored = tmp_path / 'restored-before-upgrade.sqlite3'
    before = retained_rows(baseline)
    with sqlite3.connect(baseline) as source, sqlite3.connect(restored) as target:
        source.backup(target)
    migrate(baseline, 'head')
    assert retained_rows(restored) == before
    with sqlite3.connect(restored) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == (BASE,)
    migrate(restored, 'head')
    assert retained_rows(restored) == before
    with sqlite3.connect(restored) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)


def test_empty_reversible_tail_can_downgrade_and_upgrade_again(baseline):
    migrate(baseline, 'head')
    before = retained_rows(baseline)
    migrate(baseline, '-2', direction='downgrade')
    with sqlite3.connect(baseline) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('20260891_governed_product_offers',)
    migrate(baseline, 'head')
    assert retained_rows(baseline) == before


def test_forward_repair_handles_an_existing_92_without_the_ownership_column(baseline):
    migrate(baseline, '20260892_buyer_supplier_selection')
    with sqlite3.connect(baseline) as db:
        db.execute('ALTER TABLE security_events DROP COLUMN tenant_id')
    migrate(baseline, 'head')
    with sqlite3.connect(baseline) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == (HEAD,)
        assert db.execute("SELECT tenant_id FROM security_events WHERE id='legacy-security-event'").fetchone() == (None,)
