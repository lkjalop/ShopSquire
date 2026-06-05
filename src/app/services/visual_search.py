"""Visual similarity search using CLIP embeddings and FAISS.

Productionized behavior:
- lazy dependency loading (CLIP + FAISS)
- durable on-disk index + metadata persistence
- freshness and quality telemetry in status payload
- safe degraded mode when dependencies/index are unavailable
"""
from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_log = logging.getLogger(__name__)

_LOCK = threading.RLock()
_clip_model: Any = None
_faiss_index: Any = None
_product_map: List[Dict[str, Any]] = []
_EMBED_DIM: int = 512
_MODEL_NAME = os.getenv("CLIP_MODEL_NAME", "sentence-transformers/clip-ViT-B-32")
_INDEX_DIR = Path(str(os.getenv("VISUAL_SEARCH_INDEX_DIR", "tmp/visual_search_index") or "tmp/visual_search_index"))
_INDEX_FILE = _INDEX_DIR / "catalog.faiss"
_META_FILE = _INDEX_DIR / "catalog.meta.json"
_DEFAULT_FRESHNESS_MINUTES = int(os.getenv("VISUAL_SEARCH_MAX_AGE_MINUTES", "1440") or 1440)

_state: Dict[str, Any] = {
    "built_at": None,
    "source": None,
    "catalog_size": 0,
    "indexed_count": 0,
    "coverage_ratio": 0.0,
    "quality_score": 0.0,
    "catalog_max_updated_at": None,
    "persisted_index_path": str(_INDEX_FILE),
    "loaded_from_disk": False,
    "last_query_at": None,
    "queries_served": 0,
}


def _utc_now_ts() -> int:
    return int(time.time())


def _load_clip() -> bool:
    global _clip_model
    if _clip_model is not None:
        return True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _clip_model = SentenceTransformer(_MODEL_NAME)
        _log.info("visual_search.clip_model_loaded model=%s", _MODEL_NAME)
        return True
    except Exception as exc:
        _log.warning("visual_search.clip_unavailable: %s", exc)
        return False


def _get_faiss():
    try:
        import faiss  # type: ignore

        return faiss
    except Exception:
        return None


def _ensure_index_dir() -> None:
    _INDEX_DIR.mkdir(parents=True, exist_ok=True)


def _is_index_ready(*, load_model: bool = True) -> bool:
    model_ready = _load_clip() if load_model else (_clip_model is not None)
    return _faiss_index is not None and len(_product_map) > 0 and model_ready and _get_faiss() is not None


def _to_serializable_product(p: Dict[str, Any]) -> Dict[str, Any]:
    specs = p.get("specs") if isinstance(p.get("specs"), dict) else {}
    return {
        "sku": str(p.get("sku") or ""),
        "name": str(p.get("name") or ""),
        "brand": str(p.get("brand") or ""),
        "price_cents": int(p.get("price_cents") or 0),
        "specs": specs,
    }


def _product_text(p: Dict[str, Any]) -> str:
    specs = p.get("specs") if isinstance(p.get("specs"), dict) else {}
    spec_vals = " ".join(str(v) for v in specs.values()) if specs else ""
    text = f"{p.get('name', '')} {p.get('brand', '')} {spec_vals}".strip()
    return text or str(p.get("sku") or "unknown")


def _quality_metrics(products: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    total = float(len(products) or 0)
    if total <= 0:
        return {"coverage_ratio": 0.0, "quality_score": 0.0}
    with_name = sum(1 for p in products if str((p or {}).get("name") or "").strip())
    with_brand = sum(1 for p in products if str((p or {}).get("brand") or "").strip())
    with_specs = sum(1 for p in products if isinstance((p or {}).get("specs"), dict) and len((p or {}).get("specs") or {}) > 0)
    coverage = with_name / total
    quality = ((with_name / total) * 0.5) + ((with_brand / total) * 0.2) + ((with_specs / total) * 0.3)
    return {"coverage_ratio": round(float(coverage), 4), "quality_score": round(float(quality), 4)}


def is_available() -> bool:
    return _load_clip() and _get_faiss() is not None


def status() -> Dict[str, Any]:
    with _LOCK:
        now = _utc_now_ts()
        built_at = int(_state.get("built_at") or 0)
        age_seconds = max(0, now - built_at) if built_at else None
        stale = bool(age_seconds is not None and age_seconds > (_DEFAULT_FRESHNESS_MINUTES * 60))
        faiss_available = _get_faiss() is not None
        model_loaded = _clip_model is not None
        return {
            "available": bool(model_loaded and faiss_available),
            "index_ready": bool(_is_index_ready(load_model=False)),
            "index_size": len(_product_map),
            "embed_dim": int(_EMBED_DIM or 0),
            "model_name": _MODEL_NAME,
            "model_loaded": model_loaded,
            "faiss_available": faiss_available,
            "freshness": {
                "built_at": built_at,
                "age_seconds": age_seconds,
                "stale": stale,
                "max_age_minutes": _DEFAULT_FRESHNESS_MINUTES,
                "catalog_max_updated_at": _state.get("catalog_max_updated_at"),
            },
            "quality": {
                "coverage_ratio": float(_state.get("coverage_ratio") or 0.0),
                "quality_score": float(_state.get("quality_score") or 0.0),
                "catalog_size": int(_state.get("catalog_size") or 0),
                "indexed_count": int(_state.get("indexed_count") or 0),
            },
            "ops": {
                "persisted_index_path": str(_state.get("persisted_index_path") or _INDEX_FILE),
                "meta_path": str(_META_FILE),
                "loaded_from_disk": bool(_state.get("loaded_from_disk")),
                "queries_served": int(_state.get("queries_served") or 0),
                "last_query_at": _state.get("last_query_at"),
                "source": _state.get("source"),
            },
        }


def _persist_index() -> None:
    if _faiss_index is None:
        return
    faiss = _get_faiss()
    if faiss is None:
        return
    _ensure_index_dir()
    meta = {
        "version": 1,
        "model_name": _MODEL_NAME,
        "embed_dim": int(_EMBED_DIM or 0),
        "product_map": [_to_serializable_product(p) for p in _product_map],
        "state": dict(_state),
    }
    faiss.write_index(_faiss_index, str(_INDEX_FILE))
    _META_FILE.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def try_load_persisted_index() -> bool:
    global _faiss_index, _product_map, _EMBED_DIM
    with _LOCK:
        if not is_available():
            return False
        if not _INDEX_FILE.exists() or not _META_FILE.exists():
            return False
        faiss = _get_faiss()
        if faiss is None:
            return False
        try:
            meta = json.loads(_META_FILE.read_text(encoding="utf-8"))
            idx = faiss.read_index(str(_INDEX_FILE))
            pmap = meta.get("product_map") if isinstance(meta.get("product_map"), list) else []
            _faiss_index = idx
            _product_map = [x for x in pmap if isinstance(x, dict)]
            _EMBED_DIM = int(meta.get("embed_dim") or _EMBED_DIM)
            loaded_state = meta.get("state") if isinstance(meta.get("state"), dict) else {}
            _state.update(loaded_state)
            _state["loaded_from_disk"] = True
            _state["persisted_index_path"] = str(_INDEX_FILE)
            return True
        except Exception as exc:
            _log.warning("visual_search.load_persisted_failed: %s", exc)
            return False


def build_index(
    products: Sequence[Dict[str, Any]],
    *,
    persist: bool = True,
    source: str = "manual",
    catalog_max_updated_at: str | None = None,
) -> int:
    global _faiss_index, _product_map, _EMBED_DIM
    with _LOCK:
        if not is_available():
            return 0
        faiss = _get_faiss()
        if faiss is None:
            return 0
        import numpy as np

        valid_products: List[Dict[str, Any]] = []
        texts: List[str] = []
        for p in products or []:
            if not isinstance(p, dict):
                continue
            sku = str(p.get("sku") or "").strip()
            if not sku:
                continue
            clean = _to_serializable_product(p)
            valid_products.append(clean)
            texts.append(_product_text(clean))
        if not texts:
            _faiss_index = None
            _product_map = []
            _state.update(
                {
                    "built_at": _utc_now_ts(),
                    "source": source,
                    "catalog_size": int(len(products or [])),
                    "indexed_count": 0,
                    "coverage_ratio": 0.0,
                    "quality_score": 0.0,
                    "catalog_max_updated_at": catalog_max_updated_at,
                    "loaded_from_disk": False,
                }
            )
            return 0

        emb = _clip_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        emb = np.asarray(emb, dtype="float32")
        _EMBED_DIM = int(emb.shape[1])
        index = faiss.IndexFlatIP(_EMBED_DIM)
        index.add(emb)
        _faiss_index = index
        _product_map = valid_products
        q = _quality_metrics(valid_products)
        _state.update(
            {
                "built_at": _utc_now_ts(),
                "source": source,
                "catalog_size": int(len(products or [])),
                "indexed_count": int(len(valid_products)),
                "coverage_ratio": float(q["coverage_ratio"]),
                "quality_score": float(q["quality_score"]),
                "catalog_max_updated_at": catalog_max_updated_at,
                "loaded_from_disk": False,
                "persisted_index_path": str(_INDEX_FILE),
            }
        )
        if persist:
            try:
                _persist_index()
            except Exception as exc:
                _log.warning("visual_search.persist_failed: %s", exc)
        return len(valid_products)


def search(
    image_bytes: bytes | None = None,
    query_text: str | None = None,
    k: int = 20,
    budget_max: float | None = None,
    budget_min: float | None = None,
    brand: str | None = None,
) -> List[Dict[str, Any]]:
    with _LOCK:
        if not _is_index_ready():
            return []
        import numpy as np

        embedding: Optional[np.ndarray] = None
        if image_bytes:
            try:
                from PIL import Image  # type: ignore

                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                embedding = _clip_model.encode(img, normalize_embeddings=True)
            except Exception as exc:
                _log.warning("visual_search.image_encode_failed: %s", exc)

        if embedding is None and query_text:
            embedding = _clip_model.encode(str(query_text), normalize_embeddings=True)
        if embedding is None:
            return []

        query_vec = np.asarray([embedding], dtype="float32")
        fetch_k = min(int(max(1, k) * 5), int(getattr(_faiss_index, "ntotal", 0) or 0))
        if fetch_k <= 0:
            return []
        scores, indices = _faiss_index.search(query_vec, fetch_k)
        out: List[Dict[str, Any]] = []
        for rank, (score, idx) in enumerate(zip(scores[0], indices[0])):
            if int(idx) < 0 or int(idx) >= len(_product_map):
                continue
            p = _product_map[int(idx)]
            price = int(p.get("price_cents") or 0)
            if budget_max is not None and price > int(float(budget_max) * 100):
                continue
            if budget_min is not None and price < int(float(budget_min) * 100):
                continue
            if brand and str(p.get("brand") or "").strip().lower() != str(brand).strip().lower():
                continue
            out.append({**p, "visual_score": round(float(score), 4), "visual_rank": rank})
            if len(out) >= int(k):
                break
        _state["queries_served"] = int(_state.get("queries_served") or 0) + 1
        _state["last_query_at"] = _utc_now_ts()
        return out
