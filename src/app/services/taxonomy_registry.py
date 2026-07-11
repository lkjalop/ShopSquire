"""T1 taxonomy registry (V2 Phase 2) — the deterministic ground truth the model is clamped to.

Vendored, PINNED release of the Shopify Standard Product Taxonomy (MIT):
    data/taxonomy/shopify-2026-05/categories.txt   (14,606 categories, release 2026-05)
Upgrades are deliberate: vendor the new dist under a new directory, flip PINNED_RELEASE, and
re-run the drift tests — never fetch at runtime.

WHY THIS EXISTS (the ungrounded-router lesson, 2026-07-10): a model can map "rack-mount A100
servers" or "forklift" to a category with world knowledge, but it CANNOT know what THIS store
sells — that must be a deterministic lookup. This module supplies both halves of the clamp:
  • the closed vocabulary  — get_node/search_nodes over the pinned release (the model may only
    ever pick node handles that exist here), and
  • the tenant ground truth — sold_taxonomy + is_sold(), which turns OFF_CATALOG from a model
    opinion (or a hand-maintained negative list, blind to forklifts) into a set-membership fact.

Hierarchy is encoded in the handle itself (el-6-6 ⊂ el-6 ⊂ el), so ancestry is pure string
math — verified against the vendored file by the drift test, no graph table needed.

SELLING SEMANTICS: approving a node sells its whole subtree (a merchant who sells "Laptops"
sells gaming laptops) — ancestors are NOT implied (selling laptops ≠ selling all Electronics).

is_sold() is TRI-STATE and fail-safe by design:
  True  — the node or one of its ancestors is in the tenant's sold set.
  False — valid node, sold set present and readable, and the node is NOT covered.
          (Only this value may justify an off-catalog refusal.)
  None  — cannot determine: unknown handle, no sold set bootstrapped for the tenant, or a
          read failure. A None must NEVER become a refusal — that is the exact failure mode
          the ungrounded router had (deciding membership with nothing to check against).

Tables (in-service DDL like catalog_entities; alembic migration lands with the T2/T3 wiring):
  product_classification — variant sku → node handle (source/confidence/status/approved_by).
                           Node handles are validated against the pinned release on write.
  sold_taxonomy          — the materialized set of approved node handles per tenant.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.taxonomy_registry")

PINNED_RELEASE = "2026-05"
_DIST_PATH = Path(__file__).resolve().parents[3] / "data" / "taxonomy" / f"shopify-{PINNED_RELEASE}" / "categories.txt"

DEFAULT_TENANT = "default"


@dataclass(frozen=True)
class TaxonomyNode:
    handle: str          # "el-6-6" — hierarchy-encoding short id (the clamp vocabulary)
    gid: str             # "gid://shopify/TaxonomyCategory/el-6-6"
    name: str            # "Laptops"
    full_path: str       # "Electronics > Computers > Laptops"
    depth: int           # 0 = vertical root


# ── pinned-release load (read-only, cached once per process) ─────────────────

@lru_cache(maxsize=1)
def _nodes() -> Dict[str, TaxonomyNode]:
    out: Dict[str, TaxonomyNode] = {}
    try:
        for line in _DIST_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or " : " not in line:
                continue
            gid, path = line.split(" : ", 1)
            gid, path = gid.strip(), path.strip()
            handle = gid.rsplit("/", 1)[-1]
            segments = [s.strip() for s in path.split(">")]
            out[handle] = TaxonomyNode(handle=handle, gid=gid, name=segments[-1],
                                       full_path=path, depth=len(segments) - 1)
    except Exception as exc:
        logger.error("taxonomy dist unreadable (%s): %s", _DIST_PATH, exc)
    return out


@lru_cache(maxsize=1)
def _children_index() -> Dict[str, tuple]:
    idx: Dict[str, List[str]] = {}
    for h in _nodes():
        p = parent_handle(h)
        if p is not None:
            idx.setdefault(p, []).append(h)
    return {k: tuple(sorted(v)) for k, v in idx.items()}


def release() -> str:
    return PINNED_RELEASE


def node_count() -> int:
    return len(_nodes())


def parent_handle(handle: str) -> Optional[str]:
    h = str(handle or "")
    return h.rsplit("-", 1)[0] if "-" in h else None


def get_node(handle_or_gid: str) -> Optional[TaxonomyNode]:
    h = str(handle_or_gid or "").strip().rsplit("/", 1)[-1]
    return _nodes().get(h)


def ancestors(handle: str) -> List[TaxonomyNode]:
    """Nearest-first chain of ancestors (el-6-6 → [el-6, el])."""
    out: List[TaxonomyNode] = []
    h = parent_handle(str(handle or ""))
    while h is not None:
        node = _nodes().get(h)
        if node is None:
            break
        out.append(node)
        h = parent_handle(h)
    return out


def children(handle: str) -> List[TaxonomyNode]:
    return [_nodes()[h] for h in _children_index().get(str(handle or ""), ()) if h in _nodes()]


def search_nodes(query: str, *, limit: int = 20) -> List[TaxonomyNode]:
    """Deterministic substring search over the pinned release (exact name > name-contains >
    path-contains; ties by depth then handle). This is the T3 candidate generator's fallback;
    the vector top-K comes later — either way the model only ever PICKS from real handles."""
    q = str(query or "").strip().lower()
    if not q:
        return []
    exact, name_hit, path_hit = [], [], []
    for n in _nodes().values():
        name = n.name.lower()
        if name == q:
            exact.append(n)
        elif q in name:
            name_hit.append(n)
        elif q in n.full_path.lower():
            path_hit.append(n)
    key = lambda n: (n.depth, n.handle)  # noqa: E731
    ranked = sorted(exact, key=key) + sorted(name_hit, key=key) + sorted(path_hit, key=key)
    return ranked[: max(1, int(limit))]


# ── tenant grounding: product_classification + sold_taxonomy ─────────────────

_CLASSIFICATION_DDL = """
CREATE TABLE IF NOT EXISTS product_classification (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    sku TEXT NOT NULL,
    node_handle TEXT NOT NULL,
    taxonomy_release TEXT,
    source TEXT,
    confidence REAL,
    status TEXT DEFAULT 'proposed',
    approved_by TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_SOLD_DDL = """
CREATE TABLE IF NOT EXISTS sold_taxonomy (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    node_handle TEXT NOT NULL,
    taxonomy_release TEXT,
    source TEXT,
    approved_by TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_pclass_key ON product_classification(tenant_id, sku)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_sold_key ON sold_taxonomy(tenant_id, node_handle)",
)


def ensure_tables(db) -> None:
    db.execute(text(_CLASSIFICATION_DDL))
    db.execute(text(_SOLD_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


def upsert_classification(db, *, sku: str, node_handle: str, source: str = "",
                          confidence: Optional[float] = None, status: str = "proposed",
                          approved_by: Optional[str] = None, tenant_id: str = DEFAULT_TENANT,
                          commit: bool = False) -> bool:
    """Variant → taxonomy node. THE CLAMP LIVES HERE: a handle not in the pinned release is
    rejected — a model (or human) can only ever classify onto real nodes."""
    if db is None or not sku or get_node(node_handle) is None:
        return False
    try:
        ensure_tables(db)
        p = {"t": str(tenant_id).strip() or DEFAULT_TENANT, "s": str(sku),
             "n": get_node(node_handle).handle, "r": PINNED_RELEASE, "src": source,
             "c": confidence, "st": status, "ab": approved_by}
        res = db.execute(text(
            "UPDATE product_classification SET node_handle=:n, taxonomy_release=:r, source=:src, "
            "confidence=:c, status=:st, approved_by=:ab, updated_at=CURRENT_TIMESTAMP "
            "WHERE tenant_id=:t AND sku=:s"), p)
        if not (getattr(res, "rowcount", 0) or 0):
            db.execute(text(
                "INSERT INTO product_classification (id, tenant_id, sku, node_handle, "
                "taxonomy_release, source, confidence, status, approved_by) "
                "VALUES (:id,:t,:s,:n,:r,:src,:c,:st,:ab)"), {**p, "id": str(uuid.uuid4())})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


def approve_classification(db, *, sku: str, approved_by: str, tenant_id: str = DEFAULT_TENANT,
                           commit: bool = False) -> bool:
    if db is None or not sku or not approved_by:
        return False
    try:
        ensure_tables(db)
        res = db.execute(text(
            "UPDATE product_classification SET status='approved', approved_by=:ab, "
            "updated_at=CURRENT_TIMESTAMP WHERE tenant_id=:t AND sku=:s"),
            {"t": str(tenant_id).strip() or DEFAULT_TENANT, "s": str(sku), "ab": str(approved_by)})
        if commit:
            db.commit()
        return bool(getattr(res, "rowcount", 0) or 0)
    except Exception:
        return False


def add_sold_node(db, *, node_handle: str, source: str = "manual",
                  approved_by: Optional[str] = None, tenant_id: str = DEFAULT_TENANT,
                  commit: bool = False) -> bool:
    """Direct grant of a sold node (bootstrap / merchant declaration). Clamped to the release."""
    node = get_node(node_handle)
    if db is None or node is None:
        return False
    try:
        ensure_tables(db)
        p = {"t": str(tenant_id).strip() or DEFAULT_TENANT, "n": node.handle,
             "r": PINNED_RELEASE, "src": source, "ab": approved_by}
        res = db.execute(text(
            "UPDATE sold_taxonomy SET taxonomy_release=:r, source=:src, approved_by=:ab, "
            "updated_at=CURRENT_TIMESTAMP WHERE tenant_id=:t AND node_handle=:n"), p)
        if not (getattr(res, "rowcount", 0) or 0):
            db.execute(text(
                "INSERT INTO sold_taxonomy (id, tenant_id, node_handle, taxonomy_release, source, "
                "approved_by) VALUES (:id,:t,:n,:r,:src,:ab)"), {**p, "id": str(uuid.uuid4())})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


def materialize_sold_taxonomy(db, *, tenant_id: str = DEFAULT_TENANT, commit: bool = True) -> int:
    """Distinct APPROVED classification nodes → sold_taxonomy (the T4 approval consume step)."""
    if db is None:
        return 0
    try:
        ensure_tables(db)
        rows = db.execute(text(
            "SELECT DISTINCT node_handle FROM product_classification "
            "WHERE tenant_id=:t AND status='approved'"),
            {"t": str(tenant_id).strip() or DEFAULT_TENANT}).fetchall()
        n = 0
        for r in rows:
            if add_sold_node(db, node_handle=str(r[0]), source="classification_approval",
                             tenant_id=tenant_id):
                n += 1
        if commit:
            db.commit()
        return n
    except Exception:
        return 0


def sold_nodes(db, *, tenant_id: str = DEFAULT_TENANT) -> Optional[frozenset]:
    """The tenant's sold set, or None when it cannot be read / was never bootstrapped."""
    if db is None:
        return None
    try:
        ensure_tables(db)
        rows = db.execute(text(
            "SELECT node_handle FROM sold_taxonomy WHERE tenant_id=:t"),
            {"t": str(tenant_id).strip() or DEFAULT_TENANT}).fetchall()
        handles = frozenset(str(r[0]) for r in rows)
        return handles if handles else None  # empty = ungrounded tenant, not "sells nothing"
    except Exception:
        return None


def is_sold(db, node_handle: str, *, tenant_id: str = DEFAULT_TENANT) -> Optional[bool]:
    """Tri-state sellability (see module docstring). Only an explicit False may ever justify
    an off-catalog refusal; None means UNGROUNDED — never refuse on None."""
    node = get_node(node_handle)
    if node is None:
        return None
    sold = sold_nodes(db, tenant_id=tenant_id)
    if sold is None:
        return None
    if node.handle in sold:
        return True
    for anc in ancestors(node.handle):
        if anc.handle in sold:
            return True
    return False


def sold_summary(db, *, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Any]:
    """Human/debug view of the tenant's grounding: the sold nodes with their full paths."""
    sold = sold_nodes(db, tenant_id=tenant_id)
    if sold is None:
        return {"grounded": False, "release": PINNED_RELEASE, "nodes": []}
    nodes = [get_node(h) for h in sorted(sold)]
    return {"grounded": True, "release": PINNED_RELEASE,
            "nodes": [{"handle": n.handle, "path": n.full_path} for n in nodes if n]}
