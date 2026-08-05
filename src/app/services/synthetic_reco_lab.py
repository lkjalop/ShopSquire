from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.deps import hash_uid
from src.app.services.catalog_profile import invalidate_catalog_profile_cache
from src.app.services.checkout_upsell import ensure_recommend_interactions_table
from src.app.services.recommendations import RecommendationService
from scripts.seed_demo_data import parse_laptop_products


@dataclass
class Scenario:
    uid: str
    query: str
    expected_category: str
    budget_max_cents: int | None = None


def _ensure_metrics_tables(db) -> None:
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS customer_orders (
                    id TEXT PRIMARY KEY,
                    uid_hash TEXT NOT NULL,
                    sku TEXT,
                    quantity INTEGER DEFAULT 1,
                    order_total_cents INTEGER DEFAULT 0,
                    event_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    except Exception:
        pass
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sales_metrics (
                    id TEXT PRIMARY KEY,
                    sku TEXT NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    revenue_cents INTEGER DEFAULT 0,
                    cost_cents INTEGER DEFAULT 0,
                    event_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    except Exception:
        pass


def _insert_or_update_product(db, row: Dict[str, Any]) -> None:
    sku = str(row["sku"])
    exists = db.execute(text("SELECT id FROM products WHERE sku = :sku"), {"sku": sku}).fetchone()
    payload = {
        "id": row["id"],
        "sku": sku,
        "name": row["name"],
        "price_cents": int(row["price_cents"]),
        "currency": row.get("currency", "USD"),
        "image_url": row.get("image_url"),
        "specs": json.dumps(row.get("specs") or {}, ensure_ascii=False),
        "active": 1,
    }
    if exists is None:
        db.execute(
            text(
                """
                INSERT INTO products (id, sku, name, price_cents, currency, image_url, specs, active, updated_at)
                VALUES (:id, :sku, :name, :price_cents, :currency, :image_url, :specs, :active, CURRENT_TIMESTAMP)
                """
            ),
            payload,
        )
    else:
        db.execute(
            text(
                """
                UPDATE products
                SET name = :name,
                    price_cents = :price_cents,
                    currency = :currency,
                    image_url = :image_url,
                    specs = :specs,
                    active = :active,
                    updated_at = CURRENT_TIMESTAMP
                WHERE sku = :sku
                """
            ),
            payload,
        )
    pid_row = db.execute(text("SELECT id FROM products WHERE sku = :sku"), {"sku": sku}).fetchone()
    if pid_row is None:
        return
    pid = str(pid_row[0])
    inv = db.execute(
        text("SELECT id FROM inventory WHERE product_id = :pid AND warehouse = 'default'"),
        {"pid": pid},
    ).fetchone()
    if inv is None:
        db.execute(
            text(
                """
                INSERT INTO inventory (id, product_id, stock, warehouse, updated_at)
                VALUES (:id, :product_id, :stock, 'default', CURRENT_TIMESTAMP)
                """
            ),
            {"id": str(uuid.uuid4()), "product_id": pid, "stock": int(row.get("stock", 8))},
        )
    else:
        db.execute(
            text("UPDATE inventory SET stock = :stock, updated_at = CURRENT_TIMESTAMP WHERE product_id = :pid AND warehouse = 'default'"),
            {"stock": int(row.get("stock", 8)), "pid": pid},
        )


def _laptop_products(max_n: int = 80) -> List[Dict[str, Any]]:
    parsed = parse_laptop_products("docs/laptop-products-exp.txt")
    out: List[Dict[str, Any]] = []
    for idx, p in enumerate(parsed[:max_n], start=1):
        specs = dict(p.get("specs") or {})
        specs["category"] = "laptops"
        out.append(
            {
                "id": str(uuid.uuid4()),
                "sku": f"SYN-LAP-{idx:04d}",
                "name": str(p.get("name") or f"Laptop {idx}"),
                "price_cents": int(p.get("price_cents") or 99900),
                "currency": "USD",
                "image_url": f"https://picsum.photos/seed/syn-lap-{idx}/640/480",
                "specs": specs,
                "stock": 5 + (idx % 14),
                "category": "laptops",
            }
        )
    if out:
        return out
    # Fallback if txt is empty.
    for idx in range(1, min(max_n, 20) + 1):
        out.append(
            {
                "id": str(uuid.uuid4()),
                "sku": f"SYN-LAP-{idx:04d}",
                "name": f"Synthetic Laptop {idx}",
                "price_cents": 70000 + (idx * 1200),
                "currency": "USD",
                "image_url": f"https://picsum.photos/seed/syn-lap-{idx}/640/480",
                "specs": {"category": "laptops", "ram_gb": 8 + (idx % 3) * 8, "storage": "512GB SSD"},
                "stock": 8 + (idx % 8),
                "category": "laptops",
            }
        )
    return out


def _fashion_products(max_n: int = 80) -> List[Dict[str, Any]]:
    styles = ["Classic", "Street", "Athleisure", "Minimal", "Boho", "Tailored", "Relaxed", "Vintage"]
    types = ["T-Shirt", "Dress", "Jeans", "Jacket", "Hoodie", "Sneakers", "Skirt", "Blazer", "Sandals", "Shirt"]
    sizes = ["XS", "S", "M", "L", "XL"]
    colors = ["Black", "White", "Navy", "Sage", "Tan", "Denim", "Olive", "Charcoal"]
    out: List[Dict[str, Any]] = []
    idx = 1
    for style in styles:
        for t in types:
            if idx > max_n:
                break
            price = 2500 + (idx % 12) * 700
            specs = {
                "category": "fashion",
                "style": style.lower(),
                "material": "cotton blend" if idx % 2 == 0 else "recycled polyester",
                "size": sizes[idx % len(sizes)],
                "color": colors[idx % len(colors)],
                "season": "summer" if idx % 3 == 0 else "all-season",
            }
            out.append(
                {
                    "id": str(uuid.uuid4()),
                    "sku": f"SYN-FSH-{idx:04d}",
                    "name": f"{style} {t}",
                    "price_cents": price,
                    "currency": "USD",
                    "image_url": f"https://picsum.photos/seed/syn-fashion-{idx}/640/480",
                    "specs": specs,
                    "stock": 10 + (idx % 24),
                    "category": "fashion",
                }
            )
            idx += 1
        if idx > max_n:
            break
    return out


def _homewares_products(max_n: int = 80) -> List[Dict[str, Any]]:
    rooms = ["Kitchen", "Bedroom", "Bathroom", "Living", "Laundry", "Outdoor"]
    types = [
        "Storage Basket",
        "Throw Pillow",
        "Table Lamp",
        "Bed Sheet Set",
        "Non-stick Pan",
        "Cutlery Set",
        "Scented Candle",
        "Bath Towel",
        "Air Fryer",
        "Water Bottle",
    ]
    brands = ["Target Basics", "Kmart Living", "Home Collective", "Urban Nest", "Daily Essentials"]
    out: List[Dict[str, Any]] = []
    idx = 1
    for room in rooms:
        for t in types:
            if idx > max_n:
                break
            price = 1200 + (idx % 14) * 950
            specs = {
                "category": "homewares",
                "room": room.lower(),
                "material": "bamboo" if idx % 4 == 0 else "cotton",
                "brand_family": brands[idx % len(brands)],
                "capacity_l": round(0.8 + (idx % 7) * 0.6, 1),
                "color": ["white", "charcoal", "sand", "olive"][idx % 4],
            }
            out.append(
                {
                    "id": str(uuid.uuid4()),
                    "sku": f"SYN-HMW-{idx:04d}",
                    "name": f"{brands[idx % len(brands)]} {room} {t}",
                    "price_cents": price,
                    "currency": "USD",
                    "image_url": f"https://picsum.photos/seed/syn-home-{idx}/640/480",
                    "specs": specs,
                    "stock": 12 + (idx % 30),
                    "category": "homewares",
                }
            )
            idx += 1
        if idx > max_n:
            break
    return out


def seed_multicategory_catalog(
    *,
    include_categories: List[str] | None = None,
    per_category: int = 80,
    clear_existing_synthetic: bool = True,
) -> Dict[str, Any]:
    cats = [c.strip().lower() for c in (include_categories or ["laptops", "fashion", "homewares"]) if c.strip()]
    generators = {
        "laptops": _laptop_products,
        "fashion": _fashion_products,
        "homewares": _homewares_products,
    }
    seeded = 0
    by_cat: Dict[str, int] = {}
    with db_session() as db:
        ensure_recommend_interactions_table(db)
        _ensure_metrics_tables(db)
        if clear_existing_synthetic:
            for prefix in ("SYN-LAP-", "SYN-FSH-", "SYN-HMW-"):
                like_pref = prefix + "%"
                rows = db.execute(text("SELECT id FROM products WHERE sku LIKE :pref"), {"pref": like_pref}).fetchall()
                pids = [str(r[0]) for r in rows or [] if r and r[0]]
                if pids:
                    for pid in pids:
                        db.execute(text("DELETE FROM inventory WHERE product_id = :pid"), {"pid": pid})
                    db.execute(text("DELETE FROM products WHERE sku LIKE :pref"), {"pref": like_pref})
        for cat in cats:
            gen = generators.get(cat)
            if gen is None:
                continue
            items = gen(max_n=max(5, int(per_category)))
            for item in items:
                _insert_or_update_product(db, item)
                seeded += 1
            by_cat[cat] = len(items)
        try:
            db.commit()
            invalidate_catalog_profile_cache()
        except Exception:
            pass
    return {"status": "ok", "seeded": seeded, "categories": by_cat}


def seed_synthetic_interactions(
    *,
    users: int = 45,
    interactions_per_user: int = 35,
    days_back: int = 90,
    seed: int = 1337,
) -> Dict[str, Any]:
    rng = random.Random(int(seed))
    inserted = 0
    with db_session() as db:
        ensure_recommend_interactions_table(db)
        _ensure_metrics_tables(db)
        prows = db.execute(
            text("SELECT sku, specs, price_cents FROM products WHERE sku LIKE 'SYN-%' AND active IS NOT FALSE")
        ).fetchall()
        if not prows:
            return {"status": "no_products", "inserted": 0}
        products = []
        by_cat: Dict[str, List[Tuple[str, int]]] = {"laptops": [], "fashion": [], "homewares": []}
        for r in prows or []:
            sku = str(r[0] or "").strip()
            if not sku:
                continue
            try:
                specs = json.loads(str(r[1] or "{}")) if isinstance(r[1], str) else (r[1] or {})
            except Exception:
                specs = {}
            category = str((specs or {}).get("category") or "laptops")
            price = int(r[2] or 0)
            products.append((sku, category, price))
            by_cat.setdefault(category, []).append((sku, price))
        actions = ["view", "hover", "click", "add_to_cart"]
        personas = ["student", "young_family", "home_styler", "office_worker", "trend_shopper"]
        now = datetime.now(timezone.utc)
        for u in range(users):
            uid = f"syn-user-{u+1:03d}"
            uid_h = hash_uid(uid)
            persona = personas[u % len(personas)]
            pref_cat = "laptops" if persona in ("student", "office_worker") else ("fashion" if persona == "trend_shopper" else "homewares")
            pool = by_cat.get(pref_cat) or [p[:2] for p in products]
            for _ in range(interactions_per_user):
                sku, price = rng.choice(pool)
                action = rng.choices(actions, weights=[0.45, 0.15, 0.28, 0.12], k=1)[0]
                ts = now - timedelta(days=rng.randint(0, max(1, days_back)), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
                ctx = {
                    "persona": persona,
                    "device_fingerprint": f"dev-{u%17:02d}",
                    "session_id": f"sess-{u:03d}-{rng.randint(1, 15):02d}",
                    "bandit_arm": rng.choice(["balanced", "explore_novelty", "price_value", "personalized_heavy"]),
                    "category_pref": pref_cat,
                }
                db.execute(
                    text(
                        """
                        INSERT INTO recommend_interactions (id, event_time, uid_hash, sku, action, surface, trace_id, context_json)
                        VALUES (:id, :event_time, :uid_hash, :sku, :action, :surface, :trace_id, :context_json)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "event_time": ts.isoformat(),
                        "uid_hash": uid_h,
                        "sku": sku,
                        "action": action,
                        "surface": "synthetic_lab",
                        "trace_id": f"trace-syn-{u:03d}",
                        "context_json": json.dumps(ctx, ensure_ascii=False),
                    },
                )
                if action in ("click", "add_to_cart") and rng.random() < 0.42:
                    qty = 1 if pref_cat != "homewares" else (1 + rng.randint(0, 2))
                    revenue = int(price * qty)
                    cost = int(revenue * (0.52 if pref_cat == "fashion" else (0.60 if pref_cat == "laptops" else 0.57)))
                    db.execute(
                        text(
                            """
                            INSERT INTO customer_orders (id, uid_hash, sku, quantity, order_total_cents, event_time)
                            VALUES (:id, :uid_hash, :sku, :quantity, :order_total_cents, :event_time)
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "uid_hash": uid_h,
                            "sku": sku,
                            "quantity": qty,
                            "order_total_cents": revenue,
                            "event_time": ts.isoformat(),
                        },
                    )
                    db.execute(
                        text(
                            """
                            INSERT INTO sales_metrics (id, sku, quantity, revenue_cents, cost_cents, event_time)
                            VALUES (:id, :sku, :quantity, :revenue_cents, :cost_cents, :event_time)
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "sku": sku,
                            "quantity": qty,
                            "revenue_cents": revenue,
                            "cost_cents": cost,
                            "event_time": ts.isoformat(),
                        },
                    )
                inserted += 1
        try:
            db.commit()
        except Exception:
            pass
    return {"status": "ok", "inserted": inserted, "users": users}


def _scenario_set() -> List[Scenario]:
    return [
        Scenario(uid="syn-user-001", query="Need a laptop for university coding under $900 with 16GB RAM", expected_category="laptops", budget_max_cents=90000),
        Scenario(uid="syn-user-008", query="Show me a black street style hoodie and sneakers bundle", expected_category="fashion", budget_max_cents=18000),
        Scenario(uid="syn-user-013", query="Looking for kitchen storage basket and non-stick pan set", expected_category="homewares", budget_max_cents=25000),
        Scenario(uid="syn-user-020", query="Best value office laptop with long battery and windows", expected_category="laptops", budget_max_cents=130000),
        Scenario(uid="syn-user-026", query="Minimal white bed sheet set and bath towels", expected_category="homewares", budget_max_cents=22000),
        Scenario(uid="syn-user-034", query="Affordable denim jacket and casual shirt for weekend", expected_category="fashion", budget_max_cents=16000),
    ]


def evaluate_recommendation_behavior(*, top_n: int = 5) -> Dict[str, Any]:
    svc = RecommendationService(session=None)
    scenarios = _scenario_set()
    rows: List[Dict[str, Any]] = []
    with db_session() as db:
        for sc in scenarios:
            analysis = svc.analyze_query(query=sc.query, prior={})
            constraints = dict(analysis.get("preferences") or {})
            constraints["uid_hash"] = hash_uid(sc.uid)
            constraints["query"] = sc.query
            if sc.budget_max_cents and not constraints.get("budget_max"):
                constraints["budget_max"] = sc.budget_max_cents
            cands = svc.retrieve_candidates(sc.query, limit=18)
            scored = svc.rerank_candidates_with_factors(cands, constraints)
            top = scored[: max(1, int(top_n))]
            matched = 0
            top_items = []
            for item in top:
                cand = item.get("candidate") or {}
                specs = cand.get("specs") if isinstance(cand.get("specs"), dict) else {}
                cat = str((specs or {}).get("category") or "")
                if cat == sc.expected_category:
                    matched += 1
                top_items.append(
                    {
                        "sku": cand.get("sku"),
                        "name": cand.get("name"),
                        "category": cat,
                        "score": round(float(item.get("score") or 0.0), 4),
                    }
                )
            proposal = {
                "decision_mode": "synthetic_lab",
                "ranked_skus": [x["sku"] for x in top_items if x.get("sku")],
                "rationale": f"Synthetic lab scenario expected {sc.expected_category}",
            }
            retrieved_context = {"candidates": [x.get("candidate") for x in top], "intent": analysis.get("intent"), "scenario": sc.expected_category}
            dec_id = svc.log_decision(
                uid=sc.uid,
                query=sc.query,
                retrieved_context=retrieved_context,
                proposal=proposal,
                policy_version="synthetic_lab_v1",
                flags={"LOG_DETAIL_LEVEL": "standard"},
                agent_name="recommendation_agent",
            )
            drow = db.execute(
                text(
                    """
                    SELECT valid_from, system_from, valid_to, system_to
                    FROM decision_logs
                    WHERE id = :id
                    """
                ),
                {"id": dec_id},
            ).fetchone()
            bitemporal_ok = bool(drow and drow[0] and drow[1] and drow[2] and drow[3])
            precision_at_n = matched / max(1, len(top_items))
            rows.append(
                {
                    "uid": sc.uid,
                    "query": sc.query,
                    "expected_category": sc.expected_category,
                    "precision_at_n": round(precision_at_n, 4),
                    "top_items": top_items,
                    "decision_id": dec_id,
                    "bitemporal_ok": bitemporal_ok,
                }
            )
        try:
            db.commit()
        except Exception:
            pass

    by_cat: Dict[str, List[float]] = {}
    bt_ok = 0
    for r in rows:
        by_cat.setdefault(str(r["expected_category"]), []).append(float(r["precision_at_n"]))
        if r.get("bitemporal_ok"):
            bt_ok += 1
    cat_summary = {k: round(sum(v) / max(1, len(v)), 4) for k, v in by_cat.items()}
    overall = round(sum(float(r["precision_at_n"]) for r in rows) / max(1, len(rows)), 4)
    training_actions = []
    if cat_summary.get("fashion", 1.0) < 0.7:
        training_actions.append("Increase fashion synonym dictionary and enrich size/style slot extraction in NLP/Intent agent.")
    if cat_summary.get("homewares", 1.0) < 0.7:
        training_actions.append("Add room-specific ontology and query reformulations for homewares to Recommendation agent.")
    if overall < 0.75:
        training_actions.append("Run ALS training nightly and raise interaction capture quality for click/add_to_cart events.")
    if bt_ok < len(rows):
        training_actions.append("Fix decision-log persistence path; enforce valid/system timestamp checks in CI.")
    if not training_actions:
        training_actions.append("Promote synthetic lab to scheduled weekly regression and add category-specific canary checks.")
    return {
        "status": "ok",
        "scenarios": rows,
        "category_precision": cat_summary,
        "overall_precision": overall,
        "bitemporal_trace_ok_ratio": round(bt_ok / max(1, len(rows)), 4),
        "recommended_training_actions": training_actions,
    }
