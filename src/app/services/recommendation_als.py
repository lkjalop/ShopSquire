from __future__ import annotations

import json
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from sqlalchemy import text, bindparam

from src.app.models.db import db_session


def ensure_recommend_cf_tables(db) -> None:
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommend_cf_model (
                    model_version TEXT PRIMARY KEY,
                    trained_at TEXT,
                    lookback_days INTEGER,
                    metadata_json TEXT
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommend_cf_scores (
                    id TEXT PRIMARY KEY,
                    model_version TEXT NOT NULL,
                    uid_hash TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    score REAL NOT NULL,
                    rank_pos INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_reco_cf_uid ON recommend_cf_scores(uid_hash)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_reco_cf_uid_sku ON recommend_cf_scores(uid_hash, sku)"))
    except Exception:
        pass


def _implicit_weight(action: str, n: int) -> float:
    a = str(action or "").strip().lower()
    base = {
        "view": 0.4,
        "hover": 0.15,
        "click": 1.0,
        "add_to_cart": 1.5,
        "atc": 1.5,
        "cart_add": 1.5,
        "purchase": 2.2,
        "order": 2.2,
    }.get(a, 0.25)
    return base * max(1.0, math.log1p(float(max(0, int(n)))))


def _build_interaction_matrix(db, lookback_days: int = 120) -> Tuple[List[str], List[str], List[List[float]]]:
    rows = db.execute(
        text(
            """
            SELECT uid_hash, sku, action, COUNT(*) AS n
            FROM recommend_interactions
            WHERE uid_hash IS NOT NULL
              AND sku IS NOT NULL
              AND datetime(event_time) >= datetime('now', :window)
            GROUP BY uid_hash, sku, action
            """
        ),
        {"window": f"-{max(1, int(lookback_days))} days"},
    ).fetchall()
    if not rows:
        return [], [], []
    uids = sorted({str(r[0]) for r in rows if r[0]})
    skus = sorted({str(r[1]) for r in rows if r[1]})
    if not uids or not skus:
        return [], [], []
    ui = {u: idx for idx, u in enumerate(uids)}
    ii = {s: idx for idx, s in enumerate(skus)}
    mat = [[0.0 for _ in skus] for _ in uids]
    for r in rows:
        u = str(r[0] or "")
        s = str(r[1] or "")
        if not u or not s:
            continue
        weight = _implicit_weight(str(r[2] or ""), int(r[3] or 0))
        mat[ui[u]][ii[s]] += float(weight)
    return uids, skus, mat


def _als_factorize(
    matrix: List[List[float]],
    factors: int = 12,
    iters: int = 6,
    reg: float = 0.08,
) -> Tuple[List[List[float]], List[List[float]]]:
    # Lightweight numpy-free fallback ALS to keep dependency-free behavior.
    # Uses deterministic seeded initialization.
    if not matrix or not matrix[0]:
        return [], []
    users = len(matrix)
    items = len(matrix[0])
    k = max(4, min(int(factors), 24))
    u_lat = [[(0.01 * ((i + 1) * (f + 3) % 11)) for f in range(k)] for i in range(users)]
    i_lat = [[(0.01 * ((j + 2) * (f + 5) % 13)) for f in range(k)] for j in range(items)]

    def dot(a: List[float], b: List[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    def solve_least_squares(lhs: List[List[float]], rhs: List[float]) -> List[float]:
        # Naive Gauss-Seidel for tiny k; robust enough for this use-case.
        x = [0.0 for _ in range(len(rhs))]
        for _ in range(24):
            for p in range(len(rhs)):
                diag = lhs[p][p] if lhs[p][p] != 0 else 1e-6
                residual = rhs[p]
                for q in range(len(rhs)):
                    if q == p:
                        continue
                    residual -= lhs[p][q] * x[q]
                x[p] = residual / diag
        return x

    for _ in range(max(1, int(iters))):
        # Update user factors
        for u in range(users):
            lhs = [[0.0 for _ in range(k)] for _ in range(k)]
            rhs = [0.0 for _ in range(k)]
            for j in range(items):
                r = float(matrix[u][j])
                if r <= 0:
                    continue
                v = i_lat[j]
                c = 1.0 + r
                for a in range(k):
                    rhs[a] += c * r * v[a]
                    for b in range(k):
                        lhs[a][b] += c * v[a] * v[b]
            for a in range(k):
                lhs[a][a] += reg
            u_lat[u] = solve_least_squares(lhs, rhs)
        # Update item factors
        for j in range(items):
            lhs = [[0.0 for _ in range(k)] for _ in range(k)]
            rhs = [0.0 for _ in range(k)]
            for u in range(users):
                r = float(matrix[u][j])
                if r <= 0:
                    continue
                v = u_lat[u]
                c = 1.0 + r
                for a in range(k):
                    rhs[a] += c * r * v[a]
                    for b in range(k):
                        lhs[a][b] += c * v[a] * v[b]
            for a in range(k):
                lhs[a][a] += reg
            i_lat[j] = solve_least_squares(lhs, rhs)
    return u_lat, i_lat


def train_recommend_als(
    *,
    lookback_days: int = 120,
    topk_per_user: int = 80,
    factors: int = 12,
    iters: int = 6,
    reg: float = 0.08,
) -> Dict[str, int | str]:
    with db_session() as db:
        ensure_recommend_cf_tables(db)
        uids, skus, mat = _build_interaction_matrix(db, lookback_days=lookback_days)
        if not mat:
            return {"status": "no_data", "users": 0, "items": 0, "scores": 0}

        try:
            # Prefer implicit library when present.
            import numpy as np  # type: ignore
            from implicit.als import AlternatingLeastSquares  # type: ignore

            arr = np.array(mat, dtype="float32")
            # implicit expects item-user sparse matrix, keep dense for small nightly jobs.
            model = AlternatingLeastSquares(factors=max(8, int(factors)), regularization=float(reg), iterations=max(4, int(iters)))
            model.fit(arr.T)
            u_fac = model.user_factors.tolist()
            i_fac = model.item_factors.tolist()
            engine = "implicit_als"
        except Exception:
            u_fac, i_fac = _als_factorize(mat, factors=factors, iters=iters, reg=reg)
            engine = "fallback_als"

        def dot(a: List[float], b: List[float]) -> float:
            return sum(float(x) * float(y) for x, y in zip(a, b))

        model_version = f"als_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        db.execute(text("DELETE FROM recommend_cf_scores"))
        inserted = 0
        k_top = max(20, min(int(topk_per_user), 200))
        for u_idx, uid in enumerate(uids):
            if u_idx >= len(u_fac):
                continue
            preds: List[Tuple[str, float]] = []
            for i_idx, sku in enumerate(skus):
                if i_idx >= len(i_fac):
                    continue
                preds.append((sku, dot(u_fac[u_idx], i_fac[i_idx])))
            preds.sort(key=lambda x: x[1], reverse=True)
            for rank_pos, (sku, score) in enumerate(preds[:k_top], start=1):
                db.execute(
                    text(
                        """
                        INSERT INTO recommend_cf_scores
                        (id, model_version, uid_hash, sku, score, rank_pos)
                        VALUES (:id, :model_version, :uid_hash, :sku, :score, :rank_pos)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "model_version": model_version,
                        "uid_hash": uid,
                        "sku": sku,
                        "score": float(score),
                        "rank_pos": int(rank_pos),
                    },
                )
                inserted += 1
        db.execute(
            text(
                """
                INSERT INTO recommend_cf_model (model_version, trained_at, lookback_days, metadata_json)
                VALUES (:model_version, :trained_at, :lookback_days, :metadata_json)
                """
            ),
            {
                "model_version": model_version,
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "lookback_days": int(lookback_days),
                "metadata_json": json.dumps(
                    {
                        "engine": engine,
                        "users": len(uids),
                        "items": len(skus),
                        "factors": int(factors),
                        "iters": int(iters),
                        "reg": float(reg),
                        "env": os.getenv("ENV", "dev"),
                    },
                    ensure_ascii=False,
                ),
            },
        )
        try:
            db.commit()
        except Exception:
            pass
    return {"status": "ok", "users": len(uids), "items": len(skus), "scores": inserted, "model_version": model_version}


def load_precomputed_cf_scores(db, uid_hashes: List[str], candidate_skus: List[str]) -> Dict[str, float]:
    uids = [str(u).strip() for u in (uid_hashes or []) if str(u).strip()]
    skus = [str(s).strip() for s in (candidate_skus or []) if str(s).strip()]
    if not uids or not skus:
        return {}
    ensure_recommend_cf_tables(db)
    rows = db.execute(
        text(
            """
            SELECT sku, MAX(score) AS best_score
            FROM recommend_cf_scores
            WHERE uid_hash IN :uids
              AND sku IN :skus
            GROUP BY sku
            """
        ).bindparams(
            bindparam("uids", expanding=True),
            bindparam("skus", expanding=True),
        ),
        {"uids": uids, "skus": skus},
    ).fetchall()
    out: Dict[str, float] = {}
    for r in rows or []:
        sku = str(r[0] or "").strip()
        if not sku:
            continue
        out[sku] = float(r[1] or 0.0)
    return out
