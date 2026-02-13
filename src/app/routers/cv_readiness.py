from __future__ import annotations

import os
import pathlib
import json
from fastapi import APIRouter, Depends
from typing import Any, Dict

from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER
from src.app.models.db import db_session
from sqlalchemy import text as sql_text


router = APIRouter(prefix="/api/v1/admin/cv", tags=["admin-cv"])


def _has_import(name: str) -> tuple[bool, str | None]:
    try:
        __import__(name)
        return True, None
    except Exception as exc:
        return False, str(exc)


def _safe_stat(path: str | None) -> Dict[str, Any]:
    if not path:
        return {"configured": False, "exists": False}
    try:
        p = pathlib.Path(path)
        return {
            "configured": True,
            "path": str(p),
            "exists": bool(p.exists()),
            "is_file": bool(p.is_file()) if p.exists() else False,
            "size_bytes": int(p.stat().st_size) if p.exists() and p.is_file() else None,
        }
    except Exception:
        return {"configured": True, "path": path, "exists": False}


def _list_json_files(dir_path: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"dir": dir_path, "exists": False, "files": []}
    try:
        p = pathlib.Path(dir_path)
        out["exists"] = bool(p.exists() and p.is_dir())
        if not out["exists"]:
            return out
        out["files"] = sorted([f.name for f in p.glob("*.json") if f.is_file()])
        return out
    except Exception:
        return out


@router.get("/readiness")
def readiness(role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Report which CV dependencies/configs are actually active.

    This is intentionally introspective (no heavy model warmups).
    """
    deps = {}
    for mod in ("PIL", "numpy", "pytesseract", "cv2"):
        ok, err = _has_import(mod)
        deps[mod] = {"ok": ok, "error": err}
    ok_ultra, err_ultra = _has_import("ultralytics")
    deps["ultralytics"] = {"ok": ok_ultra, "error": err_ultra}
    ok_paddle, err_paddle = _has_import("paddleocr")
    deps["paddleocr"] = {"ok": ok_paddle, "error": err_paddle}

    paths: Dict[str, str | None] = {
        "CV_DAMAGE_YOLO_MODEL": os.getenv("CV_DAMAGE_YOLO_MODEL"),
        "CV_OBJECT_MODEL": os.getenv("CV_OBJECT_MODEL"),
        "CV_ROI_MODEL": os.getenv("CV_ROI_MODEL"),
        "CV_CLIP_MODEL": os.getenv("CV_CLIP_MODEL"),
    }
    files: Dict[str, Any] = {}
    for k, p in paths.items():
        files[k] = _safe_stat(p)

    cfg = {
        "CV_OCR_PROVIDER": os.getenv("CV_OCR_PROVIDER"),
        "CV_OCR_FALLBACK": os.getenv("CV_OCR_FALLBACK"),
        "CV_MODEL_PACK": os.getenv("CV_MODEL_PACK"),
        "CV_OCR_TIMEOUT_SEC": os.getenv("CV_OCR_TIMEOUT_SEC"),
        "CV_MAX_IMAGES": os.getenv("CV_MAX_IMAGES"),
        "CV_MAX_IMAGE_BYTES": os.getenv("CV_MAX_IMAGE_BYTES"),
        "RETURNS_CV_TIER2_ENABLED": os.getenv("RETURNS_CV_TIER2_ENABLED"),
        "RETURNS_CV_TIER2_MAX_IMAGES": os.getenv("RETURNS_CV_TIER2_MAX_IMAGES"),
        "TIER0_RULES_ENABLED": os.getenv("TIER0_RULES_ENABLED"),
        "CV_CONFIG_DIR": os.getenv("CV_CONFIG_DIR", "config/cv"),
        "VERTICALS_DIR": os.getenv("VERTICALS_DIR", "config/verticals"),
    }
    packs = {
        "cv_config": _list_json_files(str(cfg.get("CV_CONFIG_DIR") or "config/cv")),
        "verticals": _list_json_files(str(cfg.get("VERTICALS_DIR") or "config/verticals")),
    }

    # Lightweight feature summary (no model execution).
    features = {
        "roi_crop_ocr_pipeline": True,
        "tier2_forensics": True,
        "ultralytics_available": bool(deps.get("ultralytics", {}).get("ok")),
        "ocr_provider": cfg.get("CV_OCR_PROVIDER") or "auto",
    }
    return {"deps": deps, "models": files, "config": cfg, "packs": packs, "features": features}


@router.get("/incidents/recent")
def recent_incidents(
    limit: int = 50,
    sku: str | None = None,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Recent CV-related incidents derived from persisted `evidence_bundles`.

    This is intentionally computed from stored evidence JSON so it works without
    new schema, and is suitable for MVP admin drilldowns.
    """
    lim = max(1, min(int(limit or 50), 500))
    out = []
    try:
        with db_session() as db:
            rows = db.execute(
                sql_text(
                    "SELECT id, case_id, bundle_json, created_at "
                    "FROM evidence_bundles "
                    "ORDER BY created_at DESC "
                    "LIMIT :lim"
                ),
                {"lim": lim},
            ).fetchall()
    except Exception:
        rows = []

    for r in rows or []:
        try:
            evidence_id = r[0]
            case_id = r[1]
            bundle = json.loads(r[2] or "{}") if isinstance(r[2], str) else (r[2] or {})
            created_at = r[3]
            b_sku = str(bundle.get("sku") or "") if isinstance(bundle, dict) else ""
            if sku and b_sku and str(b_sku) != str(sku):
                continue
            cv = (bundle.get("cv") or {}) if isinstance(bundle, dict) else {}
            fields = (cv.get("fields") or {}) if isinstance(cv, dict) else {}
            pack_id = cv.get("pack_id") if isinstance(cv, dict) else None
            evidence_tags = (bundle.get("evidence_tags") if isinstance(bundle, dict) else None) or (cv.get("evidence_tags") if isinstance(cv, dict) else None) or []
            if not isinstance(evidence_tags, list):
                evidence_tags = []
            manipulation_score = None
            try:
                # Best-effort extraction from Tier2 forensics when present
                forensics = None
                if isinstance(bundle, dict):
                    forensics = bundle.get("forensics") or ((bundle.get("tier2") or {}).get("forensics") if isinstance(bundle.get("tier2"), dict) else None)
                if isinstance(forensics, dict):
                    manipulation_score = forensics.get("manipulation_score")
            except Exception:
                manipulation_score = None
            out.append(
                {
                    "evidence_id": evidence_id,
                    "case_id": case_id,
                    "sku": b_sku or None,
                    "created_at": created_at,
                    "pack_id": pack_id,
                    "cv_fields": {"order_id": fields.get("order_id"), "serial": fields.get("serial")},
                    "evidence_tags": evidence_tags[:20],
                    "manipulation_score": manipulation_score,
                }
            )
        except Exception:
            continue
    return {"items": out, "limit": lim, "sku": sku}


@router.get("/incidents/by_sku")
def incidents_by_sku(
    limit: int = 500,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Aggregate recent evidence bundles by SKU for drilldowns."""
    lim = max(1, min(int(limit or 500), 5000))
    counts: Dict[str, Dict[str, Any]] = {}
    try:
        with db_session() as db:
            rows = db.execute(
                sql_text(
                    "SELECT bundle_json, created_at "
                    "FROM evidence_bundles "
                    "ORDER BY created_at DESC "
                    "LIMIT :lim"
                ),
                {"lim": lim},
            ).fetchall()
    except Exception:
        rows = []

    for r in rows or []:
        try:
            bundle = json.loads(r[0] or "{}") if isinstance(r[0], str) else (r[0] or {})
            if not isinstance(bundle, dict):
                continue
            sku_val = str(bundle.get("sku") or "").strip()
            if not sku_val:
                sku_val = "unknown"
            cv = bundle.get("cv") or {}
            pack_id = cv.get("pack_id") if isinstance(cv, dict) else None
            counts.setdefault(sku_val, {"sku": sku_val, "count": 0, "pack_ids": set(), "last_seen": None})
            counts[sku_val]["count"] += 1
            if pack_id:
                counts[sku_val]["pack_ids"].add(str(pack_id))
            counts[sku_val]["last_seen"] = counts[sku_val]["last_seen"] or r[1]
        except Exception:
            continue

    items = []
    for _, v in counts.items():
        try:
            v["pack_ids"] = sorted(list(v.get("pack_ids") or []))
        except Exception:
            v["pack_ids"] = []
        items.append(v)
    items.sort(key=lambda x: int(x.get("count") or 0), reverse=True)
    return {"items": items[:200], "scanned": lim}
