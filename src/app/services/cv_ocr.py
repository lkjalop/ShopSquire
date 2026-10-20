from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Dict, List

from src.app.services.ocr_embedded import extract_embedded_text


def _ocr_timeout_sec() -> int | None:
    try:
        v = os.getenv("CV_OCR_TIMEOUT_SEC")
        if v is None or str(v).strip() == "":
            return 5
        sec = int(float(str(v).strip()))
        if sec <= 0:
            return None
        return min(sec, 60)
    except Exception:
        return None


def _embedded_ocr(image_bytes: bytes) -> Dict[str, Any]:
    text = extract_embedded_text(image_bytes)
    if not text:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": None, "provider": "embedded"}
    # Provide synthetic "boxes" so downstream heuristics (e.g., document detection)
    # can still work in tests without a heavyweight OCR engine.
    import re

    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", (text or "")) if t.strip()]
    boxes = [{"text": t.strip(), "conf": 99.0, "left": 0, "top": 0, "width": 0, "height": 0} for t in tokens[:96]]
    return {"text": text[:2000], "confidence": 0.95, "boxes": boxes, "provider": "embedded"}


def _annotate_degradation(out: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(out or {})
    txt = str(payload.get("text") or "").strip()
    err = str(payload.get("error") or "").strip()
    degraded = bool((not txt) and err)
    payload["degraded"] = degraded
    payload["degradation_reason"] = err[:200] if degraded else None
    return payload


def _tesseract_ocr(image_bytes: bytes) -> Dict[str, Any]:
    try:
        from PIL import Image
        import pytesseract  # type: ignore
    except Exception as exc:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": str(exc), "provider": "tesseract"}
    try:
        # Windows installs often aren't on PATH; allow explicit configuration.
        cmd = os.getenv("TESSERACT_CMD") or os.getenv("TESSERACT_PATH")
        if not cmd:
            default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.name == "nt" and os.path.exists(default):
                cmd = default
        if cmd and os.path.exists(cmd):
            pytesseract.pytesseract.tesseract_cmd = cmd
    except Exception:
        pass
    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception as exc:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": str(exc), "provider": "tesseract"}
    timeout = _ocr_timeout_sec()
    boxes: List[Dict[str, Any]] = []
    try:
        if timeout is not None:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, timeout=timeout)
        else:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        n = len(data.get("text", []))
        for i in range(n):
            if not (data.get("text", [""])[i] or "").strip():
                continue
            conf = float(data.get("conf", [0])[i])
            boxes.append(
                {
                    "text": data.get("text", [""])[i],
                    "conf": conf,
                    "left": int(data.get("left", [0])[i]),
                    "top": int(data.get("top", [0])[i]),
                    "width": int(data.get("width", [0])[i]),
                    "height": int(data.get("height", [0])[i]),
                }
            )
    except Exception:
        return {
            "text": "", "confidence": 0.0, "boxes": [],
            "error": "ocr_failed_or_timed_out", "provider": "tesseract",
        }
    # image_to_data already invokes Tesseract and returns every recognized token.
    # Reconstructing text from it avoids launching a second native OCR process via
    # image_to_string, which previously doubled both latency and teardown exposure.
    text = " ".join(str(box.get("text") or "").strip() for box in boxes).strip()
    confs = [b.get("conf") for b in boxes if isinstance(b.get("conf"), (int, float))]
    confidence = max(0.0, min(1.0, (sum(confs) / max(len(confs), 1)) / 100.0)) if confs else 0.4
    return {"text": text[:2000], "confidence": confidence, "boxes": boxes, "provider": "tesseract"}


def _paddle_ocr(image_bytes: bytes) -> Dict[str, Any]:
    from src.app.services.paddle_model_assets import local_paddle_models, PaddleAssetError
    try:
        models = local_paddle_models()
    except PaddleAssetError as exc:
        return _paddle_error(str(exc))
    try:
        import math
        import numpy as np
        from paddleocr import PaddleOCR  # type: ignore
        from PIL import Image
        with Image.open(BytesIO(image_bytes)) as source:
            if source.width * source.height > 16_000_000:
                return _paddle_error('paddle_image_too_large')
            with source.convert('RGB') as rgb:
                image = np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])
        # Paddle 3.3's oneDNN path rejects DoubleAttribute arrays in the pinned
        # OCRv5 graph. The plain CPU executor is verified on Windows and Linux.
        ocr = PaddleOCR(**models, device='cpu', cpu_threads=1, enable_mkldnn=False,
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False)
        lines, boxes, scores = [], [], []
        for result in ocr.predict(image):
            row = result.json if hasattr(result, 'json') else result
            if isinstance(row, str):
                import json
                row = json.loads(row)
            row = row.get('res', row)
            texts, confidence = row['rec_texts'], list(row['rec_scores'])
            polygons = row['rec_polys']
            if hasattr(polygons, 'tolist'):
                polygons = polygons.tolist()
            if len(texts) != len(confidence) or len(texts) != len(polygons):
                return _paddle_error('paddle_result_invalid')
            for text, score, polygon in zip(texts[:96], confidence[:96], polygons[:96]):
                score = float(score)
                if not isinstance(text, str) or not math.isfinite(score) or not 0 <= score <= 1:
                    return _paddle_error('paddle_result_invalid')
                if (not isinstance(polygon, (list, tuple)) or len(polygon) != 4
                        or any(not isinstance(point, (list, tuple)) or len(point) != 2
                               or any(isinstance(value, bool) or not math.isfinite(float(value))
                                      or abs(float(value)) > image.shape[1 - axis] * 2 + 16
                                      for axis, value in enumerate(point)) for point in polygon)):
                    return _paddle_error('paddle_result_invalid')
                lines.append(text[:2000])
                scores.append(score)
                boxes.append({'text': text[:2000], 'conf': score, 'box': polygon})
            break  # A single uploaded image has one result page.
        return {'text': ' '.join(lines)[:2000], 'confidence': sum(scores) / len(scores) if scores else 0.0,
                'boxes': boxes, 'provider': 'paddle'}
    except Exception:
        return _paddle_error('paddle_ocr_failed')


def _paddle_error(reason):
    return {'text': '', 'confidence': 0.0, 'boxes': [], 'error': reason, 'provider': 'paddle'}


def _paddle_ocr_b64(image_b64: str):
    """Top-level disposable worker entry; SDK progress cannot corrupt its JSON."""
    import base64
    import contextlib
    import sys
    # Native inference libraries may write directly to descriptor 1. Keep both
    # their progress and Python prints off the worker's JSON protocol channel.
    sys.stdout.flush()
    saved_stdout = os.dup(1)
    try:
        os.dup2(2, 1)
        with contextlib.redirect_stdout(sys.stderr):
            return _paddle_ocr(base64.b64decode(image_b64, validate=True))
    finally:
        sys.stderr.flush()
        os.dup2(saved_stdout, 1)
        os.close(saved_stdout)


from threading import BoundedSemaphore
_PADDLE_WORKERS = BoundedSemaphore(1)


def _isolated_paddle_ocr(image_bytes):
    import base64
    import math
    from src.app.services.media_process_isolation import run_isolated_media_call
    if len(image_bytes) > 8 * 1024 * 1024:
        return _paddle_error('paddle_image_too_large')
    if not os.getenv('CV_PADDLE_MODEL_MANIFEST'):
        return _paddle_error('paddle_models_not_enrolled')
    if not _PADDLE_WORKERS.acquire(timeout=0.05):
        return _paddle_error('paddle_worker_busy')
    try:
        try:
            timeout = float(os.getenv('CV_PADDLE_TIMEOUT_SEC', '20'))
            timeout = min(60.0, max(1.0, timeout)) if math.isfinite(timeout) else 20.0
        except ValueError:
            timeout = 20.0
        try:
            result = run_isolated_media_call(module_name=__name__, function_name='_paddle_ocr_b64',
                kwargs={'image_b64': base64.b64encode(image_bytes).decode('ascii')}, timeout_s=timeout,
                worker_env={'CUDA_VISIBLE_DEVICES': '-1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                    'OPENBLAS_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1',
                    'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK': 'True', 'HF_HUB_OFFLINE': '1',
                    'TRANSFORMERS_OFFLINE': '1', 'MEDIA_ISOLATE_MEMORY_MB': '4096',
                    'MEDIA_ISOLATE_CPU_SECONDS': '20'})
        except (OSError, ValueError, TypeError):
            return _paddle_error('paddle_worker_failed')
        if result.status == 'completed' and isinstance(result.value, dict):
            return result.value
        return _paddle_error('paddle_ocr_timed_out' if result.status == 'timed_out' else 'paddle_worker_failed')
    finally:
        _PADDLE_WORKERS.release()


def _glm_ocr(image_bytes: bytes) -> Dict[str, Any]:
    """OCR via an artifact-bound local model; no cloud fallback is permitted."""
    import base64
    try:
        from src.app.services.local_model_roles import configured_digest, execute_local_model_role
        from src.app.services.model_transports import make_ollama_generate_transport

        model = os.getenv("OLLAMA_GLM_OCR_MODEL", "glm-ocr:latest")
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        timeout = _ocr_timeout_sec() or 30
        text = execute_local_model_role(
            "Extract all text from this image. Output only the extracted text.",
            role="image_ocr",
            purpose="buyer_uploaded_image_text_extraction",
            prompt_id="image-ocr-v1",
            model=model,
            digest=configured_digest("CV_OCR_MODEL_DIGEST"),
            timeout_s=float(timeout),
            max_output_tokens=1_024,
            transport=make_ollama_generate_transport(images=[img_b64]),
        ).strip()
        return {"text": text[:2000], "confidence": 0.85, "boxes": [], "provider": "glm-ocr"}
    except Exception as exc:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": str(exc), "provider": "glm-ocr"}


def extract_text(image_bytes: bytes, provider: str | None = None, fallback: str | None = None) -> Dict[str, Any]:
    # An explicit, policy-selected provider belongs to the caller and must win.
    # The environment is only the default. Reversing this precedence caused the
    # bounded screenshot path to silently use GPU-hosted OCR and time out.
    provider = (provider or os.getenv("CV_OCR_PROVIDER") or "tesseract").lower()
    if provider in ("disabled", "none", "off"):
        return _annotate_degradation({"text": "", "confidence": 0.0, "boxes": [], "error": None, "provider": "disabled"})
    if provider in ("glm-ocr", "glm_ocr", "ollama-ocr"):
        out = _glm_ocr(image_bytes)
        if out.get("text") or not fallback:
            return _annotate_degradation(out)
        return _annotate_degradation(_embedded_ocr(image_bytes))
    if provider == "paddle":
        out = _isolated_paddle_ocr(image_bytes)
        if out.get("text") or not fallback:
            return _annotate_degradation(out)
        return _annotate_degradation(_tesseract_ocr(image_bytes))
    if provider == "embedded":
        out = _embedded_ocr(image_bytes)
        if out.get("text") or not fallback:
            return _annotate_degradation(out)
        return extract_text(image_bytes, provider=fallback, fallback=None)
    if provider == "tesseract":
        return _annotate_degradation(_tesseract_ocr(image_bytes))
    return _annotate_degradation(_tesseract_ocr(image_bytes))
