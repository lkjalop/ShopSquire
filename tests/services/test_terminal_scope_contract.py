from src.app.services.chat_turn_projection import terminal_scope_contract


def test_unrelated_question_has_explicit_inapplicable_scope():
    result = terminal_scope_contract(scope=None, case_id=None, case_revision=None, applicable=False)
    assert result == {"catalog_scope": None, "catalog_scope_status": "not_applicable"}


def test_missing_and_stale_scope_are_not_bound():
    for scope in (None, {"case_id": "old", "case_revision": 1}):
        result = terminal_scope_contract(scope=scope, case_id="new", case_revision=2)
        assert result["catalog_scope_status"] == "unavailable"
        assert result["catalog_scope"] is None


def test_scope_is_bound_only_to_its_current_case_revision():
    scope = {"case_id": "case", "case_revision": 2, "tenant_id": "default"}
    result = terminal_scope_contract(scope=scope, case_id="case", case_revision=2)
    assert result["catalog_scope_status"] == "bound"
    assert result["catalog_scope"] == scope


def test_null_references_do_not_make_an_unpersisted_scope_bound():
    result = terminal_scope_contract(scope={"case_id": None, "case_revision": None}, case_id=None, case_revision=None)
    assert result["catalog_scope_status"] == "unavailable"
