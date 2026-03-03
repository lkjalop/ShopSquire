from __future__ import annotations

from typing import Any, Dict, List
import os

import httpx
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

    def external_lookup(self, *, phash: str | None, sha256: str | None, sku: str | None = None) -> Dict[str, Any]:
        """Query manufacturer and known-fraud reverse-image endpoints (best-effort).

        Env config (comma-separated URLs):
          - REVERSE_IMAGE_MANUFACTURER_ENDPOINTS
          - REVERSE_IMAGE_FRAUD_DB_ENDPOINTS
        Each endpoint receives query params: phash, sha256, sku.
        Expected response shape (lenient):
          {"matches": [{"source": "...", "url": "...", "confidence": 0.0-1.0, "fraud": bool}]}
        """
        out: Dict[str, Any] = {
            "manufacturer_matches": [],
            "fraud_db_matches": [],
            "errors": [],
        }
        manu_eps = [x.strip() for x in str(os.getenv("REVERSE_IMAGE_MANUFACTURER_ENDPOINTS", "") or "").split(",") if x.strip()]
        fraud_eps = [x.strip() for x in str(os.getenv("REVERSE_IMAGE_FRAUD_DB_ENDPOINTS", "") or "").split(",") if x.strip()]
        if not manu_eps and not fraud_eps:
            return out

        params = {"phash": phash or "", "sha256": sha256 or "", "sku": sku or ""}
        timeout = float(os.getenv("REVERSE_IMAGE_LOOKUP_TIMEOUT_SEC", "2.5") or 2.5)

        def _query(endpoint: str) -> List[Dict[str, Any]]:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(endpoint, params=params)
                r.raise_for_status()
                payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            matches = payload.get("matches") if isinstance(payload, dict) else []
            if not isinstance(matches, list):
                return []
            normalized: List[Dict[str, Any]] = []
            for m in matches:
                if not isinstance(m, dict):
                    continue
                normalized.append(
                    {
                        "source": str(m.get("source") or endpoint),
                        "url": str(m.get("url") or ""),
                        "confidence": float(m.get("confidence") or 0.0),
                        "fraud": bool(m.get("fraud") or False),
                    }
                )
            return normalized

        for ep in manu_eps:
            try:
                out["manufacturer_matches"].extend(_query(ep))
            except Exception as exc:
                out["errors"].append({"endpoint": ep, "error": str(exc)[:160]})

        for ep in fraud_eps:
            try:
                out["fraud_db_matches"].extend(_query(ep))
            except Exception as exc:
                out["errors"].append({"endpoint": ep, "error": str(exc)[:160]})

        return out
