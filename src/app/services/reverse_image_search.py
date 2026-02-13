from __future__ import annotations

from typing import Dict, List
from sqlalchemy import text

from src.app.models.db import db_session


class ReverseImageSearch:
    """Naive phash index lookup over fraud_image_hashes.

    Provides a basic nearest-neighbor by Hamming distance.
    """

    def ensure_index(self) -> None:
        try:
            from src.app.models.db import get_engine

            eng = get_engine()
            try:
                if getattr(eng, "dialect", None) is not None and eng.dialect.name != "sqlite":
                    return
            except Exception:
                pass
            with db_session() as db:
                db.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS fraud_image_hashes (
                            phash TEXT PRIMARY KEY,
                            first_seen_case_id TEXT,
                            times_seen INTEGER DEFAULT 0,
                            confirmed_fraud INTEGER DEFAULT 0,
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                try:
                    db.commit()
                except Exception:
                    pass
        except Exception:
            pass

    def index_phash(self, phash: str, case_id: str | None = None, confirmed_fraud: bool = False) -> None:
        if not phash:
            return
        try:
            self.ensure_index()
            with db_session() as db:
                db.execute(
                    text(
                        """
                        INSERT INTO fraud_image_hashes (phash, first_seen_case_id, times_seen, confirmed_fraud)
                        VALUES (:ph, :cid, 1, :cf)
                        ON CONFLICT(phash) DO UPDATE SET times_seen = fraud_image_hashes.times_seen + 1,
                        confirmed_fraud = MAX(fraud_image_hashes.confirmed_fraud, :cf)
                        """
                    ),
                    {"ph": phash, "cid": case_id or "", "cf": 1 if confirmed_fraud else 0},
                )
                try:
                    db.commit()
                except Exception:
                    pass
        except Exception:
            pass

    def _hamming(self, a: str, b: str) -> int:
        if not a or not b or len(a) != len(b):
            return 64
        try:
            return sum(ch1 != ch2 for ch1, ch2 in zip(a, b))
        except Exception:
            return 64

    def find_similar(self, phash: str, max_distance: int = 8, limit: int = 10, include_self: bool = False) -> List[Dict]:
        results: List[Dict] = []
        self.ensure_index()
        with db_session() as db:
            rows = db.execute(text("SELECT phash, first_seen_case_id, times_seen, confirmed_fraud FROM fraud_image_hashes"))
            for row in rows.fetchall():
                try:
                    p = row[0]
                    if not include_self and p == phash:
                        continue
                    d = self._hamming(phash, p)
                    if d <= max_distance:
                        results.append({
                            "phash": p,
                            "distance": d,
                            "first_seen_case_id": row[1],
                            "times_seen": row[2],
                            "confirmed_fraud": bool(row[3]),
                        })
                except Exception:
                    continue
        results.sort(key=lambda x: x["distance"])
        return results[:limit]
