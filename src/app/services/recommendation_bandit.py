from __future__ import annotations

import json
import math
import uuid
from typing import Any, Dict, List

from sqlalchemy import text


_ARMS = ("balanced", "explore_novelty", "price_value", "personalized_heavy")


def ensure_recommend_bandit_tables(db) -> None:
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommend_bandit_arms (
                    arm TEXT PRIMARY KEY,
                    a_json TEXT NOT NULL,
                    b_json TEXT NOT NULL,
                    pulls INTEGER DEFAULT 0,
                    reward_sum REAL DEFAULT 0.0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommend_bandit_events (
                    id TEXT PRIMARY KEY,
                    uid_hash TEXT,
                    sku TEXT,
                    arm TEXT,
                    reward REAL,
                    context_json TEXT,
                    event_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    except Exception:
        pass


def _default_vec(dim: int, diag: float = 1.0) -> List[List[float]]:
    return [[diag if i == j else 0.0 for j in range(dim)] for i in range(dim)]


def _dot(a: List[float], b: List[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def _mat_vec(m: List[List[float]], x: List[float]) -> List[float]:
    return [_dot(row, x) for row in m]


def _invert(mat: List[List[float]]) -> List[List[float]]:
    # Tiny matrix inversion via Gauss-Jordan for deterministic dependency-free LinUCB.
    n = len(mat)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(mat)]
    for i in range(n):
        pivot = a[i][i]
        if abs(pivot) < 1e-9:
            for r in range(i + 1, n):
                if abs(a[r][i]) > abs(pivot):
                    a[i], a[r] = a[r], a[i]
                    pivot = a[i][i]
                    break
        if abs(pivot) < 1e-9:
            pivot = 1e-9
        inv_p = 1.0 / pivot
        for c in range(2 * n):
            a[i][c] *= inv_p
        for r in range(n):
            if r == i:
                continue
            factor = a[r][i]
            if factor == 0:
                continue
            for c in range(2 * n):
                a[r][c] -= factor * a[i][c]
    return [row[n:] for row in a]


def _context_vector(context: Dict[str, Any] | None) -> List[float]:
    c = context if isinstance(context, dict) else {}
    return [
        float(c.get("budget_tight", 0.0) or 0.0),
        float(c.get("is_repeat_user", 0.0) or 0.0),
        float(c.get("query_specificity", 0.0) or 0.0),
        float(c.get("inventory_pressure", 0.0) or 0.0),
        1.0,
    ]


def choose_recommendation_arm(db, context: Dict[str, Any] | None, alpha: float = 0.55) -> Dict[str, Any]:
    ensure_recommend_bandit_tables(db)
    x = _context_vector(context)
    dim = len(x)
    arms_data: Dict[str, Dict[str, Any]] = {}
    for arm in _ARMS:
        row = db.execute(
            text("SELECT a_json, b_json, pulls, reward_sum FROM recommend_bandit_arms WHERE arm = :arm"),
            {"arm": arm},
        ).fetchone()
        if row is None:
            a = _default_vec(dim, diag=1.0)
            b = [0.0 for _ in range(dim)]
            db.execute(
                text(
                    """
                    INSERT INTO recommend_bandit_arms (arm, a_json, b_json, pulls, reward_sum)
                    VALUES (:arm, :a_json, :b_json, 0, 0.0)
                    """
                ),
                {"arm": arm, "a_json": json.dumps(a), "b_json": json.dumps(b)},
            )
            arms_data[arm] = {"A": a, "b": b, "pulls": 0, "reward_sum": 0.0}
            continue
        try:
            a = json.loads(str(row[0] or "[]"))
            b = json.loads(str(row[1] or "[]"))
            if not isinstance(a, list) or not isinstance(b, list):
                raise ValueError("invalid bandit row")
        except Exception:
            a = _default_vec(dim, diag=1.0)
            b = [0.0 for _ in range(dim)]
        arms_data[arm] = {"A": a, "b": b, "pulls": int(row[2] or 0), "reward_sum": float(row[3] or 0.0)}
    try:
        db.commit()
    except Exception:
        pass

    best_arm = "balanced"
    best_p = -1e9
    for arm, d in arms_data.items():
        A = d["A"]
        b = d["b"]
        A_inv = _invert(A)
        theta = _mat_vec(A_inv, b)
        mean = _dot(theta, x)
        # x^T A^-1 x
        tmp = _mat_vec(A_inv, x)
        var = max(0.0, _dot(x, tmp))
        bonus = float(alpha) * math.sqrt(var)
        p = mean + bonus
        if p > best_p:
            best_p = p
            best_arm = arm
    return {"arm": best_arm, "score": round(float(best_p), 6), "context": x}


def record_bandit_reward(
    db,
    *,
    uid_hash: str,
    sku: str,
    arm: str,
    reward: float,
    context: Dict[str, Any] | None,
) -> None:
    ensure_recommend_bandit_tables(db)
    x = _context_vector(context)
    dim = len(x)
    chosen = str(arm or "balanced").strip() or "balanced"
    row = db.execute(
        text("SELECT a_json, b_json, pulls, reward_sum FROM recommend_bandit_arms WHERE arm = :arm"),
        {"arm": chosen},
    ).fetchone()
    if row is None:
        A = _default_vec(dim, diag=1.0)
        b = [0.0 for _ in range(dim)]
        pulls = 0
        reward_sum = 0.0
    else:
        try:
            A = json.loads(str(row[0] or "[]"))
            b = json.loads(str(row[1] or "[]"))
        except Exception:
            A = _default_vec(dim, diag=1.0)
            b = [0.0 for _ in range(dim)]
        pulls = int(row[2] or 0)
        reward_sum = float(row[3] or 0.0)
    # LinUCB update: A += x x^T, b += r x
    for i in range(dim):
        b[i] = float(b[i]) + float(reward) * float(x[i])
        for j in range(dim):
            A[i][j] = float(A[i][j]) + float(x[i]) * float(x[j])
    db.execute(
        text(
            """
            INSERT INTO recommend_bandit_arms (arm, a_json, b_json, pulls, reward_sum, updated_at)
            VALUES (:arm, :a_json, :b_json, :pulls, :reward_sum, CURRENT_TIMESTAMP)
            ON CONFLICT(arm) DO UPDATE SET
                a_json = excluded.a_json,
                b_json = excluded.b_json,
                pulls = excluded.pulls,
                reward_sum = excluded.reward_sum,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "arm": chosen,
            "a_json": json.dumps(A),
            "b_json": json.dumps(b),
            "pulls": pulls + 1,
            "reward_sum": reward_sum + float(reward),
        },
    )
    db.execute(
        text(
            """
            INSERT INTO recommend_bandit_events (id, uid_hash, sku, arm, reward, context_json)
            VALUES (:id, :uid_hash, :sku, :arm, :reward, :context_json)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "uid_hash": str(uid_hash or ""),
            "sku": str(sku or ""),
            "arm": chosen,
            "reward": float(reward),
            "context_json": json.dumps(context or {}, ensure_ascii=False),
        },
    )
    try:
        db.commit()
    except Exception:
        pass
