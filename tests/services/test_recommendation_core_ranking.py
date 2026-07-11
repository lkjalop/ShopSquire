"""Lexicographic ranking: each stage only breaks ties the prior left, and no learned score
can override a hard truth (a cheaper OOS item never outranks an in-stock match)."""
from src.app.services.recommendation_core.envelope import ProductCard
from src.app.services.recommendation_core.ranking import rank, rank_key


def _c(sku, price=None, stock=None, overall=None, failed=0):
    fit = None
    if overall:
        per = {f"k{i}": False for i in range(failed)}
        fit = {"overall": overall, "per_key": per, "unknown_keys": []}
    return ProductCard(sku=sku, price_cents=price, stock=stock, fit=fit)


def test_fit_group_dominates_everything():
    # a cheap, in-stock FAILING item must sink below a pricey, OOS MEETING item
    meets = _c("M", price=999999, stock=0, overall="meets")
    fails = _c("F", price=1, stock=99, overall="fails", failed=1)
    assert [c.sku for c in rank([fails, meets])] == ["M", "F"]


def test_availability_beats_relevance_and_price():
    # same fit group: in-stock outranks unknown-stock outranks OOS, before price
    a = _c("OOS", price=1, stock=0)
    b = _c("UNK", price=1, stock=None)
    c = _c("IN", price=999, stock=5)
    assert [x.sku for x in rank([a, b, c])] == ["IN", "UNK", "OOS"]


def test_relevance_order_preserved_within_ties():
    # all identical except retrieval order → relevance decides
    cards = [_c("A", price=100, stock=1), _c("B", price=100, stock=1), _c("C", price=100, stock=1)]
    assert [x.sku for x in rank(cards, retrieval_order=["C", "A", "B"])] == ["C", "A", "B"]


def test_value_breaks_remaining_ties_cheaper_first():
    cards = [_c("EXP", price=2000, stock=1), _c("CHEAP", price=500, stock=1)]
    assert [x.sku for x in rank(cards)] == ["CHEAP", "EXP"]


def test_missing_price_sinks_but_stays_above_wrong_fit():
    noprice = _c("NP", price=None, stock=1)
    priced = _c("P", price=1500, stock=1)
    assert [x.sku for x in rank([noprice, priced])] == ["P", "NP"]


def test_stable_sku_tiebreak_is_deterministic():
    cards = [_c("Z", price=100, stock=1), _c("A", price=100, stock=1)]
    assert [x.sku for x in rank(cards)] == ["A", "Z"]
    # identical inputs → identical output (the property the shadow differ relies on)
    assert rank(list(cards)) == rank(list(cards))


def test_fewest_failed_keys_within_fails_group():
    two = _c("TWO", price=1, stock=1, overall="fails", failed=2)
    one = _c("ONE", price=999, stock=1, overall="fails", failed=1)
    assert [x.sku for x in rank([two, one])] == ["ONE", "TWO"]


def test_limit_applies_after_ordering():
    cards = [_c("A", price=300, stock=1), _c("B", price=100, stock=1), _c("C", price=200, stock=1)]
    assert [x.sku for x in rank(cards, limit=2)] == ["B", "C"]
