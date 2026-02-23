"""Cross-session image clustering (P2).

Detects coordinated fraud rings by clustering images across claims/sessions
using device fingerprints (EXIF camera model + serial), perceptual hashes,
and structural similarity.

Storage is DB-backed so clusters persist across sessions.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session


def _ensure_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS image_fingerprints (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT,
                        claim_id TEXT,
                        session_id TEXT,
                        sha256 TEXT NOT NULL,
                        phash TEXT,
                        dhash TEXT,
                        camera_make TEXT,
                        camera_model TEXT,
                        camera_serial TEXT,
                        device_fingerprint TEXT,
                        gps_lat REAL,
                        gps_lon REAL,
                        exif_datetime TEXT,
                        filename TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text("CREATE INDEX IF NOT EXISTS idx_imgfp_device ON image_fingerprints(tenant_id, device_fingerprint)")
            )
            db.execute(
                text("CREATE INDEX IF NOT EXISTS idx_imgfp_phash ON image_fingerprints(tenant_id, phash)")
            )
            db.execute(
                text("CREATE INDEX IF NOT EXISTS idx_imgfp_sha256 ON image_fingerprints(tenant_id, sha256)")
            )
            db.commit()
    except Exception:
        pass


def _device_fingerprint(make: str | None, model: str | None, serial: str | None) -> str | None:
    """Create a deterministic device fingerprint from camera metadata."""
    parts = [
        (make or "").strip().lower(),
        (model or "").strip().lower(),
        (serial or "").strip().lower(),
    ]
    combined = "|".join(parts)
    if combined == "||":
        return None
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:24]


def _hamming_distance(a: str, b: str) -> int:
    return sum(c1 != c2 for c1, c2 in zip(a, b))


def record_image_fingerprint(
    *,
    tenant_id: str | None,
    claim_id: str | None,
    session_id: str | None,
    sha256: str,
    phash: str | None = None,
    dhash: str | None = None,
    camera_make: str | None = None,
    camera_model: str | None = None,
    camera_serial: str | None = None,
    gps_lat: float | None = None,
    gps_lon: float | None = None,
    exif_datetime: str | None = None,
    filename: str | None = None,
) -> Dict[str, Any]:
    """Record an image fingerprint and return any cross-session matches."""
    _ensure_table()
    import uuid

    fp_id = f"imgfp-{uuid.uuid4().hex[:16]}"
    device_fp = _device_fingerprint(camera_make, camera_model, camera_serial)
    tenant = tenant_id or "default"

    # Insert the fingerprint
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO image_fingerprints
                    (id, tenant_id, claim_id, session_id, sha256, phash, dhash,
                     camera_make, camera_model, camera_serial, device_fingerprint,
                     gps_lat, gps_lon, exif_datetime, filename, created_at)
                    VALUES
                    (:id, :tenant_id, :claim_id, :session_id, :sha256, :phash, :dhash,
                     :camera_make, :camera_model, :camera_serial, :device_fingerprint,
                     :gps_lat, :gps_lon, :exif_datetime, :filename, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": fp_id,
                    "tenant_id": tenant,
                    "claim_id": claim_id,
                    "session_id": session_id,
                    "sha256": sha256,
                    "phash": phash,
                    "dhash": dhash,
                    "camera_make": camera_make,
                    "camera_model": camera_model,
                    "camera_serial": camera_serial,
                    "device_fingerprint": device_fp,
                    "gps_lat": gps_lat,
                    "gps_lon": gps_lon,
                    "exif_datetime": exif_datetime,
                    "filename": filename,
                },
            )
            db.commit()
    except Exception:
        pass

    # Find cross-session matches
    matches = find_cross_session_matches(
        tenant_id=tenant,
        sha256=sha256,
        phash=phash,
        device_fingerprint=device_fp,
        exclude_claim_id=claim_id,
    )

    return {
        "fingerprint_id": fp_id,
        "device_fingerprint": device_fp,
        "matches": matches,
        "is_fraud_ring_candidate": len(matches) >= 2,
    }


def find_cross_session_matches(
    *,
    tenant_id: str | None,
    sha256: str | None = None,
    phash: str | None = None,
    device_fingerprint: str | None = None,
    exclude_claim_id: str | None = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Find images from other claims/sessions that match by device, hash, or phash."""
    _ensure_table()
    tenant = tenant_id or "default"
    matches: List[Dict[str, Any]] = []
    seen_ids: set = set()

    try:
        with db_session() as db:
            # 1. Exact SHA256 match (duplicate image across claims)
            if sha256:
                rows = db.execute(
                    text(
                        """
                        SELECT id, claim_id, session_id, sha256, phash, device_fingerprint,
                               camera_make, camera_model, filename, created_at
                        FROM image_fingerprints
                        WHERE tenant_id = :tenant AND sha256 = :sha256
                          AND (:exclude IS NULL OR claim_id != :exclude)
                        ORDER BY created_at DESC LIMIT :lim
                        """
                    ),
                    {"tenant": tenant, "sha256": sha256, "exclude": exclude_claim_id, "lim": limit},
                ).fetchall()
                for r in rows or []:
                    if r[0] not in seen_ids:
                        seen_ids.add(r[0])
                        matches.append({
                            "match_type": "exact_duplicate",
                            "fingerprint_id": r[0],
                            "claim_id": r[1],
                            "session_id": r[2],
                            "camera_model": f"{r[6] or ''} {r[7] or ''}".strip(),
                            "filename": r[8],
                            "created_at": r[9],
                            "confidence": 1.0,
                        })

            # 2. Same device fingerprint (same camera across claims)
            if device_fingerprint:
                rows = db.execute(
                    text(
                        """
                        SELECT id, claim_id, session_id, sha256, phash, device_fingerprint,
                               camera_make, camera_model, filename, created_at
                        FROM image_fingerprints
                        WHERE tenant_id = :tenant AND device_fingerprint = :dfp
                          AND (:exclude IS NULL OR claim_id != :exclude)
                        ORDER BY created_at DESC LIMIT :lim
                        """
                    ),
                    {"tenant": tenant, "dfp": device_fingerprint, "exclude": exclude_claim_id, "lim": limit},
                ).fetchall()
                for r in rows or []:
                    if r[0] not in seen_ids:
                        seen_ids.add(r[0])
                        matches.append({
                            "match_type": "same_device",
                            "fingerprint_id": r[0],
                            "claim_id": r[1],
                            "session_id": r[2],
                            "camera_model": f"{r[6] or ''} {r[7] or ''}".strip(),
                            "filename": r[8],
                            "created_at": r[9],
                            "confidence": 0.85,
                        })

            # 3. Perceptual hash near-match (similar images across claims)
            if phash and len(phash) >= 49:
                # Fetch recent phashes and compare hamming distance in-app
                rows = db.execute(
                    text(
                        """
                        SELECT id, claim_id, session_id, phash, device_fingerprint,
                               camera_make, camera_model, filename, created_at
                        FROM image_fingerprints
                        WHERE tenant_id = :tenant AND phash IS NOT NULL
                          AND (:exclude IS NULL OR claim_id != :exclude)
                        ORDER BY created_at DESC LIMIT 500
                        """
                    ),
                    {"tenant": tenant, "exclude": exclude_claim_id},
                ).fetchall()
                for r in rows or []:
                    if r[0] in seen_ids:
                        continue
                    stored_phash = r[3] or ""
                    if len(stored_phash) != len(phash):
                        continue
                    dist = _hamming_distance(phash, stored_phash)
                    if dist <= 8:  # near-duplicate threshold
                        seen_ids.add(r[0])
                        matches.append({
                            "match_type": "perceptual_near_duplicate",
                            "fingerprint_id": r[0],
                            "claim_id": r[1],
                            "session_id": r[2],
                            "phash_distance": dist,
                            "camera_model": f"{r[5] or ''} {r[6] or ''}".strip(),
                            "filename": r[7],
                            "created_at": r[8],
                            "confidence": round(max(0.5, 1.0 - dist / 16.0), 3),
                        })
    except Exception:
        pass

    return matches[:limit]


def get_fraud_ring_clusters(
    *,
    tenant_id: str | None,
    min_claims: int = 2,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Identify potential fraud ring clusters — devices appearing across multiple claims."""
    _ensure_table()
    tenant = tenant_id or "default"
    clusters: List[Dict[str, Any]] = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT device_fingerprint, camera_make, camera_model,
                           COUNT(DISTINCT claim_id) as claim_count,
                           GROUP_CONCAT(DISTINCT claim_id) as claim_ids
                    FROM image_fingerprints
                    WHERE tenant_id = :tenant AND device_fingerprint IS NOT NULL
                    GROUP BY device_fingerprint, camera_make, camera_model
                    HAVING COUNT(DISTINCT claim_id) >= :min_claims
                    ORDER BY claim_count DESC
                    LIMIT :lim
                    """
                ),
                {"tenant": tenant, "min_claims": min_claims, "lim": limit},
            ).fetchall()
            for r in rows or []:
                clusters.append({
                    "device_fingerprint": r[0],
                    "camera_make": r[1],
                    "camera_model": r[2],
                    "claim_count": int(r[3]),
                    "claim_ids": (r[4] or "").split(",")[:20],
                    "risk": "high" if int(r[3]) >= 5 else "medium",
                })
    except Exception:
        pass
    return clusters
