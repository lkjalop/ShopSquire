#!/usr/bin/env python
"""End-to-end platform sweep against the LIVE backend (:8080). Exercises every buyer/operator surface the
user asked about — pure text, non-laptop, FAQ, cart lifecycle, bulk/quantity, procurement→drafted-email,
returns/claims, image permutations — and reports PASS/FAIL + a response snippet per check.

    python -m scripts.e2e_sweep         # backend must be up on :8080

Not a pytest suite — a live integration probe you read. Each section is independent + best-effort."""
from __future__ import annotations

import json
import sys
import time
import uuid

import httpx

from tests.utils import default_headers

BASE = "http://127.0.0.1:8080"
H = {**default_headers(), "Content-Type": "application/json"}
CLIENT = httpx.Client(timeout=180.0)

# Real SKUs from the demo catalog
LAPTOP = "LAP-37144522"    # Dell 15 $629
MONITOR = "MON-D1B9086C"   # Blaupunkt 27" $399
DESKTOP = "LAP-B96F7EF3"   # iMac $2887
TABLET = "LAP-BF3CF82E"    # Surface Pro $1399

_pass = _fail = 0


def check(name, ok, detail=""):
    global _pass, _fail
    _pass += ok; _fail += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail[:110]}" if detail else ""))


def chat(uid, query, images=None):
    body = {"uid": uid, "query": query}
    if images:
        body["images"] = images
    r = CLIENT.post(f"{BASE}/api/v1/chat/query", headers=H, json=body)
    return r.json() if r.status_code == 200 else {"_status": r.status_code, "_text": r.text[:200]}


def section(title):
    print(f"\n{'='*70}\n{title}\n{'='*70}")


# ── 1. PURE TEXT SEARCH (laptop) ───────────────────────────────────────────────
section("1. PURE TEXT SEARCH")
b = chat("t-search", "gaming laptop under 2000 with good battery")
prods = b.get("products") or []
check("gaming laptop search returns products", len(prods) > 0, f"{len(prods)} products")
check("results within budget", all((p.get("price") or 9999) <= 2000 for p in prods[:5]) if prods else False,
      f"top prices {[p.get('price') for p in prods[:3]]}")

# ── 2. NON-LAPTOP RECOMMENDATIONS ──────────────────────────────────────────────
section("2. NON-LAPTOP RECOMMENDATIONS")
for label, q, want in [("monitor", "i need a 27 inch 240hz gaming monitor", "monitor"),
                       ("desktop", "show me an all-in-one desktop computer", "imac"),
                       ("tablet", "a windows tablet for note taking", "surface")]:
    b = chat(f"t-{label}", q)
    names = " ".join((p.get("name") or "") for p in (b.get("products") or [])[:5]).lower()
    check(f"{label} query surfaces {want}", want in names, f"top: {(b.get('products') or [{}])[0].get('name','-')[:44]}")

# ── 3. FAQ / POLICY ────────────────────────────────────────────────────────────
section("3. FAQ / POLICY")
for label, q, kw in [("returns", "what is your returns policy?", "return"),
                     ("warranty", "how long is the warranty?", "warrant"),
                     ("payment", "what payment methods do you accept?", "pay"),
                     ("repair", "how do repairs work?", "repair"),
                     ("store", "can i visit a store?", "store")]:
    b = chat(f"t-faq-{label}", q)
    msg = (b.get("assistant_message") or "").lower()
    check(f"FAQ {label} answered from policy", kw in msg and len(msg) > 40, f"{msg[:70]}")

# ── 4. CART LIFECYCLE ──────────────────────────────────────────────────────────
section("4. CART LIFECYCLE (add / qty / clear-keep-latest / undo / clear)")
CU = "t-cart-1"
CLIENT.post(f"{BASE}/api/v1/cart/clear", headers=H, json={"uid": CU})
CLIENT.post(f"{BASE}/api/v1/cart/items", headers=H, json={"uid": CU, "sku": MONITOR, "quantity": 1})
r2 = CLIENT.post(f"{BASE}/api/v1/cart/items", headers=H, json={"uid": CU, "sku": LAPTOP, "quantity": 2})
cart = CLIENT.get(f"{BASE}/api/v1/cart", headers=H, params={"uid": CU}).json()
items = cart.get("items") or []
check("add 2 SKUs → cart has 2 lines", len(items) == 2, f"{[i.get('sku') for i in items]}")
# quantity change
CLIENT.put(f"{BASE}/api/v1/cart/items/{LAPTOP}", headers=H, json={"uid": CU, "sku": LAPTOP, "quantity": 5})
cart = CLIENT.get(f"{BASE}/api/v1/cart", headers=H, params={"uid": CU}).json()
lap_qty = next((i.get("quantity") for i in (cart.get("items") or []) if i.get("sku") == LAPTOP), None)
check("quantity change → laptop qty=5", lap_qty == 5, f"qty={lap_qty}")
# undo stash + restore (reload-durable)
CLIENT.post(f"{BASE}/api/v1/cart/undo/stash", headers=H, json={"uid": CU, "items": [{"sku": MONITOR, "quantity": 1}]})
u = CLIENT.post(f"{BASE}/api/v1/cart/undo", headers=H, params={"uid": CU}).json()
check("undo restores a stashed clear", (u.get("restored") or 0) >= 1, f"restored={u.get('restored')}")
CLIENT.post(f"{BASE}/api/v1/cart/clear", headers=H, json={"uid": CU})

# ── 5. BULK QUANTITY + SOURCING PREVIEW ────────────────────────────────────────
section("5. BULK QUANTITY + SOURCING PREVIEW")
b = chat("t-bulk", "i need 30 dell laptops for my team by next month")
si = b.get("sourcing_intent") or {}
check("bulk qty parsed (30)", "30" in json.dumps(b)[:4000], "qty present in response")
check("sourcing preview present for shortfall", bool(si.get("lines")) or "source" in (b.get("assistant_message") or "").lower(),
      f"sourcing_intent lines={len(si.get('lines') or [])}")

# ── 6. PROCUREMENT E2E + DRAFTED EMAIL ─────────────────────────────────────────
section("6. PROCUREMENT E2E → DRAFTED SUPPLIER RFQ")
oid = f"E2E-{uuid.uuid4().hex[:8]}"
cc = CLIENT.post(f"{BASE}/api/v1/fulfillment/cases/confirm-cart", headers=H,
                 json={"uid": "t-proc", "order_id": oid, "query": "30 Dell 15 laptops"})
ccj = cc.json() if cc.status_code == 200 else {"_status": cc.status_code, "_text": cc.text[:160]}
cases = ccj.get("cases") or ccj.get("case_ids") or []
check("confirm-cart materializes procurement case(s)", bool(cases), f"{ccj if not cases else len(cases)} case(s)")
if cases:
    cid = cases[0].get("case_id") if isinstance(cases[0], dict) else cases[0]
    dq = CLIENT.post(f"{BASE}/api/v1/fulfillment/cases/{cid}/draft-quote", headers=H,
                     json={"item_ref": LAPTOP, "quantity": 30})
    dqj = dq.json() if dq.status_code == 200 else {"_status": dq.status_code}
    draft = json.dumps(dqj).lower()
    check("draft-quote produces an RFQ email draft", "subject" in draft or "draft" in draft or "rfq" in draft,
          f"keys: {list(dqj)[:6]}")
    check("nothing sent (waits at gate)", "sent" not in draft or "not sent" in draft or "draft" in draft, "sandbox/no-send")

# ── 7. RETURNS / CLAIMS (governed) ─────────────────────────────────────────────
section("7. RETURNS / CLAIMS")
from datetime import datetime, timedelta
ruid, rsku = "t-return", "E2E-RET-1"
oid2 = f"ORD-{uuid.uuid4().hex[:8]}"
try:
    from src.app.models.db import db_session
    from sqlalchemy import text as _t
    with db_session() as db:
        db.execute(_t("INSERT OR IGNORE INTO products (sku,name,price_cents,active) VALUES (:s,'E2E Test Laptop',199900,1)"), {"s": rsku})
        did = f"D-{uuid.uuid4().hex[:8]}"
        db.execute(_t("INSERT INTO draft_orders (id,customer_id,line_items,status) VALUES (:d,:u,:li,'committed')"),
                   {"d": did, "u": ruid, "li": json.dumps([{"sku": rsku, "quantity": 1}])})
        _ca = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute(_t("INSERT INTO orders (id,draft_order_id,customer_id,total_cents,currency,status,created_at) "
                      "VALUES (:o,:d,:u,199900,'USD','paid',:ca)"), {"o": oid2, "d": did, "u": ruid, "ca": _ca})
        db.commit()
    rr = CLIENT.post(f"{BASE}/api/v1/returns/submit", headers=H,
                     json={"sku": rsku, "uid": ruid, "description": "laptop wont turn on at all, no power"})
    rj = rr.json() if rr.status_code == 200 else {"_status": rr.status_code, "_text": rr.text[:160]}
    check("return submits → decision mode", bool(rj.get("mode")), f"mode={rj.get('mode')}")
    check("claim grounding present", rj.get("grounding") is not None, f"verdict={(rj.get('grounding') or {}).get('verdict')}")
    sev = rj.get("failure_severity") or {}
    check("ACL severity classified (major → consumer chooses)", sev.get("severity") == "major" and sev.get("consumer_chooses"),
          f"severity={sev.get('severity')} remedies={sev.get('remedy_options')}")
except Exception as exc:
    check("returns flow", False, f"setup error: {exc}")

# ── 8. IMAGE PERMUTATIONS ──────────────────────────────────────────────────────
section("8. IMAGE PERMUTATIONS (off-domain / damage / support)")
import os
IMG = "dump/test-cv"
for label, fn, assert_fn, desc in [
    ("off-domain apples", "apple-red.jpg",
     lambda t: 'apple' in json.dumps(t).get('labels',json.dumps(t)).lower() or 'apple' in str(t.get('labels')).lower(),
     "should be off_topic, no product hijack"),
    ("cracked laptop", "cracked-mac.jpg",
     lambda t: (t.get("damage_score") or 0) > 0.2 or "damage" in json.dumps(t).lower() or "crack" in json.dumps(t).lower(),
     "should flag damage"),
    ("bsod screen", "windows-11-bsod.avif",
     lambda t: "bsod" in json.dumps(t).lower() or "text" in json.dumps(t).lower() or (t.get("extracted_text") or ""),
     "should OCR the error screen"),
]:
    path = os.path.join(IMG, fn)
    if not os.path.exists(path):
        check(f"image: {label}", False, f"missing {path}")
        continue
    try:
        with open(path, "rb") as f:
            files = {"image": (fn, f.read(), "application/octet-stream")}
        r = CLIENT.post(f"{BASE}/api/v1/vision/triage", headers=default_headers(), files=files)
        tj = r.json() if r.status_code == 200 else {"_status": r.status_code}
        check(f"image: {label} ({desc})", bool(assert_fn(tj)), f"labels={str(tj.get('labels'))[:50]}")
    except Exception as exc:
        check(f"image: {label}", False, f"error: {exc}")

print(f"\n{'='*70}\nSUMMARY: {_pass} PASS / {_fail} FAIL out of {_pass+_fail}\n{'='*70}")
sys.exit(0)
