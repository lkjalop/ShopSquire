"""Reconcile historical demo SKUs against the current canonical text parser.

This is deliberately a demo-data repair tool, not a production identity policy.
Production connectors must provide authoritative product and variant identities.
The default is dry-run; ``--apply`` updates the products row and known SKU-bearing
fact tables in one transaction.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seed_inventory_from_txt import parse_inventory


DEFAULT_DB = Path("tmp/demo.sqlite")
DEFAULT_SOURCE = Path("docs/laptop-products-new-short.txt")


def _normalized_name(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _sku_tables(connection: sqlite3.Connection) -> list[str]:
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    result: list[str] = []
    for table in tables:
        columns = {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        if "sku" in columns:
            result.append(table)
    return result


def plan_repairs(
    connection: sqlite3.Connection,
    *,
    source: Path = DEFAULT_SOURCE,
) -> list[dict[str, Any]]:
    expected = [
        (_normalized_name(item["name"]), item)
        for item in parse_inventory(source.read_text(encoding="utf-8"))
    ]
    repairs: list[dict[str, Any]] = []
    rows = connection.execute(
        "SELECT sku, name, specs, image_url FROM products"
    ).fetchall()
    for old_sku, name, specs_json, image_url in rows:
        normalized = _normalized_name(name)
        matches = [
            item
            for expected_name, item in expected
            if expected_name == normalized
            or expected_name.startswith(normalized)
            or normalized.startswith(expected_name)
        ]
        canonical = matches[0] if len(matches) == 1 else None
        if not canonical or str(canonical["sku"]) == str(old_sku):
            continue
        specs = json.loads(specs_json or "{}")
        expected_category = str(canonical["category"])
        observed_category = str(specs.get("category") or "")
        expected_prefix = str(canonical["sku"]).split("-", 1)[0]
        observed_prefix = str(old_sku).split("-", 1)[0]
        # Rows without a declared category are test fixtures or connector-owned
        # identities. Do not infer ownership merely from a partial title match.
        if not observed_category:
            continue
        if expected_category == observed_category and expected_prefix == observed_prefix:
            continue
        repairs.append(
            {
                "old_sku": str(old_sku),
                "new_sku": str(canonical["sku"]),
                "name": str(name),
                "old_category": observed_category or None,
                "new_category": expected_category,
                "image_url": image_url,
            }
        )
    return repairs


def apply_repairs(
    connection: sqlite3.Connection,
    repairs: list[dict[str, Any]],
) -> dict[str, int]:
    tables = _sku_tables(connection)
    counts: dict[str, int] = {}
    with connection:
        for repair in repairs:
            old_sku = repair["old_sku"]
            new_sku = repair["new_sku"]
            conflict = connection.execute(
                "SELECT 1 FROM products WHERE sku = ? AND sku <> ?",
                (new_sku, old_sku),
            ).fetchone()
            if not conflict:
                row = connection.execute(
                    "SELECT specs FROM products WHERE sku = ?", (old_sku,)
                ).fetchone()
                specs = json.loads((row or ["{}"])[0] or "{}")
                specs["category"] = repair["new_category"]
                connection.execute(
                    "UPDATE products SET sku = ?, specs = ? WHERE sku = ?",
                    (new_sku, json.dumps(specs, sort_keys=True), old_sku),
                )
                counts["products"] = counts.get("products", 0) + 1

            for table in tables:
                if table == "products":
                    continue
                try:
                    cursor = connection.execute(
                        f'UPDATE "{table}" SET sku = ? WHERE sku = ?',
                        (new_sku, old_sku),
                    )
                    if cursor.rowcount:
                        counts[table] = counts.get(table, 0) + int(cursor.rowcount)
                except sqlite3.IntegrityError:
                    # A canonical row already owns a unique business key (for
                    # example supplier_id + sku). Keep it and remove only the
                    # duplicate identity's row.
                    cursor = connection.execute(
                        f'DELETE FROM "{table}" WHERE sku = ?', (old_sku,)
                    )
                    if cursor.rowcount:
                        key = f"{table}_merged"
                        counts[key] = counts.get(key, 0) + int(cursor.rowcount)
            if conflict:
                connection.execute("DELETE FROM products WHERE sku = ?", (old_sku,))
                counts["products_merged"] = counts.get("products_merged", 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    connection = sqlite3.connect(args.db)
    try:
        repairs = plan_repairs(connection, source=args.source)
        output: dict[str, Any] = {"mode": "apply" if args.apply else "dry_run", "repairs": repairs}
        if args.apply:
            output["updated_rows"] = apply_repairs(connection, repairs)
        print(json.dumps(output, indent=2, sort_keys=True))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
