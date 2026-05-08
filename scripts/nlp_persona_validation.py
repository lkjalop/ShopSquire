"""
NLP + NQE persona validation suite — tests all major use-case flows:
  1. High school student ($600 budget)
  2. University student (CS/engineering/general)
  3. Corporate / office (general / finance / executive)
  4. Content creator
  5. Casual gaming at university
  6. Returns routing (SUPPORT_CLAIM via chat)
  7. Cracked screen routing (SUPPORT_CLAIM via chat)
  8. NQE ask_university_subject → constraints update
  9. NQE ask_high_school_activity → constraints update
 10. NQE ask_corporate_work_type → constraints update
 11. NQE ask_gaming_depth → constraints update

Run: python scripts/nlp_persona_validation.py
"""

import json
import os
import sys
import time
import requests

_RUN_ID = hex(int(time.time()))[-6:]  # hex suffix avoids phone-number PII detection on pure digits


def _uid(base: str) -> str:
    return f"{base}-{_RUN_ID}"

BASE_URL = os.getenv("BASE_URL", "http://localhost:8080")
HEADERS = {"x-api-key": "local-merchant-key", "Content-Type": "application/json"}
SEP = "=" * 60

PASS = "PASS"
FAIL = "FAIL"
INFO = "INFO"


def suggest(query: str, uid: str, **extra) -> dict:
    params = {"uid": uid, "query": query, **extra}
    r = requests.get(f"{BASE_URL}/api/v1/recommend/suggest", headers=HEADERS, params=params, timeout=120)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}


def chat(query: str, uid: str, **payload_extra) -> dict:
    payload = {"query": query, "uid": uid, **payload_extra}
    r = requests.post(f"{BASE_URL}/api/v1/chat/query", headers=HEADERS, json=payload, timeout=120)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}


def check(label: str, ok: bool, detail: str = "") -> None:
    tag = PASS if ok else FAIL
    msg = f"  [{tag}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


# ─────────────────────────────────────────────────────────────────
# 1. High school $600 budget — should get laptops, NOT accessories
# ─────────────────────────────────────────────────────────────────
def test_high_school_budget():
    print(f"\n{SEP}\n[1] High school $600 budget\n{SEP}")
    r = suggest("laptop for high school student budget around 600", _uid("val-hs-600"))
    products = r.get("products") or r.get("results") or []
    persona = r.get("buyer_persona", "")
    use_case = (r.get("constraints_used") or {}).get("use_case", "")
    nq = r.get("next_questions") or []
    print(f"  persona={persona}  use_case={use_case}  products={len(products)}")
    print(f"  top_product: {(products[0].get('name') or products[0].get('sku')) if products else '(none)'}")
    if products:
        print(f"  top_price: ${products[0].get('price')}")

    check("Detected student/high_school persona", "school" in (persona or "").lower() or "student" in (persona or "").lower() or "school" in use_case)
    check("Returns actual laptop (not accessory)", len(products) > 0 and all(
        any(str(p.get("sku", "")).upper().startswith(pfx) for pfx in ("LAP-", "GAM-", "NB-"))
        or (p.get("price") or 0) > 200
        for p in products[:3]
    ))
    check("Asks use-case or activity clarification", any(
        str(q.get("id", "")).startswith("ask_") for q in nq
    ), f"questions={[q.get('id') for q in nq[:3]]}")


# ─────────────────────────────────────────────────────────────────
# 2. University student general
# ─────────────────────────────────────────────────────────────────
def test_university_general():
    print(f"\n{SEP}\n[2] University general student\n{SEP}")
    r = suggest("laptop for university student", _uid("val-uni-gen"))
    products = r.get("products") or r.get("results") or []
    persona = r.get("buyer_persona", "")
    nq = r.get("next_questions") or []
    uc = (r.get("constraints_used") or {}).get("use_case", "")
    print(f"  persona={persona}  use_case={uc}  products={len(products)}")
    check("Student persona detected", "student" in (persona or "").lower() or "student" in uc)
    check("Asks university subject question", any("university" in str(q.get("id", "")) or "subject" in str(q.get("text", "")).lower() for q in nq))


# ─────────────────────────────────────────────────────────────────
# 3. University CS student — NQE selection should update use_case
# ─────────────────────────────────────────────────────────────────
def test_university_cs_nqe_selection():
    print(f"\n{SEP}\n[3] University CS student — NQE selection\n{SEP}")
    uid = _uid("val-uni-cs-nqe")
    # First turn: get NQE question
    r1 = suggest("laptop for university student under 1500", uid)
    nq1 = r1.get("next_questions") or []
    has_univ_q = any("university" in str(q.get("id", "")) for q in nq1)
    print(f"  Turn 1 — asked university question: {has_univ_q}")
    check("Turn 1 emits ask_university_subject", has_univ_q)

    # Second turn: simulate NQE selection for CS
    time.sleep(1)
    r2 = suggest(
        "laptop for university student under 1500", uid,
        nqe_question_id="ask_university_subject",
        nqe_option_id="computer_science_student",
        nqe_option_value="computer_science_student",
        nqe_option_label="Computer Science / IT",
    )
    uc2 = (r2.get("constraints_used") or {}).get("use_case", "")
    print(f"  Turn 2 — use_case after selection: {uc2}")
    check("NQE selection sets use_case=computer_science_student", "computer_science" in uc2)


# ─────────────────────────────────────────────────────────────────
# 4. Corporate work type — NQE selection flow
# ─────────────────────────────────────────────────────────────────
def test_corporate_nqe():
    print(f"\n{SEP}\n[4] Corporate laptop — NQE work type selection\n{SEP}")
    uid = _uid("val-corp-nqe")
    r1 = suggest("work laptop for corporate office", uid)
    nq1 = r1.get("next_questions") or []
    persona = r1.get("buyer_persona", "")
    print(f"  Turn 1 — persona={persona}  questions={[q.get('id') for q in nq1[:3]]}")
    check("Corporate persona detected", "corporate" in (persona or "").lower() or "office" in (r1.get("constraints_used") or {}).get("use_case", ""))
    has_corp_q = any("corporate" in str(q.get("id", "")) for q in nq1)
    check("Emits ask_corporate_work_type", has_corp_q)

    if has_corp_q:
        time.sleep(1)
        r2 = suggest(
            "work laptop for corporate office", uid,
            nqe_question_id="ask_corporate_work_type",
            nqe_option_id="office_finance",
            nqe_option_value="office_finance",
            nqe_option_label="Finance / Data Analysis (Excel, Power BI, SAP)",
        )
        uc2 = (r2.get("constraints_used") or {}).get("use_case", "")
        print(f"  Turn 2 — use_case after selection: {uc2}")
        check("NQE selection sets use_case=office_finance", "finance" in uc2)


# ─────────────────────────────────────────────────────────────────
# 5. Content creator
# ─────────────────────────────────────────────────────────────────
def test_content_creator():
    print(f"\n{SEP}\n[5] Content creator / video editing\n{SEP}")
    r = suggest("laptop for video editing YouTube content creation", _uid("val-cc-001"))
    products = r.get("products") or r.get("results") or []
    persona = r.get("buyer_persona", "")
    uc = (r.get("constraints_used") or {}).get("use_case", "")
    msg = r.get("assistant_message", "")
    print(f"  persona={persona}  use_case={uc}  products={len(products)}")
    check("Creative persona detected", "creative" in (persona or "").lower() or "content" in uc)
    check("Recommends products", len(products) > 0)
    check("Message mentions performance/GPU/rendering", any(tok in msg.lower() for tok in ("gpu", "render", "performance", "rtx", "vram", "creator")))


# ─────────────────────────────────────────────────────────────────
# 6. High school activity NQE — light gaming selection
# ─────────────────────────────────────────────────────────────────
def test_high_school_activity_gaming_nqe():
    print(f"\n{SEP}\n[6] High school - activity NQE to casual gaming\n{SEP}")
    uid = _uid("val-hs-nqe-gaming")
    r1 = suggest("laptop for high school student", uid)
    nq1 = r1.get("next_questions") or []
    print(f"  Turn 1 questions: {[q.get('id') for q in nq1[:4]]}")
    has_hs_q = any("high_school" in str(q.get("id", "")) or "activity" in str(q.get("id", "")) for q in nq1)
    check("Emits ask_high_school_activity", has_hs_q)

    if has_hs_q:
        time.sleep(1)
        r2 = suggest(
            "laptop for high school student", uid,
            nqe_question_id="ask_high_school_activity",
            nqe_option_id="gaming_light",
            nqe_option_value="gaming_light",
            nqe_option_label="Casual gaming (Minecraft, Roblox, Fortnite)",
        )
        uc2 = (r2.get("constraints_used") or {}).get("use_case", "")
        print(f"  Turn 2 — use_case after gaming_light: {uc2}")
        check("NQE sets use_case=gaming", "gaming" in uc2)


# ─────────────────────────────────────────────────────────────────
# 7. Gaming depth NQE — competitive esports
# ─────────────────────────────────────────────────────────────────
def test_gaming_depth_nqe():
    print(f"\n{SEP}\n[7] Gaming — ask_gaming_depth NQE selection\n{SEP}")
    uid = _uid("val-gaming-depth")
    r1 = suggest("gaming laptop under 2000", uid)
    nq1 = r1.get("next_questions") or []
    print(f"  Turn 1 questions: {[q.get('id') for q in nq1[:3]]}")
    check("NQE emits GPU or gaming question", any(
        "gpu" in str(q.get("id", "")) or "gaming" in str(q.get("id", ""))
        for q in nq1
    ))

    time.sleep(1)
    r2 = suggest(
        "gaming laptop under 2000", uid,
        nqe_question_id="ask_gaming_depth",
        nqe_option_id="gaming_competitive",
        nqe_option_value="gaming_competitive",
        nqe_option_label="Competitive Esports (CS2, Valorant at 144fps+)",
    )
    uc2 = (r2.get("constraints_used") or {}).get("use_case", "")
    gpu2 = (r2.get("constraints_used") or {}).get("gpu_preference", "")
    print(f"  Turn 2 — use_case={uc2}  gpu_preference={gpu2}")
    check("Sets use_case=gaming", "gaming" in uc2)
    check("Sets gpu_preference=with_discrete", "with_discrete" in gpu2)


# ─────────────────────────────────────────────────────────────────
# 8. Returns via chat — SUPPORT_CLAIM routing
# ─────────────────────────────────────────────────────────────────
def test_returns_via_chat():
    print(f"\n{SEP}\n[8] Returns via chat — SUPPORT_CLAIM routing\n{SEP}")
    r = chat("I want to return my laptop I bought last week screen flickering", _uid("val-returns-chat"))
    status = r.get("status", "")
    view_mode = r.get("view_mode", "")
    msg = str(r.get("assistant_message") or "")
    products = r.get("products") or []
    print(f"  status={status}  view_mode={view_mode}  products={len(products)}")
    print(f"  message[:150]: {msg[:150]}")
    check("Support routing (status=support_claim or view_mode=support)", "support" in status or "support" in view_mode or any(tok in msg.lower() for tok in ("return", "warranty", "repair", "support", "exchange", "fastest")))
    check("No product recommendations shown (support not shopping)", len(products) == 0)


# ─────────────────────────────────────────────────────────────────
# 9. Cracked screen via chat
# ─────────────────────────────────────────────────────────────────
def test_cracked_screen_via_chat():
    print(f"\n{SEP}\n[9] Cracked screen via chat\n{SEP}")
    r = chat("my laptop screen cracked has black lines is this covered under warranty", _uid("val-cracked-chat"))
    status = r.get("status", "")
    view_mode = r.get("view_mode", "")
    msg = str(r.get("assistant_message") or "")
    rp = r.get("right_panel") or {}
    print(f"  status={status}  view_mode={view_mode}")
    print(f"  message[:150]: {msg[:150]}")
    check("Support routing (status or view_mode)", "support" in status or "support" in view_mode or any(tok in msg.lower() for tok in ("warranty", "repair", "damage", "cracked", "fastest path", "support")))
    check("Right panel is support mode", rp.get("mode") == "support" or "support" in str(rp.get("support_cards", [])).lower())


# ─────────────────────────────────────────────────────────────────
# 10. University student with casual gaming — mixed signal
# ─────────────────────────────────────────────────────────────────
def test_university_with_casual_gaming():
    print(f"\n{SEP}\n[10] University student who also does casual gaming\n{SEP}")
    r = suggest("laptop for university student who also plays some games casually like Minecraft and Fortnite budget 1200", _uid("val-uni-gamer"))
    products = r.get("products") or r.get("results") or []
    uc = (r.get("constraints_used") or {}).get("use_case", "")
    msg = r.get("assistant_message", "")
    print(f"  use_case={uc}  products={len(products)}")
    print(f"  message[:150]: {msg[:150]}")
    check("Use case detected (gaming or student)", "gaming" in uc or "student" in uc or "university" in uc)
    check("Products returned", len(products) > 0)


# ─────────────────────────────────────────────────────────────────
# 11. Engineering student — specs check
# ─────────────────────────────────────────────────────────────────
def test_engineering_student():
    print(f"\n{SEP}\n[11] Engineering student (AutoCAD/SolidWorks)\n{SEP}")
    r = suggest("laptop for engineering student who uses AutoCAD and SolidWorks", _uid("val-eng-stud"))
    uc = (r.get("constraints_used") or {}).get("use_case", "")
    products = r.get("products") or r.get("results") or []
    msg = r.get("assistant_message", "")
    print(f"  use_case={uc}  products={len(products)}")
    check("Engineering use case detected", "engineering" in uc or "engineer" in uc)
    check("GPU recommendation in message", any(tok in msg.lower() for tok in ("gpu", "rtx", "dedicated", "discrete", "workstation", "cad")))


def main():
    print(f"\n{'#'*60}")
    print("ShopSquire NLP+NQE Persona Validation Suite")
    print(f"{'#'*60}")
    print(f"Target: {BASE_URL}")
    print()

    # Verify backend is up
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code not in (200, 204):
            print(f"ERROR: Backend returned {r.status_code}")
            sys.exit(1)
        print("Backend: UP")
    except Exception as e:
        print(f"ERROR: Backend not reachable — {e}")
        sys.exit(1)

    # Unique run suffix prevents DummyRedis NQE history from affecting re-runs
    import time as _t
    global _RUN_ID
    _RUN_ID = hex(int(_t.time()))[-6:]  # hex avoids PII false-positive on pure digit UIDs

    test_high_school_budget()
    test_university_general()
    test_university_cs_nqe_selection()
    test_corporate_nqe()
    test_content_creator()
    test_high_school_activity_gaming_nqe()
    test_gaming_depth_nqe()
    test_returns_via_chat()
    test_cracked_screen_via_chat()
    test_university_with_casual_gaming()
    test_engineering_student()

    print(f"\n{'#'*60}")
    print("Done.")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
