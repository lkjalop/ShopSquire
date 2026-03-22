from __future__ import annotations

from types import SimpleNamespace


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        return _FakeExecuteResult(self._rows)


def _row(*, sku: str, name: str, price_cents: int, specs: dict):
    return SimpleNamespace(
        _mapping={
            "sku": sku,
            "name": name,
            "price_cents": price_cents,
            "image_url": None,
            "specs": specs,
        }
    )


def test_image_lane_fill_for_laptop_excludes_accessories():
    from src.app.routers.recommend import _top_up_image_results

    rows = [
        _row(sku="BAG-001", name="Laptop Sleeve 15 inch", price_cents=2900, specs={"category": "laptop"}),
        _row(sku="COOL-001", name="Adjustable Laptop Stand", price_cents=4500, specs={"category": "laptop"}),
        _row(sku="LAP-002", name="Acer Nitro 16", price_cents=169900, specs={"category": "laptop", "gpu": "RTX 4060"}),
        _row(sku="LAP-003", name="Lenovo LOQ 15", price_cents=179900, specs={"category": "laptop", "gpu": "RTX 4050"}),
    ]
    seed_results = [
        {
            "sku": "LAP-001",
            "name": "MSI Thin A15 15",
            "price_cents": 179900,
            "specs": {"category": "laptop", "gpu": "RTX 3050"},
        }
    ]

    merged, meta = _top_up_image_results(
        db=_FakeDB(rows),
        results=seed_results,
        minimum_count=3,
        image_category="laptop",
        constraints={"budget_max": 2000},
        catalog_profile={"primary_category": "laptop"},
    )

    names = [str((row or {}).get("name") or "") for row in merged]
    assert meta["applied"] is True
    assert meta["added"] == 2
    assert len(merged) == 3
    assert not any("Sleeve" in name or "Stand" in name for name in names)
