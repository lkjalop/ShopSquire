"""Quick smoke test for all recent changes."""
import json, sys
errors = []

# 1. Ranking agent
try:
    from src.app.services.product_ranking_agent import (
        _CATEGORY_RANKING_DIMENSIONS, _detect_product_category, _spec_match_score,
    )
    cat = _detect_product_category({"category": "clothing"})
    assert cat == "clothing", f"Expected clothing, got {cat}"
    score = _spec_match_score(
        {"category": "clothing", "material": "cotton", "color": "blue"},
        {"material": "cotton", "color": "blue"},
    )
    assert 0.0 <= score <= 1.0, f"Score out of range: {score}"
    score2 = _spec_match_score(
        {"category": "laptop", "ram_gb": 16, "storage_gb": 512},
        {"min_ram": 16, "min_storage": 256},
    )
    assert 0.0 <= score2 <= 1.0, f"Score2 out of range: {score2}"
    cats = list(_CATEGORY_RANKING_DIMENSIONS.keys())
    assert "laptop" in cats and "clothing" in cats and "kitchen" in cats
    print(f"[OK] Ranking: clothing={round(score,3)} laptop={round(score2,3)} categories={cats}")
except Exception as e:
    errors.append(f"Ranking: {e}")
    print(f"[FAIL] Ranking: {e}")

# 2. CV model packs
try:
    from src.app.services.cv_model_pack import get_model_pack_for_category
    for cat in ["clothing", "kitchen", "furniture", "tv", "phone"]:
        p = get_model_pack_for_category(cat)
        assert p, f"No pack for {cat}"
        assert "quality" in p, f"Missing quality key in {cat} pack"
    print("[OK] CV model packs: all categories resolve")
except Exception as e:
    errors.append(f"CV packs: {e}")
    print(f"[FAIL] CV packs: {e}")

# 3. Status summary router
try:
    from src.app.routers.status_summary import router
    routes = [r.path for r in router.routes]
    assert "/status/summary" in routes, f"Route not found: {routes}"
    print(f"[OK] Status summary router: {routes}")
except Exception as e:
    errors.append(f"Status summary: {e}")
    print(f"[FAIL] Status summary: {e}")

# 4. Chat stream router
try:
    from src.app.routers.chat_stream import router as cs
    routes = [r.path for r in cs.routes]
    assert any("/stream" in r for r in routes), f"Route not found: {routes}"
    print(f"[OK] Chat stream router: {routes}")
except Exception as e:
    errors.append(f"Chat stream: {e}")
    print(f"[FAIL] Chat stream: {e}")

# 5. Orchestrator risk boost
try:
    from src.app.services.orchestrator import Orchestrator
    print("[OK] Orchestrator imports")
except Exception as e:
    errors.append(f"Orchestrator: {e}")
    print(f"[FAIL] Orchestrator: {e}")

# 6. NQE engine
try:
    from src.app.flows.nqe import NextQuestionEngine
    print("[OK] NQE engine imports")
except Exception as e:
    errors.append(f"NQE: {e}")
    print(f"[FAIL] NQE: {e}")

# 7. admin_grc risk bands
try:
    from src.app.routers.admin_grc import get_latest_risk_bands
    bands = get_latest_risk_bands()
    assert isinstance(bands, dict), f"Expected dict, got {type(bands)}"
    print(f"[OK] Risk bands: {bands}")
except Exception as e:
    errors.append(f"Risk bands: {e}")
    print(f"[FAIL] Risk bands: {e}")

# Summary
print(f"\n{'='*40}")
if errors:
    print(f"FAILURES ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
