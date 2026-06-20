"""Tests for scripts/ctx_access_map.py — the phase-extraction de-risking analyzer.

The tool must correctly classify shared-state access (read / in-place mutate / rebind) within a
line range, and flag fields written in-range that are read afterwards (a downstream dependency =
extraction-order hazard). If the tool is wrong, the extraction decisions it informs are unsafe.
"""
from __future__ import annotations

import ast

from scripts.ctx_access_map import DEFAULT_TRACKED, analyze_range, io_contract, reads_after

SRC = (
    "def suggest():\n"                 # 1
    "    constraints = {}\n"           # 2  rebind constraints
    "    constraints['a'] = 1\n"       # 3  mutate constraints (subscript-assign)
    "    v = constraints.get('a')\n"   # 4  read constraints
    "    kv.update({})\n"              # 5  mutate kv (method)
    "    w = nlp\n"                    # 6  read nlp
    "    fraud_summary = {}\n"         # 7  rebind fraud_summary
    "    after = constraints['a']\n"   # 8  read constraints AFTER range 2-7
)


def _tree():
    return ast.parse(SRC)


def test_classifies_read_mutate_rebind():
    acc = analyze_range(_tree(), 2, 7, DEFAULT_TRACKED)
    assert "constraints" in acc.rebound
    assert "constraints" in acc.mutated      # constraints['a'] = 1
    assert "kv" in acc.mutated               # kv.update(...)
    assert "fraud_summary" in acc.rebound
    assert {"constraints", "nlp"} <= acc.read


def test_reads_after_flags_downstream_dependency():
    # constraints is written in 2-7 and read at line 8 -> the range must run before line 8.
    after = reads_after(_tree(), 7, 8, {"constraints"})
    assert after.get("constraints") == 8


def test_clean_boundary_when_no_downstream_read():
    # fraud_summary is written in-range but never read after -> safe to move.
    after = reads_after(_tree(), 7, 8, {"fraud_summary"})
    assert "fraud_summary" not in after


_IO_SRC = (
    "def suggest():\n"               # 1
    "    a = 1\n"                    # 2  set before range
    "    b = a + 1\n"                # 3  RANGE start: reads a (input), sets b
    "    c = b + 1\n"                # 4  sets c (used after) -> output
    "    d = 9\n"                    # 5  RANGE end: sets d (NOT used after) -> not output
    "    e = c + 1\n"                # 6  after: reads c
)


def test_io_contract_inputs_and_outputs():
    import ast as _ast
    tree = _ast.parse(_IO_SRC)
    fn = tree.body[0]
    inputs, outputs = io_contract(tree, fn, 3, 5)
    assert inputs == ["a"]          # read in-range, assigned before
    assert outputs == ["c"]         # assigned in-range, read after; d is dropped (unused after)
