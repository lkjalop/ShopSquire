"""Architecture ratchets for retiring the legacy recommendation router."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHAT = ROOT / "src" / "app" / "routers" / "chat.py"
SERVICES = ROOT / "src" / "app" / "services"


def _imports(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    found: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.append((node.module or "", tuple(alias.name for alias in node.names)))
        elif isinstance(node, ast.Import):
            found.extend((alias.name, ()) for alias in node.names)
    return found


def test_chat_cannot_import_legacy_recommend_or_suggest() -> None:
    violations = [
        (module, names)
        for module, names in _imports(CHAT)
        if module == "src.app.routers.recommend"
        or module.startswith("src.app.routers.recommend.")
        or "suggest" in names
    ]
    assert violations == []


def test_production_services_do_not_import_legacy_suggest() -> None:
    importers: list[str] = []
    for path in SERVICES.rglob("*.py"):
        for module, names in _imports(path):
            if module == "src.app.routers.recommend" and (
                not names or "suggest" in names
            ):
                importers.append(path.relative_to(ROOT).as_posix())

    assert importers == []
