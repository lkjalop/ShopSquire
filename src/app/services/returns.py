import os
import io
import json
import uuid
import hashlib
from typing import List, Dict, Any, Tuple
import re
from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.services.ocr_embedded import extract_embedded_text

try:
    from PIL import Image
    import pytesseract
    try:
        import imagehash
    except Exception:
        imagehash = None  # type: ignore
except Exception:
    Image = None  # type: ignore
    pytesseract = None  # type: ignore
    imagehash = None  # type: ignore


def _ensure_returns_dir():
    d = os.path.join("tmp", "returns")
    os.makedirs(d, exist_ok=True)
    return d


def image_sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def image_phash_hex(b: bytes) -> str:
    """Return a perceptual hash hex string when imagehash is available.

    Falls back to sha256 hex if imagehash is not installed.
    """
    if Image is None:
        return image_sha256_bytes(b)
    try:
        img = Image.open(io.BytesIO(b)).convert("L")
        if imagehash is not None:
            ph = imagehash.phash(img)
            # imagehash objects support __str__ which is hex-like
            return str(ph)
        # fallback: use sha256 as a stable surrogate
        return image_sha256_bytes(b)
    except Exception:
        return image_sha256_bytes(b)


def ocr_image_bytes(b: bytes) -> str:
    # Test-fixture friendly: allow OCR-like behavior without a system tesseract binary.
    try:
        embedded = extract_embedded_text(b)
        if embedded:
            return embedded
    except Exception:
        pass
    try:
        from src.app.services.cv_ocr import extract_text

        out = extract_text(b, provider=os.getenv("CV_OCR_PROVIDER") or "tesseract", fallback=os.getenv("CV_OCR_FALLBACK"))
        return str(out.get("text") or "")
    except Exception:
        if Image is None or pytesseract is None:
            # Fallback: return empty string when OCR dependencies missing
            return ""
        try:
            img = Image.open(io.BytesIO(b))
            text = pytesseract.image_to_string(img)
            return text
        except Exception:
            return ""


_SKU_TOKEN_RE = re.compile(r"[A-Z0-9]+", re.IGNORECASE)


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _sku_tokens(sku: str) -> List[str]:
    tokens = [t for t in _SKU_TOKEN_RE.findall(sku or "") if len(t) >= 3]
    return list(dict.fromkeys(tokens))


def _distinctive_sku_tokens(sku: str) -> List[str]:
    # Avoid "passing" SKU match due to generic category prefixes like PHONE/LAPTOP.
    stop = {
        "sku",
        "sn",
        "serial",
        "order",
        "invoice",
        "receipt",
        "total",
        "usd",
        "phone",
        "laptop",
        "tablet",
        "monitor",
        "device",
    }
    out: List[str] = []
    for t in _sku_tokens(sku):
        if t.lower() in stop:
            continue
        out.append(t)
    return out


def _detect_category_from_sku(sku: str) -> str | None:
    s = (sku or "").lower()
    if any(k in s for k in ["laptop", "notebook", "ultrabook", "xps", "macbook"]):
        return "laptop"
    if any(k in s for k in ["phone", "iphone", "pixel", "galaxy"]):
        return "phone"
    if any(k in s for k in ["tablet", "ipad", "surface"]):
        return "tablet"
    if any(k in s for k in ["monitor", "display", "screen"]):
        return "monitor"
    return None


def _detect_category_from_text(text: str) -> str | None:
    t = (text or "").lower()
    if any(k in t for k in ["laptop", "notebook", "ultrabook", "macbook", "xps"]):
        return "laptop"
    if any(k in t for k in ["phone", "iphone", "pixel", "galaxy"]):
        return "phone"
    if any(k in t for k in ["tablet", "ipad", "surface"]):
        return "tablet"
    if any(k in t for k in ["monitor", "display", "screen"]):
        return "monitor"
    if any(k in t for k in ["receipt", "invoice", "order"]):
        return "receipt"
    return None


def _ocr_category_mismatch(sku: str, ocr_text: str) -> tuple[bool, str | None, str | None]:
    expected = _detect_category_from_sku(sku)
    detected = _detect_category_from_text(ocr_text)
    if expected and detected and expected != detected:
        return True, expected, detected
    return False, expected, detected


def _ocr_sku_mismatch(sku: str, ocr_text: str) -> bool:
    if not sku or not ocr_text:
        return False
    ocr_norm = _normalize_text(ocr_text)
    # Exact sku match or token match qualifies as OK.
    if _normalize_text(sku) in ocr_norm:
        return False
    # Require at least one *distinctive* token to appear; otherwise treat as mismatch.
    distinct = _distinctive_sku_tokens(sku)
    if not distinct:
        # If there's nothing distinctive, fall back to previous behavior.
        for token in _sku_tokens(sku):
            if token.lower() in ocr_norm:
                return False
        return True
    for token in distinct:
        if token.lower() in ocr_norm:
            return False
    return True


def check_image_reuse(hash_hex: str) -> bool:
    # Check existing fraud_image_hashes table for the phash
    try:
        with db_session() as db:
            res = db.execute(sql_text("SELECT 1 FROM fraud_image_hashes WHERE phash = :p"), {"p": hash_hex}).scalar()
            return bool(res)
    except Exception:
        return False


def capture_evidence(
    sku: str,
    uid: str | None,
    images: List[Tuple[str, bytes]],
    description: str | None = None,
    *,
    vertical_pack_id: str | None = None,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """Capture images + OCR + image-hash checks and persist an evidence package on disk.

    images: list of (filename, bytes)
    Returns an evidence package dict with id and paths.
    """
    _ensure_returns_dir()
    eid = str(uuid.uuid4())
    pkg = {
        "evidence_id": eid,
        "sku": sku,
        "uid": uid,
        "description": description or "",
        "images": [],
        "ocr": {},
        "fraud_signals": [],
    }
    try:
        if tenant_id is not None:
            pkg["tenant_id"] = str(tenant_id)
    except Exception:
        pass

    # Run ROI→crop→OCR→postprocess once (best-effort) so evidence includes structured CV/OCR signals.
    safe_images: List[Tuple[str, bytes]] = []
    # Apply caps to avoid runaway memory/CPU from huge uploads.
    try:
        max_images = int(float(os.getenv("CV_MAX_IMAGES", "6") or 6))
    except Exception:
        max_images = 6
    max_images = max(1, min(50, max_images))
    try:
        max_bytes = int(float(os.getenv("CV_MAX_IMAGE_BYTES", "5000000") or 5000000))
    except Exception:
        max_bytes = 5_000_000
    max_bytes = max(10_000, min(50_000_000, max_bytes))
    for idx, (fname, b) in enumerate(images or []):
        if idx >= max_images:
            break
        b = b or b""
        if len(b) > max_bytes:
            continue
        safe_images.append((f"img_{idx}_{(fname or 'upload.jpg')}", b))
    cv_result: Dict[str, Any] | None = None
    try:
        from src.app.policy.vertical_pack import load_vertical_pack
        from src.app.cv.cv_pipeline import run_pipeline
        from src.app.feature_flags import get_flag
        from src.app.services.cv_model_pack import get_model_pack

        pack = load_vertical_pack(vertical_pack_id or "electronics")

        model_pack = get_model_pack(None, tenant_id=tenant_id)
        detector_cfg = (model_pack.get("detector") or {}) if isinstance(model_pack.get("detector"), dict) else {}
        ocr_cfg = (model_pack.get("ocr") or {}) if isinstance(model_pack.get("ocr"), dict) else {}

        roi_model_path = None
        try:
            if get_flag("YOLO_ROI_ENABLED", True):
                roi_model_path = detector_cfg.get("model")
        except Exception:
            roi_model_path = detector_cfg.get("model")
        try:
            forced = os.getenv("CV_DETECTOR_MODEL")
            if forced and str(forced).strip():
                roi_model_path = str(forced).strip()
        except Exception:
            pass

        ocr_provider = None
        try:
            ocr_provider = ocr_cfg.get("provider")
        except Exception:
            ocr_provider = None

        cv_result = run_pipeline(safe_images, pack=pack, roi_model_path=roi_model_path, ocr_provider=ocr_provider)
    except Exception:
        cv_result = None
    if cv_result is not None:
        pkg["cv"] = cv_result

    # Optional Tier2 forensics/verdict (off by default).
    try:
        tier2_enabled = str(os.getenv("RETURNS_CV_TIER2_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        tier2_enabled = False
    if tier2_enabled and safe_images:
        try:
            from src.app.services.cv_tier2_pipeline import run_tier2
            from src.app.services.cv_model_pack import get_model_pack

            try:
                max_t2 = int(float(os.getenv("RETURNS_CV_TIER2_MAX_IMAGES", "1") or 1))
            except Exception:
                max_t2 = 1
            max_t2 = max(1, min(5, max_t2))
            pack_id = (get_model_pack(None, tenant_id=tenant_id) or {}).get("id")
            t2_images = []
            for fname, b in safe_images[:max_t2]:
                t2 = run_tier2(b, meta={"filename": fname, "source": "returns"}, pack_id=pack_id)
                t2_images.append(
                    {
                        "filename": fname,
                        "evidence_tags": t2.get("evidence_tags") or [],
                        "verdict": t2.get("verdict"),
                        "forensics": (t2.get("forensics") or {}),
                        "tier2_summary": {
                            "model_pack": t2.get("model_pack"),
                            "manipulation_score": (t2.get("forensics") or {}).get("manipulation_score"),
                        },
                    }
                )
            pkg["cv_tier2"] = {"pack_id": pack_id, "images": t2_images}
        except Exception:
            pass

    cv_best_text: Dict[str, str] = {}
    try:
        for img in (cv_result or {}).get("images") or []:
            fn = img.get("filename") if isinstance(img, dict) else None
            best = (img.get("ocr") or {}).get("best_text") if isinstance(img, dict) else None
            if fn and isinstance(best, str) and best.strip():
                cv_best_text[str(fn)] = best.strip()
    except Exception:
        cv_best_text = {}
    base = os.path.join("tmp", "returns", eid)
    os.makedirs(base, exist_ok=True)
    for idx, (safe_name, b) in enumerate(safe_images):
        path = os.path.join(base, safe_name)
        try:
            with open(path, "wb") as f:
                f.write(b)
        except Exception:
            # best-effort write
            pass
        sha256 = image_sha256_bytes(b)
        phash = image_phash_hex(b)
        reused = check_image_reuse(phash)
        reverse_lookup = {}
        try:
            from src.app.services.reverse_image_search import ReverseImageSearch

            reverse_lookup = ReverseImageSearch().external_lookup(phash=phash, sha256=sha256, sku=sku)
        except Exception:
            reverse_lookup = {}
        # The full-image pass is a necessary fallback when ROI OCR finds no
        # text (receipts and fault codes are often outside detected regions).
        ocr_text = cv_best_text.get(safe_name) or ocr_image_bytes(b)
        pkg["images"].append(
            {
                "filename": safe_name,
                "path": path,
                "phash": phash,
                "sha256": sha256,
                "reused": reused,
                "reverse_image": reverse_lookup,
            }
        )
        if ocr_text:
            pkg["ocr"][safe_name] = ocr_text
            # OCR-based mismatch heuristics (best-effort)
            mismatch, expected, detected = _ocr_category_mismatch(sku, ocr_text)
            if mismatch:
                pkg["fraud_signals"].append(
                    {
                        "type": "ocr_category_mismatch",
                        "expected": expected,
                        "detected": detected,
                        "filename": safe_name,
                    }
                )
            elif _ocr_sku_mismatch(sku, ocr_text):
                pkg["fraud_signals"].append(
                    {
                        "type": "ocr_sku_mismatch",
                        "sku": sku,
                        "filename": safe_name,
                    }
                )
        if reused:
            pkg["fraud_signals"].append({"type": "image_reuse", "phash": phash, "filename": safe_name})
        try:
            manu_hits = reverse_lookup.get("manufacturer_matches") if isinstance(reverse_lookup, dict) else []
            fraud_hits = reverse_lookup.get("fraud_db_matches") if isinstance(reverse_lookup, dict) else []
            if isinstance(manu_hits, list) and manu_hits:
                pkg["fraud_signals"].append(
                    {
                        "type": "reverse_image_manufacturer_match",
                        "count": len(manu_hits),
                        "filename": safe_name,
                    }
                )
            risky_hits = [h for h in (fraud_hits or []) if isinstance(h, dict) and bool(h.get("fraud"))]
            if risky_hits:
                pkg["fraud_signals"].append(
                    {
                        "type": "reverse_image_fraud_db_hit",
                        "count": len(risky_hits),
                        "filename": safe_name,
                    }
                )
        except Exception:
            pass

    # Persist package JSON for export
    try:
        with open(os.path.join(base, "package.json"), "w", encoding="utf-8") as pf:
            json.dump(pkg, pf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return pkg


def compute_return_score(pkg: Dict[str, Any]) -> Dict[str, Any]:
    tenant_id = None
    try:
        if pkg.get("tenant_id") is not None:
            tenant_id = str(pkg.get("tenant_id"))
    except Exception:
        tenant_id = None

    cfg: Dict[str, Any] = {}
    try:
        from src.app.rules.config_defaults import fraud_heuristics_defaults

        cfg = fraud_heuristics_defaults(tenant_id=tenant_id)
    except Exception:
        cfg = {}

    base_score = 10.0
    try:
        base_score = float(cfg.get("base_score") or 10.0)
    except Exception:
        base_score = 10.0

    score = base_score
    reasons: List[str] = []
    signals_cfg = cfg.get("signals") if isinstance(cfg.get("signals"), dict) else {}

    for s in pkg.get("fraud_signals", []) or []:
        st = None
        try:
            st = s.get("type")
        except Exception:
            st = None
        if not st:
            continue
        delta = None
        try:
            delta = (signals_cfg.get(str(st)) or {}).get("score_delta")
        except Exception:
            delta = None
        if delta is None:
            # Backward-compatible legacy defaults (keeps demo behavior stable).
            if st == "image_reuse":
                delta = 70
            elif st == "ocr_category_mismatch":
                delta = 30
            elif st == "ocr_sku_mismatch":
                delta = 20
        if delta is not None:
            try:
                score += float(delta)
            except Exception:
                pass
            reasons.append(str(st))

    # If OCR empty for all images, apply config-driven penalty.
    if not pkg.get("ocr"):
        delta = None
        try:
            delta = (signals_cfg.get("no_ocr") or {}).get("score_delta")
        except Exception:
            delta = None
        if delta is None:
            delta = 10
        try:
            score += float(delta)
        except Exception:
            pass
        reasons.append("no_ocr")

    try:
        max_score = float(cfg.get("max_score") or 100.0)
    except Exception:
        max_score = 100.0
    score = min(max_score, score)
    score = max(0.0, score)
    return {"score": float(score), "reasons": reasons, "model": "fraud_heuristics_v1"}


def mark_evidence_as_fraud(evidence_id: str) -> int:
    """Persist image phashes from an evidence package into fraud_image_hashes.

    Returns number of phashes inserted.
    """
    import os
    inserted = 0
    base = os.path.join("tmp", "returns", evidence_id)
    pkgf = os.path.join(base, "package.json")
    try:
        with open(pkgf, "r", encoding="utf-8") as pf:
            pkg = json.load(pf)
    except Exception:
        return 0
    try:
        with db_session() as db:
            for img in pkg.get("images", []):
                phash = img.get("phash")
                if not phash:
                    continue
                try:
                    db.execute(
                        sql_text(
                            "INSERT INTO fraud_image_hashes (phash, first_seen_case_id, times_seen, confirmed_fraud, created_at)"
                            " VALUES (:phash, :case, 1, 1, CURRENT_TIMESTAMP)"
                            " ON CONFLICT (phash) DO UPDATE SET times_seen = fraud_image_hashes.times_seen + 1, confirmed_fraud = 1"
                        ),
                        {"phash": phash, "case": evidence_id},
                    )
                    inserted += 1
                except Exception:
                    pass
            try:
                db.commit()
            except Exception:
                pass
    except Exception:
        return inserted
    return inserted
