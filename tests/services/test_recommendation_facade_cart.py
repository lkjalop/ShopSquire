"""Facade cart-mutation serving (V2 cart milestone step 2) — the resolver detects + plans, the
guarded handlers execute, the facade shapes the payload. Flag-gated (RECOMMEND_CART_SERVE);
default off = the frontend regex serves, zero change."""
import json
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import src.app.services.recommendation_facade as F
from src.app.routers.cart import CartItemPayload, add_item
from src.app.security.auth import ROLE_OWNER
from src.app.services.recommendation_core.envelope import TurnEnvelope


def _make_engine():
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    schema_path = pathlib.Path("db/schema.sql")
    if schema_path.exists():
        with eng.connect() as conn:
            for stmt in [s.strip() for s in schema_path.read_text(encoding="utf-8").split(";") if s.strip()]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
            conn.commit()
    else:
        import src.app.models.db as _dbmod
        _dbmod._ensure_minimal_sqlite_tables(eng)
    return eng


def _seed(eng, rows):
    with eng.connect() as conn:
        for p in rows:
            pid = str(uuid.uuid4())
            conn.execute(text("INSERT OR IGNORE INTO products (id, sku, name, price_cents, active) "
                              "VALUES (:id, :sku, :name, :price, 1)"),
                         {"id": pid, "sku": p["sku"], "name": p["name"], "price": 10000})
            conn.execute(text("INSERT INTO inventory (id, product_id, stock, warehouse) "
                              "VALUES (:id, :pid, :stock, 'default')"),
                         {"id": str(uuid.uuid4()), "pid": pid, "stock": int(p.get("stock", 100))})
        conn.commit()


@pytest.fixture()
def wired():
    eng = _make_engine()
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    try:
        _dbmod.set_engine(eng)
    except Exception:
        pass
    _seed(eng, [
        {"sku": "SKU-ENVY", "name": "HP Envy x360 14"},
        {"sku": "SKU-TPAD", "name": "Lenovo ThinkPad L13"},
        {"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i"},
    ])
    yield eng
    _dbmod.engine = orig
    try:
        _dbmod.set_engine(orig)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _tenant_ctx():
    """R10.2: these tests dispatch as tenant 't1' — set the request ContextVar the way the
    middleware does, so handler-created carts, the facade's cart read, and apply_plan all share
    ONE tenant (pre-R10.2 the mismatch was invisible because tenant was decorative)."""
    from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
    tok = set_active_tenant_id("t1")
    yield
    reset_active_tenant_id(tok)


def _build_cart(uid):
    add_item(CartItemPayload(uid=uid, sku="SKU-ENVY", quantity=1), role=ROLE_OWNER)
    add_item(CartItemPayload(uid=uid, sku="SKU-TPAD", quantity=30), role=ROLE_OWNER)
    add_item(CartItemPayload(uid=uid, sku="SKU-IDEA", quantity=1), role=ROLE_OWNER)


def _env(uid, query, cart, **kwargs):
    return TurnEnvelope.from_suggest_params(
        query=query, uid=uid, tenant_id="t1", cart=cart, **kwargs,
    )


def _fixed_llm(obj):
    return lambda _p, _t: json.dumps(obj)


_IDENTITY_TRACE = lambda payload, tid: payload   # noqa: E731


# ── the compound-edit screenshot: confirm-tier → apply endpoint → executed ──────

def test_serve_compound_edit_confirms_then_applies(wired):
    # C1: a compound plan is CONFIRM tier — nothing mutates until the card's apply call.
    uid = "u-facade-compound"
    _build_cart(uid)
    cart = [{"sku": "SKU-ENVY", "name": "HP Envy x360 14", "quantity": 1},
            {"sku": "SKU-TPAD", "name": "Lenovo ThinkPad L13", "quantity": 30},
            {"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    llm = _fixed_llm({"ops": [
        {"action": "remove_items", "targets": ["HP Envy", "ThinkPad L13"]},
        {"action": "set_quantity", "targets": ["IdeaPad Slim 3i"], "quantity": 20},
    ], "confidence": 0.9})
    payload = F._serve_cart_mutation(_env(uid, "remove the envy and thinkpad, ideapad to 20", cart),
                                     role=ROLE_OWNER, with_trace=_IDENTITY_TRACE, llm_fn=llm)
    assert payload is not None
    assert payload["turn_intent"] == "CART_MUTATE"
    assert payload["cart_updated"] is False                       # NOTHING executed yet
    cm = payload["cart_mutation"]
    assert cm["needs_confirmation"] is True and cm["risk"] == "confirm"
    assert cm["plan_id"] and len(cm["ops"]) == 2
    from src.app.routers.cart import _get_or_create_cart
    _, items, _ = _get_or_create_cart(uid)
    assert len(items) == 3                                        # cart untouched pre-confirm
    # the confirmation card's apply → transactional service → the screenshot fix, executed
    from src.app.services.cart_mutation_service import apply_plan
    out = apply_plan(cm["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "applied"
    _, items, _ = _get_or_create_cart(uid)
    assert {it["sku"]: it["quantity"] for it in items} == {"SKU-IDEA": 20}


def test_compound_explain_relative_quantity_and_deadline_preserve_case_state(wired):
    """A cart mutation must not swallow read-only obligations from the same buyer turn."""
    uid = "u-compound-explain-relative"
    add_item(CartItemPayload(uid=uid, sku="SKU-TPAD", quantity=1), role=ROLE_OWNER)
    cart = [{
        "sku": "SKU-TPAD",
        "name": "Lenovo ThinkPad L13",
        "quantity": 1,
        "available_now": 7,
    }]
    explanation = {
        "sku": "SKU-TPAD",
        "name": "Lenovo ThinkPad L13",
        "workload_summary": "industrial maintenance simulation",
        "coverage_status": "partial",
        "fit_ledger": [
            {"attribute_label": "CPU cores", "required_text": ">= 12", "observed_text": "16", "verdict": "meets"},
            {"attribute_label": "RAM", "required_text": ">= 32 GB", "observed_text": "64 GB", "verdict": "meets"},
            {"attribute_label": "GPU VRAM", "required_text": ">= 12 GB", "observed_text": "24 GB", "verdict": "meets"},
            {"attribute_label": "storage", "required_text": ">= 1000 GB", "observed_text": "1000 GB", "verdict": "meets"},
            {"attribute_label": "virtualization", "required_text": "required", "observed_text": "not recorded", "verdict": "unknown"},
        ],
        "material_unknowns": ["ISV certification", "model scale", "local or cloud execution"],
    }
    payload = F._serve_cart_mutation(
        _env(
            uid,
            "Why is the Lenovo ThinkPad L13 a good choice for this workload? "
            "Can you add 30 more? I need it in 4 days.",
            cart,
            intent_hint="EXPLAIN",
            session={
                "last_product_explanation": {"sku": "SKU-OTHER", "fit_ledger": []},
                "product_explanations": {"SKU-TPAD": explanation},
                "semantic_resolution": {"desired_outcome": "industrial maintenance simulation"},
            },
        ),
        role=ROLE_OWNER,
        with_trace=_IDENTITY_TRACE,
        llm_fn=_fixed_llm({"ops": [], "confidence": 0.0}),
    )

    assert payload is not None
    assert payload["cart_updated"] is False
    op = payload["cart_mutation"]["ops"][0]
    assert op["previous_quantity"] == 1
    assert op["quantity"] == 31
    assert payload["requested_quantity"] == 31
    assert payload["explanation"]["sku"] == "SKU-TPAD"
    assert {row["attribute_label"] for row in payload["explanation"]["fit_ledger"]} >= {
        "CPU cores", "RAM", "GPU VRAM", "storage", "virtualization",
    }
    assert payload["delivery_feasibility"]["requested_quantity"] == 31
    assert payload["delivery_feasibility"]["delivery_window_days"] == 4
    assert payload["delivery_feasibility"]["feasibility"] == "unknown"
    assert payload["delivery_feasibility"]["owner"] == "fulfilment_operator"
    assert {move["id"] for move in payload["delivery_feasibility"]["recovery_moves"]} >= {
        "request_dated_commitment", "split_partial_now", "reduce_quantity", "qualified_substitute",
    }
    assert "budget range" not in payload["message"].lower()
    assert "industrial maintenance simulation" in payload["message"].lower()
    assert "dated fulfilment commitment" in payload["message"].lower()
    assert "31" in payload["message"]
    from src.app.routers.cart import _get_or_create_cart
    _, items, _ = _get_or_create_cart(uid)
    assert items[0]["quantity"] == 1


def test_compound_mutation_cofires_policy_support_and_supplier_status_without_actions(wired):
    uid = "u-compound-read-only"
    add_item(CartItemPayload(uid=uid, sku="SKU-TPAD", quantity=20), role=ROLE_OWNER)
    cart = [{"sku": "SKU-TPAD", "name": "Lenovo ThinkPad L13", "quantity": 20}]
    payload = F._serve_cart_mutation(
        _env(
            uid,
            "Add 5 more. What is the return policy? Can I file a warranty claim for this "
            "laptop, and has the supplier replied to the RFQ?",
            cart,
            session={
                "case_id": "FC-7",
                "rfq_ref": "RFQ-7",
                "last_sourcing_intent": {
                    "rfq_ref": "RFQ-7",
                    "lines": [{"item_ref": "SKU-TPAD", "quantity": 5}],
                },
            },
        ),
        role=ROLE_OWNER,
        with_trace=_IDENTITY_TRACE,
    )

    assert payload["cart_updated"] is False
    assert payload["cart_mutation"]["ops"][0]["quantity"] == 25
    assert payload["policy_answer"]["action_executed"] is False
    assert payload["support_handoff"]["case_id"] is None
    assert payload["support_handoff"]["action_executed"] is False
    assert payload["supplier_status"]["status"] == "awaiting_supplier_response"
    assert payload["supplier_status"]["availability_confirmed"] is False
    kinds = {item["kind"] for item in payload["case_obligations"]}
    assert {"quantity_amendment", "policy_question", "support_question", "supplier_status"} <= kinds
    from src.app.routers.cart import _get_or_create_cart
    _, items, _ = _get_or_create_cart(uid)
    assert items[0]["quantity"] == 20

# ── non-cart intent falls through ────────────────────────────────────────────────

def test_non_cart_intent_returns_none(wired):
    uid = "u-facade-search"
    _build_cart(uid)
    cart = [{"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    payload = F._serve_cart_mutation(_env(uid, "show me cheaper laptops", cart),
                                     role=ROLE_OWNER, with_trace=_IDENTITY_TRACE,
                                     llm_fn=_fixed_llm({"ops": []}))
    assert payload is None   # empty plan → product routing


# ── ambiguity asks, never wipes ──────────────────────────────────────────────────

def test_ambiguous_target_asks_and_does_not_mutate(wired):
    uid = "u-facade-ambig"
    _build_cart(uid)
    cart = [{"sku": "SKU-ENVY", "name": "HP Envy x360 14", "quantity": 1},
            {"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    payload = F._serve_cart_mutation(
        _env(uid, "remove the dell", cart), role=ROLE_OWNER, with_trace=_IDENTITY_TRACE,
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["the Dell"]}]}))
    assert payload is not None
    assert payload["cart_updated"] is False
    assert payload["cart_mutation"]["needs_clarification"] is True
    assert "the Dell" in payload["cart_mutation"]["ambiguous"]
    # cart untouched — all three lines still present (never wiped on a guess)
    from src.app.routers.cart import _get_or_create_cart
    _, items, _ = _get_or_create_cart(uid)
    assert {it["sku"] for it in items} == {"SKU-ENVY", "SKU-TPAD", "SKU-IDEA"}


# ── the flag ladder (off | shadow | on) ─────────────────────────────────────────

def test_cart_mode_off_by_default(monkeypatch):
    monkeypatch.delenv("RECOMMEND_CART_SERVE", raising=False)
    assert F._cart_mode() == "off"


def test_cart_mode_on(monkeypatch):
    monkeypatch.setenv("RECOMMEND_CART_SERVE", "1")
    assert F._cart_mode() == "on"


def test_cart_mode_shadow(monkeypatch):
    monkeypatch.setenv("RECOMMEND_CART_SERVE", "shadow")
    assert F._cart_mode() == "shadow"


# ── C0 gates: confidence floor, mixed-ambiguity suspension, cart_updated truth ──

def test_low_confidence_plan_falls_through(wired):
    uid = "u-lowconf"
    _build_cart(uid)
    cart = [{"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    payload = F._serve_cart_mutation(
        _env(uid, "clear my cart", cart), role=ROLE_OWNER, with_trace=_IDENTITY_TRACE,
        llm_fn=_fixed_llm({"ops": [{"action": "clear_all"}], "confidence": 0.2}))
    assert payload is None    # below the exec floor → legacy/frontend serves (parallel-run net)


def test_mixed_ambiguity_suspends_whole_plan(wired):
    # review-5 #2: 'remove A and the Dell' with the Dell unbound must NOT remove A first.
    uid = "u-mixed"
    _build_cart(uid)
    cart = [{"sku": "SKU-ENVY", "name": "HP Envy x360 14", "quantity": 1},
            {"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    payload = F._serve_cart_mutation(
        _env(uid, "remove the envy and the dell", cart), role=ROLE_OWNER,
        with_trace=_IDENTITY_TRACE,
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["HP Envy", "the Dell"]}],
                           "confidence": 0.9}))
    assert payload is not None
    assert payload["cart_updated"] is False
    assert payload["cart_mutation"]["applied"] == []          # NOTHING executed
    assert "the Dell" in payload["cart_mutation"]["ambiguous"]
    from src.app.routers.cart import _get_or_create_cart
    _, items, _ = _get_or_create_cart(uid)
    assert {it["sku"] for it in items} == {"SKU-ENVY", "SKU-TPAD", "SKU-IDEA"}   # Envy NOT removed


def test_single_op_is_confirmation_only_by_default(wired):
    # review-6 #4/#13: an AUTO-tier single op is NOT auto-applied during the soak — it returns a
    # confirmation card and the cart is untouched until the explicit apply.
    uid = "u-confonly"
    from src.app.routers.cart import CartItemPayload, add_item, _get_or_create_cart
    add_item(CartItemPayload(uid=uid, sku="SKU-IDEA", quantity=1), role=ROLE_OWNER)
    cart = [{"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    payload = F._serve_cart_mutation(
        _env(uid, "set the ideapad to 3", cart), role=ROLE_OWNER, with_trace=_IDENTITY_TRACE,
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"], "quantity": 3}],
                           "confidence": 0.9}))
    assert payload["cart_updated"] is False
    assert payload["cart_mutation"]["needs_confirmation"] is True and payload["cart_mutation"]["plan_id"]
    _, items, _ = _get_or_create_cart(uid)
    assert items[0]["quantity"] == 1                 # untouched until confirm


def test_compound_action_question_returns_confirmation_without_model_wait(wired):
    uid = "u-action-question"
    from src.app.routers.cart import CartItemPayload, add_item, _get_or_create_cart
    add_item(CartItemPayload(uid=uid, sku="SKU-IDEA", quantity=20), role=ROLE_OWNER)
    cart = [{"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 20}]

    payload = F._serve_cart_mutation(
        _env(uid, "Actually reduce the IdeaPad order to 15. Do I need to reconfirm the "
                  "supplier plan?", cart),
        role=ROLE_OWNER,
        with_trace=_IDENTITY_TRACE,
    )

    assert payload["cart_mutation"]["needs_confirmation"] is True
    assert payload["cart_mutation"]["ops"][0]["quantity"] == 15
    assert "reconfirm the updated delivery plan" in payload["message"]
    _, items, _ = _get_or_create_cart(uid)
    assert items[0]["quantity"] == 20


def test_quantity_reduction_preserves_total_budget_without_reallocating_it(wired):
    uid = "u-budget-headroom"
    from src.app.routers.cart import CartItemPayload, add_item

    add_item(CartItemPayload(uid=uid, sku="SKU-IDEA", quantity=30), role=ROLE_OWNER)
    cart = [{
        "sku": "SKU-IDEA",
        "name": "Lenovo IdeaPad Slim 3i",
        "quantity": 30,
        "price_cents": 249_900,
    }]
    session = {"accepted_constraints": {
        "budget_scope": "total",
        "total_budget_cents": 7_500_000,
    }}

    payload = F._serve_cart_mutation(
        _env(
            uid,
            "Actually reduce it by 10 units, but I don't think it is powerful enough.",
            cart,
            session=session,
        ),
        role=ROLE_OWNER,
        with_trace=_IDENTITY_TRACE,
    )

    assert payload["cart_mutation"]["needs_confirmation"] is True
    assert payload["cart_mutation"]["ops"][0]["quantity"] == 20
    assert "$75,000 whole-order budget remains unchanged" in payload["message"]
    assert "$49,980" in payload["message"]
    assert "$25,020 unallocated" in payload["message"]
    assert "does not authorize a more expensive model" in payload["message"]


def test_over_limit_increase_confirms_then_handler_rejects(wired, monkeypatch):
    # review-5 #9: qty 600 > handler line gate (500) → rejected → cart_updated must be False.
    # auto-apply ON to exercise the apply-outcome path (default is confirmation-only, review-6 #4).
    monkeypatch.setenv("RECOMMEND_CART_AUTO_APPLY", "1")
    uid = "u-allrej"
    from src.app.routers.cart import CartItemPayload, add_item
    add_item(CartItemPayload(uid=uid, sku="SKU-IDEA", quantity=1), role=ROLE_OWNER)
    cart = [{"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    payload = F._serve_cart_mutation(
        _env(uid, "set the ideapad to 600", cart), role=ROLE_OWNER, with_trace=_IDENTITY_TRACE,
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"], "quantity": 600}],
                           "confidence": 0.9}))
    assert payload is not None
    assert payload["cart_updated"] is False
    assert payload["cart_mutation"]["needs_confirmation"] is True
    assert "review and reconfirm the updated delivery plan" in payload["message"]
    from src.app.services.cart_mutation_service import apply_plan
    outcome = apply_plan(payload["cart_mutation"]["plan_id"], tenant_id="t1", uid=uid)
    assert outcome["status"] == "rejected"
    assert outcome["error"]["error"] == "quantity_out_of_range"


def test_nl_over_stock_requires_confirmation_then_creates_sourcing_line(wired, monkeypatch):
    # review-5 #8: allow_sourcing is OFF for NL edits — exceeding stock is an honest rejection,
    # never a silent sourcing line (explicit shortfall consent arrives with C1).
    monkeypatch.setenv("RECOMMEND_CART_AUTO_APPLY", "1")   # exercise the apply path (review-6 #4)
    uid = "u-nosrc"
    from src.app.routers.cart import CartItemPayload, add_item, _get_or_create_cart
    # seed a scarce line via fixture products: SKU-ENVY has stock 100; use qty gate instead —
    # build a one-line cart and ask beyond available stock (fixture stock is 100 → ask 300).
    add_item(CartItemPayload(uid=uid, sku="SKU-ENVY", quantity=1), role=ROLE_OWNER)
    cart = [{"sku": "SKU-ENVY", "name": "HP Envy x360 14", "quantity": 1}]
    payload = F._serve_cart_mutation(
        _env(uid, "set the envy to 300", cart), role=ROLE_OWNER, with_trace=_IDENTITY_TRACE,
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["HP Envy"], "quantity": 300}],
                           "confidence": 0.9}))
    assert payload["cart_updated"] is False
    assert payload["cart_mutation"]["needs_confirmation"] is True
    from src.app.services.cart_mutation_service import apply_plan
    outcome = apply_plan(payload["cart_mutation"]["plan_id"], tenant_id="t1", uid=uid)
    assert outcome["status"] == "applied"
    assert outcome["applied"][0]["sourcing"] == {
        "available_now": 100, "shortfall": 200, "requested": 300}
    _, items, _ = _get_or_create_cart(uid)
    assert items[0]["quantity"] == 300 and items[0].get("sourcing_required") is True


# ── resolve-only shadow dispatch (C0) ────────────────────────────────────────────

class _CaptureRedis:
    def __init__(self): self.pushed = []
    def lpush(self, k, v): self.pushed.append((k, v))
    def ltrim(self, k, a, b): pass
    def get(self, k): return None


def test_dispatch_shadow_mode_enqueues_cart_never_executes(wired, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    monkeypatch.delenv("RECOMMEND_CORE_MODE", raising=False)     # search core OFF
    monkeypatch.setenv("RECOMMEND_CART_SERVE", "shadow")         # resolve-only
    uid = "u-shadow-cart"
    _build_cart(uid)
    r = _CaptureRedis()
    db = sessionmaker(bind=wired)()
    try:
        payload = F.dispatch_recommendation_core(
            db, r, query="clear my cart", uid=uid, tenant_id="t1",
            budget_min=None, budget_max=None, trace_id="tid-shadow-1", role=ROLE_OWNER,
            with_trace=lambda p, tid: p, record_failure=lambda *a, **k: None)
    finally:
        db.close()
    assert payload is None                     # NOTHING served — legacy/frontend answers
    assert len(r.pushed) == 1
    import json as _json
    job = _json.loads(r.pushed[0][1])
    assert job["cart_only"] is True
    assert {line_item["sku"] for line_item in job["cart"]} == {"SKU-ENVY", "SKU-TPAD", "SKU-IDEA"}
    assert job["trace_id"] == "tid-shadow-1"
    # and the cart was NOT touched
    from src.app.routers.cart import _get_or_create_cart
    _, items, _ = _get_or_create_cart(uid)
    assert len(items) == 3


# ── full dispatch: cart serves even with the SEARCH core off (independent flag) ──

def test_dispatch_serves_cart_with_core_mode_off(wired, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    import src.app.services.recommendation_core.cart_resolver as CR

    monkeypatch.delenv("RECOMMEND_CORE_MODE", raising=False)   # search core OFF
    monkeypatch.setenv("RECOMMEND_CART_SERVE", "1")            # cart lane ON
    monkeypatch.setattr(CR, "_default_llm_fn",
                        lambda p, t: json.dumps({"ops": [{"action": "clear_all"}], "confidence": 0.9}))

    uid = "u-dispatch-off"
    _build_cart(uid)
    db = sessionmaker(bind=wired)()
    try:
        payload = F.dispatch_recommendation_core(
            db, None, query="please clear my cart", uid=uid, tenant_id="t1",
            budget_min=None, budget_max=None, trace_id="tid-cart-1", role=ROLE_OWNER,
            with_trace=lambda p, tid: p, record_failure=lambda *a, **k: None)
    finally:
        db.close()

    assert payload is not None, "cart should serve with core mode off when RECOMMEND_CART_SERVE=1"
    # clear_all is CONFIRM tier (C1): the turn returns a confirmation card, cart untouched
    assert payload["cart_updated"] is False
    cm = payload["cart_mutation"]
    assert cm["needs_confirmation"] is True and cm["plan_id"]
    from src.app.routers.cart import _get_or_create_cart
    _, items, _ = _get_or_create_cart(uid)
    assert len(items) == 3
    # confirming applies it through the transactional service (undo-stashed)
    from src.app.services.cart_mutation_service import apply_plan
    out = apply_plan(cm["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "applied"
    _, items, _ = _get_or_create_cart(uid)
    assert items == []


def test_dispatch_off_when_both_flags_off(wired, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    monkeypatch.delenv("RECOMMEND_CORE_MODE", raising=False)
    monkeypatch.delenv("RECOMMEND_CART_SERVE", raising=False)
    uid = "u-dispatch-none"
    _build_cart(uid)
    db = sessionmaker(bind=wired)()
    try:
        payload = F.dispatch_recommendation_core(
            db, None, query="clear my cart", uid=uid, tenant_id="t1",
            budget_min=None, budget_max=None, trace_id="tid-cart-2", role=ROLE_OWNER,
            with_trace=lambda p, tid: p, record_failure=lambda *a, **k: None)
    finally:
        db.close()
    assert payload is None   # both off → zero change, legacy/frontend serves
