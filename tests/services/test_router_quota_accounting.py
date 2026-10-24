"""A disabled router must not spend tokens; real admission stays enforced."""
import pytest

from tests.services.test_recommendation_facade import _Redis, _wt
from src.app.services.recommendation_core.envelope import CoreResponse, ProductCard
from src.app.services.recommendation_facade import dispatch_recommendation_core_typed
from src.app.services.token_budget import TokenBudget, estimate_tokens


class BudgetRedis(_Redis):
    def incrby(self, key, amount):
        self.store[key] = int(self.store.get(key, 0)) + amount

    def incrbyfloat(self, key, amount):
        self.store[key] = float(self.store.get(key, 0)) + amount


@pytest.mark.parametrize('model_outcome,charged', [('disabled', False), ('mock_disabled', False), ('ok', True)])
def test_only_executed_or_unknown_model_work_is_charged(monkeypatch, model_outcome, charged):
    monkeypatch.setenv('RECOMMEND_CORE_MODE', 'primary')
    monkeypatch.setenv('TOKEN_BUDGET_ENABLED', '1')
    monkeypatch.setenv('TOKEN_BUDGET_DEFAULT_TIER', 'guest')
    backend = BudgetRedis()

    def core(db, envelope):
        result = CoreResponse(envelope=envelope, lane='SEARCH', grounding='grounded',
            products=[ProductCard(sku='OWNED', title='Owned catalog listing', price_cents=1000)], message='Listing only.')
        result.extras['model_invocation'] = {'outcome': model_outcome}
        return result.finalize()

    monkeypatch.setattr('src.app.services.recommendation_core.core.recommend_turn', core)
    result = dispatch_recommendation_core_typed(object(), backend, query='show the catalog', uid='quota-controls',
        tenant_id='shop', budget_min=None, budget_max=None, trace_id='owned', with_trace=_wt)
    assert result.served
    assert TokenBudget(backend).get_usage('quota-controls')['tokens'] == (estimate_tokens('show the catalog') if charged else 0)


def test_existing_quota_rejection_still_stops_model_dispatch(monkeypatch):
    monkeypatch.setenv('RECOMMEND_CORE_MODE', 'primary')
    monkeypatch.setenv('TOKEN_BUDGET_ENABLED', '1')
    monkeypatch.setenv('TOKEN_BUDGET_DEFAULT_TIER', 'guest')
    monkeypatch.setenv('TOKEN_BUDGET_GUEST_DAILY_TOKENS', '1000')
    backend = BudgetRedis()
    TokenBudget(backend).record_usage('quota-controls', 1000, 0)
    called = []
    monkeypatch.setattr('src.app.services.recommendation_core.core.recommend_turn', lambda *a: called.append(True))
    result = dispatch_recommendation_core_typed(object(), backend, query='show the catalog', uid='quota-controls',
        tenant_id='shop', budget_min=None, budget_max=None, trace_id='owned', with_trace=_wt)
    assert result.status == 'blocked' and result.reason == 'quota:daily_token_limit'
    assert called == []
