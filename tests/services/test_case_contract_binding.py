from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.models.orm import Base, ShoppingCase
from src.app.services.case_contract_binding import (
    select_case_contract, read_case_contract_binding, revoke_case_contract,
    require_current_case_contract,
)
from src.app.services.requirement_contract import load_requirement_contract
from src.app.services.shopping_case_revision import advance_material_case_revision


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(ShoppingCase(case_id="case", tenant_id="tenant", uid="buyer", revision=1))
        session.commit()
        yield session
    engine.dispose()


def select(db, **changes):
    contract = load_requirement_contract(Path("config/requirement_contracts/blender-5.0-windows-opengl.json"))
    return select_case_contract(db, **dict(tenant_id="tenant", case_id="case", uid="buyer",
        expected_revision=1, contract_id=contract.id, context=contract.context, **changes))


def test_selection_survives_reload_and_advances_revision(db):
    selected = select(db)
    db.commit()
    db.expunge_all()
    actual = read_case_contract_binding(db, tenant_id="tenant", case_id="case", uid="buyer")
    assert selected["binding_id"] == actual["binding_id"]
    assert actual["case_revision"] == 2
    assert actual["state"] == "current"
    assert actual["commerce_authority"] == "none"


@pytest.mark.parametrize('query,expected', [
    ('Research Blender version 5.0 requirements against my selected scope.', True),
    ('Check the approved Blender sources.', True),
    ('Research Blender version 6.0 requirements.', False),
    ('Instead research Blender requirements.', False),
    ('Research Blenders requirements.', False),
    ('Buy a Blender subscription.', False),
    ('Research another application.', False),
])
def test_selected_research_continuity_only_matches_the_owned_subject_and_version(db, query, expected):
    from src.app.services.recommendation_core.case_binding import continues_selected_scope_research
    from src.app.services.recommendation_core.envelope import TurnEnvelope
    select(db)
    envelope = TurnEnvelope(tenant_id='tenant', uid='buyer', query=query, trace_id='test',
        session={'case_anchor':{'case_id':'case','revision':2}})
    assert continues_selected_scope_research(db, envelope) is expected


@pytest.mark.parametrize('change', [
    {'requested_quantity':40}, {'selected_sku':'OTHER'}, {'workloads':['different workload']},
    {'budget':{'amount_minor':10000,'currency':'USD','scope':'total'}},
    {'destinations':[{'location_ref':'other city','quantity':30}]},
    {'temporal':{'original_expression':'next Friday'}},
    {'requirements':{'accepted':[{'attribute':'capacity','value':64,'authority_status':'buyer_accepted'}]}},
])
def test_evidence_continuation_never_carries_changed_buyer_scope(db, change):
    from src.app.services.procurement_case_state import ProcurementCaseState
    from src.app.services.case_contract_binding import continue_unchanged_contract
    select(db)
    before=ProcurementCaseState(case_id='case',revision=2,requested_quantity=30)
    after=ProcurementCaseState.model_validate({**before.model_dump(),**change})
    assert continue_unchanged_contract(db,tenant_id='tenant',case_id='case',previous_revision=2,before=before,after=after) is None
    assert read_case_contract_binding(db,tenant_id='tenant',case_id='case',uid='buyer')['case_revision']==2


@pytest.mark.parametrize("tenant,uid", [("other", "buyer"), ("tenant", "other")])
def test_selection_is_owned_by_tenant_and_buyer(db, tenant, uid):
    with pytest.raises(ValueError, match="shopping_case_not_found|shopping_case_not_owned"):
        select_case_contract(db, tenant_id=tenant, case_id="case", uid=uid, expected_revision=1,
                             contract_id="unused", context=None)


def test_material_change_invalidates_binding_and_consumption(db):
    selected = select(db)
    advance_material_case_revision(db, tenant_id="tenant", case_id="case", expected_revision=2, reason="changed workload")
    actual = read_case_contract_binding(db, tenant_id="tenant", case_id="case", uid="buyer")
    assert actual["state"] == "stale_case_revision"
    with pytest.raises(ValueError, match="stale_case_revision"):
        require_current_case_contract(db, tenant_id="tenant", case_id="case", uid="buyer",
                                      binding_id=selected["binding_id"])


def test_revocation_cannot_fall_back_to_an_unselected_contract(db):
    selected = select(db)
    revoked = revoke_case_contract(db, tenant_id="tenant", case_id="case", uid="buyer",
                                  expected_revision=2, binding_id=selected["binding_id"])
    assert revoked["state"] == "revoked"
    with pytest.raises(ValueError, match="revoked"):
        require_current_case_contract(db, tenant_id="tenant", case_id="case", uid="buyer",
                                      binding_id=selected["binding_id"])


def test_stale_writer_cannot_replace_the_binding(db):
    selected = select(db)
    with pytest.raises(ValueError, match="case_revision_conflict"):
        select(db)
    assert read_case_contract_binding(db, tenant_id="tenant", case_id="case", uid="buyer")["binding_id"] == selected["binding_id"]


def test_contract_policy_change_invalidates_consumption(db, monkeypatch):
    selected = select(db)
    from src.app.services import case_contract_binding as service
    original = service.load_contract_by_id
    monkeypatch.setattr(service, "load_contract_by_id", lambda name: original(name).model_copy(update={"evidence_notes": ("policy changed",)}))
    assert read_case_contract_binding(db, tenant_id="tenant", case_id="case", uid="buyer")["state"] == "stale_contract_revision"
    with pytest.raises(ValueError, match="stale_contract_revision"):
        require_current_case_contract(db, tenant_id="tenant", case_id="case", uid="buyer", binding_id=selected["binding_id"])


def test_other_session_revocation_invalidates_previously_loaded_objects(tmp_path):
    from src.app.models.orm import ShoppingCaseContractSelection
    engine = create_engine('sqlite:///' + (tmp_path / 'case.sqlite3').as_posix())
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as reader:
        reader.add(ShoppingCase(case_id='case',tenant_id='tenant',uid='buyer',revision=1))
        reader.commit()
        selected = select(reader)
        reader.commit()
        # Keep strong references: a long-lived request may retain these ORM objects.
        cached_case = reader.query(ShoppingCase).filter_by(case_id='case').one()
        cached_binding = reader.get(ShoppingCaseContractSelection, selected['binding_id'])
        reader.commit()
        with Session(engine) as writer:
            revoke_case_contract(writer,tenant_id='tenant',case_id='case',uid='buyer',
                                 expected_revision=2,binding_id=selected['binding_id'])
            writer.commit()
        assert cached_case.revision == 2 and cached_binding.revoked_at is None
        with pytest.raises(ValueError, match='revoked'):
            require_current_case_contract(reader,tenant_id='tenant',case_id='case',uid='buyer',
                                          binding_id=selected['binding_id'])
    engine.dispose()


def test_catalog_consumption_cannot_ignore_case_owner(db):
    from src.app.services.accepted_catalog_projection import project_accepted_catalog
    with pytest.raises(ValueError, match='shopping_case_not_owned'):
        project_accepted_catalog(db,accepted_claims=[],tenant_id='tenant',case_id='case',uid='other')


def test_catalog_consumption_exposes_revoked_binding_without_fit(db):
    from src.app.services.accepted_catalog_projection import project_accepted_catalog
    chosen=select(db)
    revoke_case_contract(db,tenant_id='tenant',case_id='case',uid='buyer',expected_revision=2,binding_id=chosen['binding_id'])
    result=project_accepted_catalog(db,accepted_claims=[],tenant_id='tenant',case_id='case',uid='buyer')
    assert result.requirement_contract['state']=='revoked'
    assert result.requirement_contract['fit_authority']=='none'


def test_research_receipt_rejects_binding_changed_during_fetch(db):
    from src.app.services.case_contract_binding import assert_case_contract_unchanged
    receipt=read_case_contract_binding(db,tenant_id='tenant',case_id='case',uid='buyer')
    select(db)
    with pytest.raises(ValueError,match='changed_during_research'):
        assert_case_contract_unchanged(db,tenant_id='tenant',case_id='case',uid='buyer',receipt=receipt)


def test_complete_coverage_filters_exact_rows_even_with_duplicate_external_ids(db,monkeypatch):
    from datetime import datetime,timezone
    from src.app.services import case_contract_binding as service
    from src.app.services.requirement_contract import RequirementContract
    context=dict(subject='Unseen subject',version='1',platform='any',workload='bounded')
    contract=RequirementContract(id='test',context=context,obligations=[dict(id='capacity',attribute='capacity',
        tier='minimum',source_ids=['official'],max_age_hours=24)])
    monkeypatch.setattr(service,'load_contract_by_id',lambda _:contract)
    service.select_case_contract(db,tenant_id='tenant',case_id='case',uid='buyer',expected_revision=1,
                                 contract_id='test',context=context)
    now=datetime.now(timezone.utc)
    claim=dict(claim_id='same',attribute='capacity',requirement_class='minimum',source_id='official',
        authority_status='verified_official',applicability=context,observed_at=now.isoformat(),
        source_revision='r',source_excerpt='Capacity 12',value=12,operator='>=')
    unrelated=dict(claim,attribute='other',source_id='unapproved')
    allowed,receipt=service.gate_case_contract_consumption(db,tenant_id='tenant',case_id='case',uid='buyer',
        claims=[claim,unrelated],now=now)
    assert allowed==[claim]
    assert receipt['coverage']['coverage_complete']
    assert receipt['fit_authority']=='none'


def test_enrolled_research_discards_result_after_revocation(db,monkeypatch):
    import asyncio
    from src.app.services import shopping_case_enrolled_research as research
    from src.app.services.case_research_plan import build_case_research_plan
    chosen=select(db)
    db.commit()
    case=db.query(ShoppingCase).filter_by(case_id='case').one()
    monkeypatch.setattr(research,'external_search_readiness',lambda **_: {'effective':True})
    async def provider(*args,**kwargs):
        with Session(db.bind) as writer:
            revoke_case_contract(writer,tenant_id='tenant',case_id='case',uid='buyer',
                                 expected_revision=2,binding_id=chosen['binding_id'])
            writer.commit()
        return {'claims':[]}
    monkeypatch.setattr(research.official_workload_research,'research_official_sources',provider)
    plan=build_case_research_plan('I need a laptop for Blender rendering.')
    with pytest.raises(research.EnrolledResearchUnavailable) as failure:
        asyncio.run(research.execute_enrolled_official_research(db,plan=plan,
            approved_sources=[dict(source_id='test',review_status='approved',freshness_sla_hours=24,
                publisher_policy={'direct_origin_required':True},allowed_domains=['example.invalid'])],
            tenant_id='tenant',case_id='case',uid='buyer',case=case,hypothesis_ids=[],
            candidate_configuration_ids=[],budget_cents=None,runtime_status={},configured_search_url='',
            consent_receipt={'authorized':True}))
    assert failure.value.status_code==409
    assert failure.value.detail['code']=='case_contract_changed_during_research'
