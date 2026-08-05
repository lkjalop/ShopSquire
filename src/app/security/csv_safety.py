"""Neutralise spreadsheet formula execution on ingest and export.

Raw evidence remains immutable elsewhere; this module is for sanitized operational
representations and files presented to operators.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Mapping, Sequence

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def neutralize_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    # Leading whitespace is ignored by some spreadsheet engines.
    stripped = value.lstrip("\t\r\n ")
    if stripped.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def neutralize_csv_text(raw: str) -> tuple[str, int]:
    source = io.StringIO(str(raw or ""))
    target = io.StringIO(newline="")
    reader = csv.reader(source)
    writer = csv.writer(target)
    changed = 0
    for row in reader:
        safe = []
        for cell in row:
            value = neutralize_cell(cell)
            changed += int(value != cell)
            safe.append(value)
        writer.writerow(safe)
    return target.getvalue(), changed


def neutralize_mapping(row: Mapping[str, Any], columns: Sequence[str]) -> dict[str, Any]:
    return {column: neutralize_cell(row.get(column)) for column in columns}
