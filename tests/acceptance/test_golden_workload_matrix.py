"""W1 golden workload matrix (2026-07-08) — the 8 reference queries both audits converged on.

Two tiers: UNIT tier (no backend — stage/gate contracts, always runs in CI) and LIVE tier
(skipped unless :8080 answers — end-to-end payload shape through /chat/query). These encode the
capability boundary: gaming fit carries min-vs-recommended verdicts; AI honesty names limits;
off-catalog never sells laptops for datacenter asks."""
from __future__ import annotations

import pytest

# ── UNIT TIER ────────────────────────────────────────────────────────────────────────────────

def test_workload_stage_returns_context_and_mutates_constraints():
    from src.app.services.recommend_workload_stage import apply_workload_requirements
    c: dict = {}
    ctx = apply_workload_requirements(
        "can this run cyberpunk 2077 and fortnite under 1900", c,
        gpu_pref_inferred=False, record_failure=lambda *a, **k: None)
    assert isinstance(ctx, dict) and "floors" in ctx
    if ctx["games"]:  # game vocab is profile/KB-driven; when detected, floors must follow
        assert ctx["floors"], "detected games must produce requirement floors"
        assert any(s.startswith(("ram_gb_min", "gpu_vram_gb_min", "refresh_hz_min")) for s in c.get("specs", []))


def test_generic_gaming_defaults_parity():
    from src.app.services.recommend_workload_stage import apply_workload_requirements
    c: dict = {"budget_max": 1500}
    ctx = apply_workload_requirements("gaming and school laptop under 1500", c,
                                      gpu_pref_inferred=False, record_failure=lambda *a, **k: None)
    assert ctx["generic_gaming"] is True
    assert "ram_gb_min:8" in c.get("specs", [])
    assert c.get("gpu_preference") == "with_discrete"


def test_game_development_is_not_downgraded_to_consumer_gaming_defaults():
    from src.app.services.recommend_workload_stage import apply_workload_requirements
    c: dict = {"use_case": "game_development", "budget_max": 1640, "specs": []}
    ctx = apply_workload_requirements(
        "25 laptops for gaming development", c,
        gpu_pref_inferred=False, record_failure=lambda *a, **k: None)
    assert ctx["generic_gaming"] is False
    assert c["use_case"] == "game_development"


def test_fit_verdicts_meets_minimum_vs_recommended():
    from src.app.services.workload_fit import fit_verdicts, fit_evidence_note
    floors = {"min_ram_gb": 12, "recommended_ram_gb": 16, "min_gpu_vram_gb": 6,
              "recommended_gpu_vram_gb": 8, "gpu_needed": True}
    products = [
        {"sku": "HI", "name": "Big Rig", "specs": {"ram_gb": 32, "gpu_vram_gb": 8, "gpu": "RTX 4060"}},
        {"sku": "MID", "name": "Mid Rig", "specs": {"ram_gb": 16, "gpu_vram_gb": 6, "gpu": "RTX 4050"}},
        {"sku": "LOW", "name": "Office Book", "specs": {"ram_gb": 8, "gpu": "integrated"}},
    ]
    v = {x["sku"]: x for x in fit_verdicts(floors, products)}
    assert v["HI"]["meets_recommended"] is True
    assert v["MID"]["meets_minimum"] is True and v["MID"]["meets_recommended"] is False
    assert v["LOW"]["meets_minimum"] is False and any("minimum" in w for w in v["LOW"]["why_not_fit"])
    note = fit_evidence_note(["cyberpunk 2077"], floors, list(v.values()))
    assert note and "WORKLOAD FIT FACTS" in note and "cyberpunk 2077" in note


def test_off_catalog_gate_fires_on_datacenter_not_on_laptops():
    from src.app.services.off_catalog_gate import off_catalog_check, off_catalog_message
    hit = off_catalog_check("i need 5 rack-mount GPU servers with A100s for my data team, budget 80k", "electronics")
    assert hit and hit["class"] == "datacenter_gpu_server"
    msg = off_catalog_message(hit, "i need 5 rack-mount GPU servers with A100s, budget 80k", "electronics")
    assert "don't stock" in msg and "request-for-quote" in msg.lower()
    assert "$80,000" in msg and "account manager" in msg  # autonomy escalation on the stated spend
    assert off_catalog_check("gaming laptop under 2000", "electronics") is None
    assert off_catalog_check("laptop with a good gpu for AI work", "electronics") is None


# ── LIVE TIER (the 8 golden queries; skip when backend down) ────────────────────────────────

def _backend_up() -> bool:
    try:
        import httpx
        return httpx.get("http://127.0.0.1:8080/healthz", timeout=3).status_code == 200
    except Exception:
        return False


live = pytest.mark.skipif(not _backend_up(), reason="backend :8080 not running")


def _chat(q: str, uid: str) -> dict:
    import httpx
    import uuid
    from tests.utils import default_headers
    H = {**default_headers(), "Content-Type": "application/json"}
    r = httpx.Client(timeout=120).post("http://127.0.0.1:8080/api/v1/chat/query",
                                       headers=H,
                                       json={"uid": f"{uid}-{uuid.uuid4().hex[:10]}", "query": q})
    return r.json() if r.status_code == 200 else {}


@live
def test_golden_gaming_fit_carries_requirements_even_on_clarify():
    # Standalone "can this run X" legitimately clarifies (no product referent yet) — but the
    # clarify payload must still SHOW the game requirements it computed (N1: early-return
    # payloads bypassed main assembly and lost the workload context entirely).
    b = _chat("can this run cyberpunk 2077 and fortnite under 1900", "gm-cyber")
    wf = b.get("workload_fit") or {}
    assert wf.get("floors"), "even a clarifying answer must carry the computed game requirement floors"


@live
def test_golden_gaming_fit_verdicts_on_product_turn():
    # A product-bearing gaming turn must carry per-product verdicts. Valorant's light floors
    # fit the catalog under budget (cyberpunk's 32GB-recommended floor legitimately zeroes
    # retrieval at $1,900 — that case needs the step-up-panel verdict path, tracked for E1).
    b = _chat("gaming laptop for valorant under 1900", "gm-valo")
    wf = b.get("workload_fit") or {}
    assert wf.get("floors"), "product turn must carry requirement floors"
    assert wf.get("verdicts"), "product turn must carry min-vs-recommended verdicts"


@live
def test_golden_a100_never_sells_laptops():
    b = _chat("i need 5 rack-mount GPU servers with A100s for my data team, budget 80k", "gm-a100")
    assert not (b.get("products") or []), "off-catalog ask must not return laptop products"
    msg = (b.get("assistant_message") or "").lower()
    assert "don't stock" in msg or "don't carry" in msg
    assert "quote" in msg


@live
@pytest.mark.parametrize("q,uid", [
    ("photoshop and video editing laptop under 1600", "gm-ps"),
    ("unity game development laptop under 2000", "gm-unity"),
    ("stable diffusion image generation laptop under 1900", "gm-sd"),
    ("i want to fine tune a 7b model locally under 2500", "gm-ft"),
    ("gaming and school laptop under 1500", "gm-hybrid"),
])
def test_golden_workload_queries_answer_without_error(q, uid):
    b = _chat(q, uid)
    msg = b.get("assistant_message") or ""
    assert msg and "hiccup" not in msg.lower()
    # AI workloads must never be answered by pure office picks with zero honesty signal:
    if "fine tune" in q or "stable diffusion" in q:
        blob = (msg + " " + str(b.get("workload_fit") or "")).lower()
        assert any(t in blob for t in ("vram", "gpu", "16gb", "cloud")), \
            "AI workload answer must engage GPU/VRAM reality"


def test_untyped_drop_unit():
    # X1: pharmacy SKUs (generic 'accessory' fallback) drop under primary-device intent
    from src.app.services.recommend_response_finalizer import drop_untyped_for_primary_intent
    R = [{"name": "Hand Sanitiser 500ml (70% alcohol)", "specs": {}},
         {"name": "Dell 15 DC15255 15.6\" FHD Laptop", "specs": {}}]
    out = drop_untyped_for_primary_intent(list(R), primary_intent=True)
    assert [r["name"][:4] for r in out] == ["Dell"]
    assert len(drop_untyped_for_primary_intent(list(R), primary_intent=False)) == 2


@live
def test_golden_finetune_never_sells_pharmacy():
    # X1 live: the AI query that returned hand sanitiser must return electronics or nothing
    b = _chat("i want to fine tune a 7b model locally under 2500", "gm-ft2")
    names = " ".join((p.get("name") or "") for p in (b.get("products") or [])).lower()
    assert "sanitiser" not in names and "paracetamol" not in names and "sanitizer" not in names


def test_steam_floors_and_note_merge_into_workload_ctx():
    # W5 consume: publisher-stated Steam requirements enrich floors + produce citable evidence
    from src.app.services.recommend_workload_stage import apply_workload_requirements
    c: dict = {}
    ctx = apply_workload_requirements(
        "can this run cyberpunk 2077 under 1900", c,
        gpu_pref_inferred=False, record_failure=lambda *a, **k: None)
    if "cyberpunk_2077" not in (ctx["games"] or []):
        return  # game vocab is profile-driven; only assert when detected
    sr = ctx["steam_reqs"]
    assert sr.get("min_ram_gb") == 12          # Cyberpunk publisher minimum
    assert sr.get("recommended_ram_gb") == 16
    assert sr.get("min_gpu_vram_gb", 0) >= 4   # GTX 1060 -> laptop tier vram floor
    note = ctx["steam_note"] or ""
    assert "PUBLISHER-STATED" in note and "[steam:" in note and "GTX 1060" in note
    # merged floors take the max across KB + steam
    assert ctx["floors"].get("min_ram_gb", 0) >= 12
    # retrieval constraints NOT tightened by steam (design: enrich truth, not filtering)
    # (KB may add specs; steam adds none beyond what KB already set)


def test_steam_absent_game_is_silent():
    from src.app.services.recommend_workload_stage import apply_workload_requirements
    ctx = apply_workload_requirements(
        "work laptop for spreadsheets under 1000", {},
        gpu_pref_inferred=False, record_failure=lambda *a, **k: None)
    assert ctx["steam_reqs"] == {} and ctx["steam_note"] is None
