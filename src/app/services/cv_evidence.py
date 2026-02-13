from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Any

from src.app.models.db import db_session
try:
    from src.app.services.image_forensics import ForensicsResult
except Exception:
    ForensicsResult = None


_SN_PAT = re.compile(r"\b(?:SN|S/N|Serial)[:\s-]*([A-Za-z0-9-]{4,})\b", re.IGNORECASE)


def _extract_serial(text: str) -> Optional[str]:
    if not text:
        return None
    m = _SN_PAT.search(text)
    return m.group(1) if m else None


def persist_cv_analysis(
    case_id: str,
    image_sha256: Optional[str],
    image_phash: Optional[str],
    analysis: Dict,
    labels: List[str],
    extracted_text: str,
    provider: str,
    model: str,
    processing_time_ms: int,
) -> None:
    serial = _extract_serial(extracted_text or "")
    payload = {
        "damage_type": analysis.get("damage_type"),
        "damage_location": analysis.get("component") or analysis.get("location"),
        "severity": analysis.get("severity"),
        "confidence": float(analysis.get("confidence") or 0.0),
        "serial_number": serial,
        "extracted_text": extracted_text or "",
        "raw_labels": json.dumps(labels or []),
        "model_version": model,
        "processing_time_ms": int(processing_time_ms or 0),
    }
    with db_session() as db:
        db.execute(
            """
            INSERT INTO cv_analyses (
              id, case_id, image_sha256, image_phash,
              damage_type, damage_location, severity, confidence,
              serial_number, extracted_text, raw_labels,
              model_version, processing_time_ms, created_at
            ) VALUES (
              :id, :case_id, :image_sha256, :image_phash,
              :damage_type, :damage_location, :severity, :confidence,
              :serial_number, :extracted_text, :raw_labels,
              :model_version, :processing_time_ms, CURRENT_TIMESTAMP
            )
            """,
            {
                "id": __import__("uuid").uuid4().hex,
                "case_id": case_id,
                "image_sha256": image_sha256,
                "image_phash": image_phash,
                **payload,
            },
        )
        try:
            db.commit()
        except Exception:
            pass


def build_evidence_bundle(
    *,
    case_id: str,
    sanitized_images: List[Dict[str, Any]],
    labels: List[str],
    extracted_text: str,
    analysis: Dict[str, Any],
    reverse_hits: List[Dict[str, Any]] | None,
    forensics: Dict[str, Any] | None = None,
    ocr: Dict[str, Any] | None = None,
    supply_chain: Dict[str, Any] | None = None,
    provider: str,
    model: str,
    processing_time_ms: int | None,
    sanitize_time_ms: int | None,
    fraud: Dict[str, Any] | None,
    trust: Dict[str, Any] | None,
    issue_type: str | None,
    description: str | None,
) -> Dict[str, Any]:
    serial = _extract_serial(extracted_text or "")
    ocr = ocr or {}
    # If callers passed a `ForensicsResult` dataclass, convert to dict
    if ForensicsResult is not None and isinstance(forensics, ForensicsResult):
        try:
            # shallow convert dataclass to dict-like structure
            forensics = {
                "manipulation_score": getattr(forensics, "manipulation_score", None),
                "splice_score": getattr(forensics, "splice_score", None),
                "copy_move_score": getattr(forensics, "copy_move_score", None),
                "double_compress_score": getattr(forensics, "double_compress_score", None),
                "blur_score": getattr(forensics, "blur_score", None),
                "metadata_flags": getattr(forensics, "metadata_flags", []),
                "masks": getattr(forensics, "masks", {}),
                "hashes": getattr(forensics, "hashes", {}),
                "explanations": getattr(forensics, "explanations", []),
                "details": getattr(forensics, "details", {}),
            }
        except Exception:
            forensics = {}
    # If callers didn't pass a dedicated `forensics` object, try to extract it
    # from the richer `analysis` dict (tier2 outputs, cv_tier2, etc.) to ensure
    # evidence masks, details and verdicts are persisted even when callers
    # only forwarded the general analysis payload.
    if not forensics:
        try:
            # candidate locations where forensics may live
            if isinstance(analysis, dict):
                forensics = analysis.get("forensics") or analysis.get("cv_tier2") or (analysis.get("tier2") or {}).get("forensics") or {}
        except Exception:
            forensics = {}
    forensics = forensics or {}
    supply_chain = supply_chain or {}
    ct_hashes = []
    capture_metadata = []
    for img in sanitized_images or []:
        ct_hashes.append(img.get("sha256"))
        capture_metadata.append({
            "mime": img.get("mime"),
            "size": img.get("size"),
            "sha256": img.get("sha256"),
            "phash": img.get("phash"),
        })
    bundle = {
        "case_id": case_id,
        "ct_hashes": [h for h in ct_hashes if h],
        "capture_metadata": capture_metadata,
        "forensics": forensics or {
            "ela_score": None,
            "splice_likelihood": None,
            "recompression_indicators": None,
        },
        # Include raw evidence artifacts (masks, details) when present in analysis
        "evidence_artifacts": (forensics.get("evidence") if isinstance(forensics, dict) and forensics.get("evidence") else None),
        # Include final decision/verdict if provided by analysis
        "verdict": (forensics.get("verdict") if isinstance(forensics, dict) and forensics.get("verdict") else None),
        "ocr_extract": {
            "text": ocr.get("raw_ocr") or extracted_text or "",
            "serial_number": ocr.get("serial") or serial,
            "confidence": float(ocr.get("confidence") or analysis.get("confidence") or 0.0),
            "bounding_boxes": ocr.get("bounding_boxes") or [],
            "alternatives": ocr.get("alternatives") or [],
        },
        "perceptual_hash": [img.get("phash") for img in sanitized_images or [] if img.get("phash")],
        "match_results": reverse_hits or [],
        "decision_log": {
            "model_version": model,
            "provider": provider,
            "processing_time_ms": int(processing_time_ms or 0),
            "sanitize_time_ms": int(sanitize_time_ms or 0),
            "analysis": {
                "severity": analysis.get("severity"),
                "confidence": analysis.get("confidence"),
                "damage_type": analysis.get("damage_type"),
                "damage_location": analysis.get("component") or analysis.get("location"),
            },
        },
        "human_review": {
            "status": "pending",
            "reviewer_id": None,
            "rationale": None,
        },
        "fraud": fraud or {},
        "trust": trust or {},
        "issue_type": issue_type,
        "description": description,
        "labels": labels or [],
        "supply_chain": supply_chain or {},
    }
    return bundle


def persist_evidence_bundle(case_id: str, bundle: Dict[str, Any]) -> Optional[str]:
    evidence_id = __import__("uuid").uuid4().hex
    payload = json.dumps(bundle or {})
    try:
        with db_session() as db:
            db.execute(
                """
                INSERT INTO evidence_bundles (
                  id, case_id, bundle_json, created_at
                ) VALUES (
                  :id, :case_id, :bundle_json, CURRENT_TIMESTAMP
                )
                """,
                {"id": evidence_id, "case_id": case_id, "bundle_json": payload},
            )
            db.commit()
        return evidence_id
    except Exception:
        return None


def get_evidence_bundle(case_id: str) -> Optional[Dict[str, Any]]:
    try:
        with db_session() as db:
            row = db.execute(
                """
                SELECT bundle_json FROM evidence_bundles
                WHERE case_id = :case_id
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {"case_id": case_id},
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0] or "{}")
    except Exception:
        return None
