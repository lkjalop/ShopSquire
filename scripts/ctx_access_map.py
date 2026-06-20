#!/usr/bin/env python3
"""ctx-access static analyzer — de-risks phase extraction from recommend.py.

For a given line range (a candidate stage) inside a function, reports which shared-state names
are READ, MUTATED (in-place), or REBOUND (reassigned), and — crucially — flags fields that are
WRITTEN inside the range but READ *after* it (a reorder/extraction hazard: the downstream code
depends on this range running first).

Pure static AST analysis, no runtime / imports of the target. Usage:

    python scripts/ctx_access_map.py src/app/routers/recommend.py --func suggest --start 6645 --end 6890

This is the safety tool from CORE_EXTRACTION_AND_PORTABILITY_ROADMAP §3 (#A4): run it on a phase
BEFORE extracting it, to confirm the boundary is clean and nothing downstream silently depends on
an intermediate write.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from typing import Dict, List, Set

# Shared mutable state threaded through suggest() (the 7 ctx dicts + the common locals/aliases).
DEFAULT_TRACKED = {
    "constraints", "timing_breakdown", "image_context", "image_cv_signals_parsed",
    "kv", "kv_out", "structured_state", "structured_state_out", "nlp", "fraud_summary",
    "results", "candidates", "payload", "analysis", "_ctx",
    "_id_result", "_identity_constraints",
}
_MUTATING_METHODS = {"pop", "update", "setdefault", "clear", "append", "extend", "insert", "__setitem__"}


@dataclass
class Access:
    read: Set[str] = field(default_factory=set)
    mutated: Set[str] = field(default_factory=set)   # in-place: subscript-assign or .pop/.update/...
    rebound: Set[str] = field(default_factory=set)   # name = ...


def _name_of(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id  # e.g. _ctx in `_ctx.constraints`
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return node.value.id
    return None


def analyze_range(tree: ast.AST, lo: int, hi: int, tracked: Set[str]) -> Access:
    acc = Access()

    def in_range(n: ast.AST) -> bool:
        return getattr(n, "lineno", -1) >= lo and getattr(n, "lineno", 1 << 30) <= hi

    for node in ast.walk(tree):
        # rebinds: name = ...  /  name[...] = ...
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and in_range(node):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name) and sub.id in tracked:
                        acc.rebound.add(sub.id)
                    elif isinstance(sub, ast.Subscript):
                        nm = _name_of(sub)
                        if nm in tracked:
                            acc.mutated.add(nm)
                    elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id in tracked:
                        acc.mutated.add(sub.value.id)  # _ctx.field = ...
        # mutating method calls: name.pop(...) etc.
        if isinstance(node, ast.Call) and in_range(node) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _MUTATING_METHODS:
                nm = _name_of(node.func.value)
                if nm in tracked:
                    acc.mutated.add(nm)
        # reads: any Name load of a tracked name in range
        if isinstance(node, ast.Name) and in_range(node) and node.id in tracked and isinstance(node.ctx, ast.Load):
            acc.read.add(node.id)
    return acc


def reads_after(tree: ast.AST, after: int, end_of_fn: int, names: Set[str]) -> Dict[str, int]:
    """First line > `after` (and <= end_of_fn) where each name is read. Used to find downstream deps."""
    first: Dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in names:
            ln = getattr(node, "lineno", -1)
            if after < ln <= end_of_fn and (node.id not in first or ln < first[node.id]):
                first[node.id] = ln
    return first


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--func", default="suggest")
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    args = ap.parse_args()

    src = open(args.file, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == args.func), None)
    fn_end = getattr(fn, "end_lineno", len(src.splitlines())) if fn else len(src.splitlines())

    acc = analyze_range(tree, args.start, args.end, DEFAULT_TRACKED)
    print(f"=== {args.func}() range L{args.start}-L{args.end} ===")
    print(f"  READ   : {sorted(acc.read)}")
    print(f"  MUTATED: {sorted(acc.mutated)}")
    print(f"  REBOUND: {sorted(acc.rebound)}")

    written = acc.mutated | acc.rebound
    after = reads_after(tree, args.end, fn_end, written)
    if after:
        print("  ⚠ written-here & read-after (downstream depends on this range running first):")
        for nm, ln in sorted(after.items(), key=lambda kv: kv[1]):
            print(f"      {nm}: first read again at L{ln}")
    else:
        print("  ✓ no downstream reads of fields written here — boundary is clean to extract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
