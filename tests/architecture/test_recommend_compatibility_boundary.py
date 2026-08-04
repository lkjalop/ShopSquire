from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_main_registers_v2_compatibility_router_not_legacy_router() -> None:
    main = (ROOT / "src/app/main.py").read_text(encoding="utf-8-sig")
    assert "from src.app.routers.recommend_compat import router as recommend_router" in main
    assert "from src.app.routers.recommend import router as recommend_router" not in main


def test_compatibility_router_does_not_import_legacy_module() -> None:
    path = ROOT / "src/app/routers/recommend_compat.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "src.app.routers.recommend" not in imported


def test_storefront_widget_uses_v2_chat_not_deprecated_suggest() -> None:
    widget = (ROOT / "src/frontend/widget/shopsquire-widget.js").read_text(
        encoding="utf-8-sig"
    )
    assert "/api/v1/chat/query" in widget
    assert "/api/v1/recommend/suggest" not in widget
