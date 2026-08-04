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

from sqlalchemy import bindparam, text

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
    dialect = str(
        getattr(
            getattr(getattr(db, "bind", None), "dialect", None),
            "name",
            "",
        )
        or ""
    ).lower()
    # Production schemas are migration-owned. Runtime DDL remains available
    # only for lightweight SQLite development and test databases.
    if dialect and dialect != "sqlite":
        return

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


def classification_nodes_for_skus(db, skus: List[str], *,
                                  tenant_id: str = DEFAULT_TENANT) -> Dict[str, str]:
    """Return approved SKU-to-taxonomy-node mappings in one tenant-scoped read."""
    normalized = list(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
    if db is None or not normalized:
        return {}
    try:
        ensure_tables(db)
        stmt = text(
            "SELECT sku, node_handle FROM product_classification "
            "WHERE tenant_id=:tenant_id AND status='approved' AND sku IN :skus"
        ).bindparams(bindparam("skus", expanding=True))
        rows = db.execute(stmt, {
            "tenant_id": str(tenant_id).strip() or DEFAULT_TENANT,
            "skus": normalized,
        }).fetchall()
        return {str(row[0]): str(row[1]) for row in rows if get_node(str(row[1])) is not None}
    except Exception as exc:
        logger.warning("classification batch read failed: %s", repr(exc)[:160])
        return {}


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


def materialize_sold_taxonomy(db, *, tenant_id: str = DEFAULT_TENANT,
                              commit: bool = True) -> Dict[str, int]:
    """RECONCILIATION, not accumulation (GPT-5.6 finding #2, 2026-07-11): the
    classification-derived sold set becomes EXACTLY the distinct nodes of currently-approved
    classifications — nodes whose products were reclassified/retired are REMOVED, so a stale
    grant can't keep a category sellable forever. Rows from other sources (manual,
    merchant_declaration, demo_bootstrap) are preserved untouched; a node covered by BOTH
    keeps its non-classification source. Returns {added, retired, kept}."""
    out = {"added": 0, "retired": 0, "kept": 0}
    if db is None:
        return out
    try:
        ensure_tables(db)
        t = str(tenant_id).strip() or DEFAULT_TENANT
        approved = {str(r[0]) for r in db.execute(text(
            "SELECT DISTINCT node_handle FROM product_classification "
            "WHERE tenant_id=:t AND status='approved'"), {"t": t}).fetchall()}
        current = {str(r[0]): str(r[1] or "") for r in db.execute(text(
            "SELECT node_handle, source FROM sold_taxonomy WHERE tenant_id=:t"),
            {"t": t}).fetchall()}
        for handle, source in current.items():
            if source == "classification_approval" and handle not in approved:
                db.execute(text(
                    "DELETE FROM sold_taxonomy WHERE tenant_id=:t AND node_handle=:n "
                    "AND source='classification_approval'"), {"t": t, "n": handle})
                out["retired"] += 1
        for handle in sorted(approved):
            if handle in current:
                out["kept"] += 1
            elif add_sold_node(db, node_handle=handle, source="classification_approval",
                               tenant_id=tenant_id):
                out["added"] += 1
        if commit:
            db.commit()
        return out
    except Exception:
        try:
            db.rollback()  # half-applied reconciliation must not persist
        except Exception:
            pass
        return {"added": 0, "retired": 0, "kept": 0, "error": 1}  # counts must not lie post-rollback


# Grounding statuses (GPT-5.6 finding #3, 2026-07-11): an infrastructure ERROR must be
# distinguishable from a tenant that was never grounded (EMPTY) — both collapse to None in
# is_sold/sells_within (never refuse on either), but the V2 router must serve a DEGRADED
# catalog-verification response on ERROR instead of silently recommending as if healthy.
GROUNDING_GROUNDED = "grounded"
GROUNDING_EMPTY = "empty"
GROUNDING_ERROR = "error"


def _sold_set(db, tenant_id: str) -> tuple:
    """(status, frozenset) — the one place the sold set is read; everything else derives."""
    if db is None:
        return (GROUNDING_ERROR, frozenset())
    try:
        ensure_tables(db)
        rows = db.execute(text(
            "SELECT node_handle FROM sold_taxonomy WHERE tenant_id=:t"),
            {"t": str(tenant_id).strip() or DEFAULT_TENANT}).fetchall()
        handles = frozenset(str(r[0]) for r in rows)
        return (GROUNDING_GROUNDED, handles) if handles else (GROUNDING_EMPTY, frozenset())
    except Exception as exc:
        logger.warning("sold_taxonomy read FAILED (tenant=%s): %s — grounding=error, callers "
                       "must degrade, not recommend-as-healthy", tenant_id, repr(exc)[:120])
        return (GROUNDING_ERROR, frozenset())


def grounding_status(db, *, tenant_id: str = DEFAULT_TENANT) -> str:
    """'grounded' | 'empty' | 'error' — the router's degradation signal."""
    return _sold_set(db, tenant_id)[0]


def sold_nodes(db, *, tenant_id: str = DEFAULT_TENANT) -> Optional[frozenset]:
    """The tenant's sold set, or None when EMPTY or ERROR (use grounding_status to tell
    which — the behavioral difference belongs to the caller, the ambiguity must not)."""
    status, handles = _sold_set(db, str(tenant_id))
    return handles if status == GROUNDING_GROUNDED else None


def is_sold(db, node_handle: str, *, tenant_id: str = DEFAULT_TENANT) -> Optional[bool]:
    """STRICT tri-state sellability: True when the node or an ancestor is granted (a granted
    node covers its subtree). Deliberately does NOT look at descendants — use sells_within()
    for refusal gating; this predicate answers "is everything AT this node covered?"."""
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


def sells_within(db, node_handle: str, *, tenant_id: str = DEFAULT_TENANT) -> Optional[bool]:
    """THE REFUSAL GATE (tri-state): does the tenant's sold set overlap this node's subtree
    at all — node, ancestor, or ANY DESCENDANT? A store selling only 'Vitamin D' must not
    refuse 'do you sell vitamins?' (parent query, children sold) — per-product classification
    grants LEAVES, so parent-category queries need the descendant direction too. Refuse
    off-catalog ONLY on an explicit False from THIS predicate; None = ungrounded, never refuse."""
    node = get_node(node_handle)
    if node is None:
        return None
    sold = sold_nodes(db, tenant_id=tenant_id)
    if sold is None:
        return None
    if node.handle in sold or any(a.handle in sold for a in ancestors(node.handle)):
        return True
    prefix = node.handle + "-"
    return any(h.startswith(prefix) for h in sold)


def primary_sold_node(db, *, tenant_id: str = DEFAULT_TENANT) -> Optional[str]:
    """The tenant's DOMINANT sold DEVICE node — the sold node with the most approved
    product_classification rows (Laptops for the demo). This is the reroute target when a
    shopper names a WORKLOAD ('play valorant') rather than a device (M3-C1): the store's
    primary device category is what runs it. Deterministic tie-break by handle; None when
    ungrounded. Vertical-blind — 'most-classified sold node' is furniture/pharma-agnostic.

    A granted node need not itself carry classifications (a coarse 'el-6-6' grant can cover
    per-leaf classifications under it), so a row is counted toward a sold node when the row's
    handle is that node OR sits in its subtree; the granted node with the largest covered
    count wins."""
    sold = sold_nodes(db, tenant_id=tenant_id)
    if not sold:
        return None
    from sqlalchemy import text as _sql
    try:
        rows = db.execute(_sql(
            "SELECT node_handle, COUNT(*) AS n FROM product_classification "
            "WHERE tenant_id=:t AND status='approved' GROUP BY node_handle"),
            {"t": str(tenant_id)}).fetchall()
    except Exception as exc:
        logger.debug("primary_sold_node count failed: %s", repr(exc)[:100])
        return None
    counts: Dict[str, int] = {}
    for handle, n in rows:
        h = str(handle)
        for granted in sold:
            if h == granted or h.startswith(granted + "-"):
                counts[granted] = counts.get(granted, 0) + int(n or 0)
    if not counts:
        # granted but nothing classified under any grant → the lexically-first sold node,
        # a stable deterministic fallback (never a guess between equals).
        return sorted(sold)[0]
    # max count, tie-break by handle (deterministic)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def sold_summary(db, *, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Any]:
    """Human/debug view of the tenant's grounding: the sold nodes with their full paths."""
    sold = sold_nodes(db, tenant_id=tenant_id)
    if sold is None:
        return {"grounded": False, "release": PINNED_RELEASE, "nodes": []}
    nodes = [get_node(h) for h in sorted(sold)]
    return {"grounded": True, "release": PINNED_RELEASE,
            "nodes": [{"handle": n.handle, "path": n.full_path} for n in nodes if n]}
