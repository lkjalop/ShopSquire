from __future__ import annotations

import json
from typing import Dict, List, Optional

from sqlalchemy import text
from src.app.models.db import db_session


class WarehouseVerification:
    """Compares complaint vs return photo analyses for mismatches."""

    def fetch_analyses(self, case_id: str, limit: int = 10) -> List[Dict]:
        with db_session() as db:
            rows = db.execute(
                text(
                    "SELECT image_sha256, image_phash, damage_type, damage_location, severity, confidence, raw_labels, extracted_text, created_at "
                    "FROM cv_analyses WHERE case_id = :cid ORDER BY created_at ASC LIMIT :lim"
                ),
                {"cid": case_id, "lim": int(limit)},
            ).mappings().all()
            out: List[Dict] = []
            for r in rows:
                try:
                    labels = json.loads(r.get("raw_labels") or "[]")
                except Exception:
                    labels = []
                out.append({
                    "image_sha256": r.get("image_sha256"),
                    "image_phash": r.get("image_phash"),
                    "damage_type": r.get("damage_type"),
                    "damage_location": r.get("damage_location"),
                    "severity": r.get("severity"),
                    "confidence": float(r.get("confidence") or 0.0),
                    "labels": labels,
                    "text": r.get("extracted_text") or "",
                    "created_at": r.get("created_at"),
                })
            return out

    def compare_latest_pair(self, case_id: str) -> Dict:
        """Compare earliest vs latest analysis to flag mismatches.
        Heuristics:
        - Different damage_type/location/severity
        - Label overlap (Jaccard) below threshold
        - Confidence delta beyond threshold
        """
        analyses = self.fetch_analyses(case_id, limit=50)
        if len(analyses) < 2:
            return {"status": "insufficient_evidence", "case_id": case_id, "analyses_count": len(analyses)}
        first = analyses[0]
        last = analyses[-1]
        mismatches: List[str] = []
        if (first.get("damage_type") or "") != (last.get("damage_type") or ""):
            mismatches.append("damage_type")
        if (first.get("severity") or "") != (last.get("severity") or ""):
            mismatches.append("severity")
        if (first.get("damage_location") or "") != (last.get("damage_location") or ""):
            mismatches.append("damage_location")
        # Label overlap
        a = set([str(x).lower() for x in (first.get("labels") or [])])
        b = set([str(x).lower() for x in (last.get("labels") or [])])
        j = (len(a & b) / max(1, len(a | b))) if (a or b) else 1.0
        if j < 0.3:
            mismatches.append("labels_overlap_low")
        # Confidence delta
        c1 = float(first.get("confidence") or 0.0)
        c2 = float(last.get("confidence") or 0.0)
        if abs(c2 - c1) >= 0.4:
            mismatches.append("confidence_delta_high")
        # phash mismatch (if available)
        try:
            def _hamming(a: str, b: str) -> int:
                if not a or not b or len(a) != len(b):
                    return 0
                try:
                    return sum(ch1 != ch2 for ch1, ch2 in zip(a, b))
                except Exception:
                    return 0
            pa = str(first.get("image_phash") or "")
            pb = str(last.get("image_phash") or "")
            if pa and pb:
                if _hamming(pa, pb) >= 8:
                    mismatches.append("phash_mismatch_high")
        except Exception:
            pass
        return {
            "status": "ok",
            "case_id": case_id,
            "mismatches": mismatches,
            "first": first,
            "last": last,
        }
