"""M2-B2: the intrinsic quality gate (quality.py) + its wiring into summarize_run.

The proofs GPT-5.6's spec demanded: one safe-but-irrelevant product FAILS (precision alone is
gameable — NDCG + empty-rate close the hole); unmeasured relevance is a FAILURE not a pass
(labeled-coverage floor); unauthorized (over-budget/duplicate) shown products are never
acceptable; and a parity-green run cannot promote past a red quality gate."""
from src.app.services.recommendation_core.quality import (
    DEFAULT_THRESHOLDS,
    case_labels,
    evaluate_case_quality,
    ndcg_at_k,
    precision_at_k,
    summarize_quality,
)


def _resp(products):
    return {"products": products}


def _card(sku, price=1000.0, brand="acme", fit=None):
    d = {"sku": sku, "price": price, "brand": brand}
    if fit is not None:
        d["workload_fit"] = {"overall": fit, "per_key": {}}
    return d


_LABELS = {"cases": {
    "c1": {"labels": {"A": 2, "B": 1, "C": 0, "D": 1}},
}}


# ── labeled metrics ──────────────────────────────────────────────────────────────

def test_precision_and_ndcg_reward_the_right_slate():
    lab = case_labels(_LABELS, "c1")
    assert precision_at_k(["A", "B", "D"], lab) == 1.0
    assert precision_at_k(["A", "C", "ZZZ"], lab) == 1 / 3      # unlabeled counts NOT relevant
    assert ndcg_at_k(["A", "B", "D"], lab) > ndcg_at_k(["D", "B", "A"], lab)  # rank-aware
    assert ndcg_at_k(["A", "B", "D"], lab) > 0.9


def test_one_safe_but_irrelevant_product_fails_the_gate():
    """The anti-gaming proof: a single grade-0 product gives precision 0 AND ndcg 0 — and even
    a single grade-1 product (precision 1.0!) cannot reach the NDCG floor against a label set
    whose ideal slate is richer."""
    lab = case_labels(_LABELS, "c1")
    assert precision_at_k(["C"], lab) == 0.0 and ndcg_at_k(["C"], lab) == 0.0
    assert precision_at_k(["B"], lab) == 1.0                    # gameable alone…
    assert ndcg_at_k(["B"], lab) < DEFAULT_THRESHOLDS["ndcg_at_10_min"]   # …but NDCG says no


# ── per-case label-free metrics ──────────────────────────────────────────────────

def test_unauthorized_counts_over_budget_and_duplicates():
    row = evaluate_case_quality(
        {"id": "x", "budget_max": 1500},
        _resp([_card("A", 1400), _card("B", 1600), _card("A", 1400)]))
    assert row["unauthorized"] == 2          # one over-budget + one duplicate SKU
    assert row["shown"] == 3


def test_constraint_satisfaction_and_empty():
    row = evaluate_case_quality(
        {"id": "y"}, _resp([_card("A", fit="meets"), _card("B", fit="fails"),
                            _card("C", fit="unknown")]))
    assert row["verdict_count"] == 3 and row["meets_count"] == 1 and row["fails_shown"] == 1
    empty = evaluate_case_quality({"id": "z"}, _resp([]))
    assert empty["empty"] is True
    refusal = evaluate_case_quality({"id": "r", "expects_products": False}, _resp([]))
    assert refusal["empty"] is False         # an expected refusal is not an empty failure


# ── run-level gate ───────────────────────────────────────────────────────────────

def _good_rows(n=10):
    return [evaluate_case_quality(
        {"id": f"g{i}", "budget_max": 2000},
        _resp([_card("A", 1000, "acme", "meets"), _card("B", 1200, "bravo", "meets"),
               _card("C", 1400, "carbon", "meets")])) for i in range(n)]


def test_gate_fails_on_unmeasured_relevance_not_passes():
    s = summarize_quality(_good_rows())
    assert s["gates"]["pass"] is False
    assert any("labeled_coverage" in f for f in s["gates"]["failures"])
    assert any("UNMEASURED" in f for f in s["gates"]["failures"])


def test_gate_passes_with_labels_and_clean_slate():
    labels = {"cases": {f"g{i}": {"labels": {"A": 2, "B": 1, "C": 1}} for i in range(10)}}
    rows = [evaluate_case_quality(
        {"id": f"g{i}", "budget_max": 2000},
        _resp([_card("A", 1000, "acme", "meets"), _card("B", 1200, "bravo", "meets"),
               _card("C", 1400, "carbon", "meets")]), labels=labels) for i in range(10)]
    s = summarize_quality(rows)
    assert s["labeled_coverage"] == 1.0 and s["precision_at_10"] == 1.0
    assert s["gates"]["pass"] is True, s["gates"]["failures"]


def test_gate_fails_on_unauthorized_even_when_labeled_green():
    labels = {"cases": {f"g{i}": {"labels": {"A": 2, "B": 1, "C": 1}} for i in range(10)}}
    rows = [evaluate_case_quality(
        {"id": f"g{i}", "budget_max": 1100},                      # B and C now OVER budget
        _resp([_card("A", 1000, "acme", "meets"), _card("B", 1200, "bravo", "meets"),
               _card("C", 1400, "carbon", "meets")]), labels=labels) for i in range(10)]
    s = summarize_quality(rows)
    assert s["unauthorized_rate"] > 0
    assert s["gates"]["pass"] is False
    assert any("unauthorized" in f for f in s["gates"]["failures"])


def test_empty_rate_bounds_the_do_nothing_strategy():
    rows = _good_rows(8) + [evaluate_case_quality({"id": f"e{i}"}, _resp([])) for i in range(2)]
    s = summarize_quality(rows)
    assert s["empty_rate"] == 0.2
    assert any("empty_rate" in f for f in s["gates"]["failures"])


# ── summarize_run wiring: parity-green cannot promote past a red quality gate ────

def test_summarize_run_requires_quality_when_supplied():
    from src.app.services.recommend_parity_full import summarize_run
    parity_green = []   # zero cases → zero BLOCKERs, mc rate 0/1... need real green diffs
    # minimal green parity diff rows
    diff = {"severity": "INFO", "dimensions": {"message_class": {"match": True},
                                               "product_set": {"jaccard": 1.0, "order_matches_v1": True},
                                               "gates": {"match": True}}}
    diffs = [dict(diff) for _ in range(5)]
    base = summarize_run(diffs)
    # review-6 #1: an unmeasured run is diagnostically clean but NOT promotable.
    assert base["quality_evaluated"] is False
    assert base["diagnostic_pass"] is True and base["gates_pass"] is False
    red_quality = summarize_quality(_good_rows())          # fails on labeled coverage
    gated = summarize_run(diffs, quality=red_quality)
    assert gated["quality_evaluated"] is True
    assert gated["gates_pass"] is False                    # parity-green + quality-red = NO
    green_labels = {"cases": {f"g{i}": {"labels": {"A": 2, "B": 1, "C": 1}} for i in range(10)}}
    green_rows = [evaluate_case_quality(
        {"id": f"g{i}", "budget_max": 2000},
        _resp([_card("A", 1000, "acme", "meets"), _card("B", 1200, "bravo", "meets"),
               _card("C", 1400, "carbon", "meets")]), labels=green_labels) for i in range(10)]
    ok = summarize_run(diffs, quality=summarize_quality(green_rows))
    assert ok["gates_pass"] is True


# ── review-9 #2: server-side catalog authorization (the composite unauthorized gate) ──

def _authz_db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    s = sessionmaker(bind=create_engine("sqlite://"))()
    s.execute(text("CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE, name TEXT, "
                   "price_cents INT, active INTEGER DEFAULT 1)"))
    s.execute(text("INSERT INTO products (id, sku, name, price_cents, active) VALUES "
                   "('p1','OK-1','Fine',1000,1), ('p2','INACT-1','Gone',1000,0), "
                   "('p3','UNSOLD-1','Forklift',1000,1)"))
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification
    add_sold_node(s, node_handle="el-6-6")               # grounded sold set = {Laptops}
    upsert_classification(s, sku="OK-1", node_handle="el-6-6", source="t", status="approved")
    # classified into Forklifts (bi-18): under a GROUNDED sold set, sells_within(bi-18) is
    # False — the explicitly-unauthorized case, no separate setter needed
    upsert_classification(s, sku="UNSOLD-1", node_handle="bi-18", source="t", status="approved")
    s.commit()
    return s


def test_catalog_authorization_catches_phantom_inactive_and_unsold():
    from src.app.services.recommendation_core.quality import catalog_authorization_violations
    db = _authz_db()
    assert catalog_authorization_violations(db, ["OK-1"]) == 0            # clean product
    assert catalog_authorization_violations(db, ["PHANTOM-9"]) == 1       # not in catalog
    assert catalog_authorization_violations(db, ["INACT-1"]) == 1         # inactive shown
    assert catalog_authorization_violations(db, ["UNSOLD-1"]) == 1        # unsold-taxonomy node
    assert catalog_authorization_violations(
        db, ["OK-1", "PHANTOM-9", "INACT-1", "UNSOLD-1"]) == 3


def test_composite_unauthorized_feeds_the_gate():
    from src.app.services.recommendation_core.quality import evaluate_case_quality
    row = evaluate_case_quality({"id": "c1", "budget_max": None},
                                {"products": [{"sku": "A", "price": 10.0}]},
                                catalog_violations=2)
    assert row["payload_violations"] == 0
    assert row["catalog_violations"] == 2
    assert row["unauthorized"] == 2                       # server-side violations reach the gate


def test_authorization_unmeasured_fails_gate_closed():
    """review-9-followup #A1: a broken authorization read (db None / unreadable) must FAIL the
    gate, never read as clean. catalog_authorization reports measured=False → summarize fails."""
    from src.app.services.recommendation_core.quality import (catalog_authorization,
                                                              evaluate_case_quality, summarize_quality)
    res = catalog_authorization(None, ["A"])          # no db → unmeasured
    assert res["measured"] is False
    row = evaluate_case_quality({"id": "c1"}, {"products": [{"sku": "A", "price": 1.0}]},
                                catalog=res)
    assert row["catalog_measured"] is False
    g = summarize_quality([row])
    assert g["gates"]["pass"] is False
    assert any("UNMEASURED" in f for f in g["gates"]["failures"])


def test_classification_coverage_is_a_separate_gate():
    """review-9-followup #A3: unclassified-but-active products aren't unauthorized, but LOW
    classification coverage fails its OWN gate (onboarding gap), distinct from authorization."""
    from src.app.services.recommendation_core.quality import (evaluate_case_quality,
                                                              summarize_quality)
    # 2 shown, 0 classified, 0 authz violations, measured → coverage 0 < 0.98 fails, authz clean
    cat = {"violations": 0, "measured": True, "shown": 2, "classified": 0}
    row = evaluate_case_quality({"id": "c1"},
                                {"products": [{"sku": "A", "price": 1.0}, {"sku": "B", "price": 1.0}]},
                                catalog=cat)
    assert row["unauthorized"] == 0                    # coverage gap is NOT an authz violation
    g = summarize_quality([row])
    assert any("classified_shown_rate" in f for f in g["gates"]["failures"])


# ── dev/test split enforcement (GPT-5.6 review-11b: the split was never enforced) ──────────────

def test_case_labels_honors_split():
    from src.app.services.recommendation_core.quality import case_labels
    labels = {
        "cases": {"c1:0": {"labels": {"SKU-A": 2}}, "c2:0": {"labels": {"SKU-B": 1}}},
        "split": {"dev": ["c1:0"], "test": ["c2:0"]},
    }
    # split=None → any labeled case
    assert case_labels(labels, "c1:0") == {"SKU-A": 2}
    # gating on test → the dev case is NOT visible (no leak into the sealed gate)
    assert case_labels(labels, "c1:0", split="test") is None
    assert case_labels(labels, "c2:0", split="test") == {"SKU-B": 1}
    # gating on dev → only dev
    assert case_labels(labels, "c1:0", split="dev") == {"SKU-A": 2}
    assert case_labels(labels, "c2:0", split="dev") is None


def test_validate_labels_catches_schema_problems():
    from src.app.services.recommendation_core.quality import validate_labels
    assert validate_labels({"cases": {}, "split": {"dev": [], "test": []}}) == []
    probs = validate_labels({
        "cases": {"c1:0": {"labels": {"SKU-A": 5}},      # grade out of range
                  "c2:0": {}},                            # missing labels
        "split": {"test": ["c9:0"]},                      # unknown case ref
    })
    assert any("0..2" in p for p in probs)
    assert any("missing 'labels'" in p for p in probs)
    assert any("unknown case" in p for p in probs)


def test_evaluate_case_quality_split_gates_labeling():
    from src.app.services.recommendation_core.quality import evaluate_case_quality
    labels = {"cases": {"c1:0": {"labels": {"SKU-A": 2}}}, "split": {"dev": ["c1:0"], "test": []}}
    case = {"id": "c1:0", "expects_products": True}
    resp = {"products": [{"sku": "SKU-A", "price": 100, "brand": "X"}]}
    # gating on test → c1 (a dev case) is NOT labeled → row.labeled False
    assert evaluate_case_quality(case, resp, labels=labels, split="test")["labeled"] is False
    # gating on dev → labeled True
    assert evaluate_case_quality(case, resp, labels=labels, split="dev")["labeled"] is True
