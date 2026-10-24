from __future__ import annotations

import asyncio
import os
import json
import base64
import hashlib
from typing import Any, Dict, List, Optional, Tuple
import logging
import threading

from src.app.services.local_model_roles import LocalModelFailure

# ── Vision prompt templates (mode-selectable) ──
_TRIAGE_PROMPT = (
    "You are an e-commerce vision assistant. Analyze the provided image and "
    "return a compact JSON object with keys 'labels' (array of lowercase keywords) "
    "and 'text' (any visible serial/receipt text snippets). Use laptop-related labels like "
    "screen, crack, hinge, keyboard, charger when relevant. "
    'Example: {"labels":["screen","crack"],"text":"SN-ABC123"}.'
)

_PRODUCT_IDENTITY_PROMPT = (
    "You are a product identification assistant for an e-commerce platform. "
    "Analyze the provided image and return a compact JSON object with keys: "
    "'brand' (brand name, e.g. Apple, MSI, Lenovo, Dell, HP, Asus, Acer, Samsung, Microsoft, Razer — use null if unknown), "
    "'model' (model name or series if visible, e.g. MacBook Pro 16, MSI GT76, ThinkPad X1 Carbon — use null if unknown), "
    "'category' (e.g. laptop, gaming_laptop, ultrabook, tablet, phone, desktop — use null if unknown), "
    "'labels' (array of 3-8 lowercase product descriptor keywords, e.g. [\"gaming\", \"rgb_keyboard\", \"large_screen\"]), "
    "'text' (any visible model numbers, serial numbers, or spec text). "
    "If you cannot determine a field, use null. "
    'Example: {"brand":"MSI","model":"GT76","category":"gaming_laptop",'
    '"labels":["gaming","rgb_keyboard","dragon_logo"],"text":"GT76 10SF"}.'
)
from src.app.services.cv_ocr import extract_text as extract_text_stage_a


class VisionProviderBusy(RuntimeError):
    """The bounded vision provider is at capacity; callers should retry later."""


_VISION_PROVIDER_GATE = threading.BoundedSemaphore(
    max(1, min(int(os.getenv("CV_VISION_MAX_CONCURRENCY", "1") or 1), 4))
)


class ManagedCVProvider:
    """Thin wrapper around a managed CV API for labels + OCR.

    Supports Google Vision (if installed) and Ollama vision via REST.
    """

    def __init__(self):
        self.provider = os.getenv("CV_PROVIDER", "none").lower()
        self.model = os.getenv("CV_MODEL", "llava")
        self.last_ocr_meta: Dict[str, Any] = {
            "ocr_confidence": None,
            "ocr_engine": None,
            "ocr_word_count": None,
            "cv_model_confidence": None,
            "cv_extraction_method": None,
        }

    def _set_last_ocr_meta(
        self,
        *,
        ocr_confidence: float | None = None,
        ocr_engine: str | None = None,
        ocr_word_count: int | None = None,
        cv_model_confidence: float | None = None,
        cv_extraction_method: str | None = None,
    ) -> None:
        self.last_ocr_meta = {
            "ocr_confidence": ocr_confidence,
            "ocr_engine": ocr_engine,
            "ocr_word_count": ocr_word_count,
            "cv_model_confidence": cv_model_confidence,
            "cv_extraction_method": cv_extraction_method,
        }

    async def get_labels_and_text(
        self,
        image_bytes: bytes,
        mode: str = "triage",
    ) -> Tuple[List[str], str, Optional[Dict]]:
        """Return (labels, text, product_identity).

        *mode* selects the vision prompt:
        - ``"triage"``        — damage/component labels (default, backwards-compat)
        - ``"visual_search"`` — product brand/model/category extraction

        *product_identity* is a dict with ``brand``, ``model``, ``category``
        keys when ``mode="visual_search"`` and the provider returns them,
        otherwise ``None``.
        """
        product_identity: Optional[Dict] = None
        # Image-hash cache: same image (demo/retry/fan-out) skips the 50-86s vision call.
        # Namespaced by mode so triage vs visual_search prompts don't collide. Fail-open.
        _vc_key = None
        try:
            from src.app.services import vision_cache as _vcache
            _vc_key = _vcache.image_key(image_bytes, f"labels:{mode}")
            _vc_hit = _vcache.get(_vc_key)
            if isinstance(_vc_hit, tuple) and len(_vc_hit) == 3:
                return _vc_hit
        except Exception:
            _vc_key = None
        if self.provider == "google":
            try:
                from google.cloud import vision  # type: ignore
                client = vision.ImageAnnotatorClient()
                image = vision.Image(content=image_bytes)
                response = await asyncio.to_thread(client.annotate_image,
                    {
                        "image": image,
                        "features": [
                            {"type_": vision.Feature.Type.LABEL_DETECTION, "max_results": 20},
                            {"type_": vision.Feature.Type.TEXT_DETECTION},
                        ],
                    }
                )
                labels = [l.description.lower() for l in response.label_annotations or []]
                text = response.text_annotations[0].description if response.text_annotations else ""
                self._set_last_ocr_meta(
                    ocr_confidence=None,
                    ocr_engine="google_vision",
                    ocr_word_count=len([tok for tok in str(text or "").split() if tok.strip()]),
                    cv_model_confidence=None,
                    cv_extraction_method="managed_google_vision",
                )
                return labels, text, None
            except Exception:
                pass
        if self.provider == "ollama":
            try:
                labels, text, product_identity = await asyncio.to_thread(self._ollama_labels_and_text, image_bytes, mode=mode)
                self._set_last_ocr_meta(
                    ocr_confidence=None,
                    ocr_engine="ollama_vision",
                    ocr_word_count=len([tok for tok in str(text or "").split() if tok.strip()]),
                    cv_model_confidence=None,
                    cv_extraction_method="managed_ollama_vision",
                )
                # Only cache a non-empty result so a transient miss isn't poisoned.
                if _vc_key and (labels or text or product_identity):
                    try:
                        from src.app.services import vision_cache as _vcache
                        _vcache.put(_vc_key, (labels, text, product_identity))
                    except Exception:
                        pass
                return labels, text, product_identity
            except (VisionProviderBusy, LocalModelFailure):
                raise
            except Exception:
                # Fall through to local OCR so the pipeline still has text evidence.
                logging.getLogger(__name__).exception("cv_provider.ollama_failed")
        # The visual-search VLM already extracts visible text. If it times out, starting the
        # local Stage-A/Stage-B ladder can turn one bounded miss into another minute-long path.
        # Risk-triggered OCR in the router remains available for suspicious screenshots.
        if (mode == "visual_search"
                and str(os.getenv("CV_VISUAL_SEARCH_OCR_FALLBACK", "0")).lower()
                not in ("1", "true", "yes", "on")):
            self._set_last_ocr_meta(
                ocr_confidence=0.0,
                ocr_engine=None,
                ocr_word_count=0,
                cv_model_confidence=None,
                cv_extraction_method="visual_search_ocr_deferred",
            )
            return [], "", None
        # Degradation path: if managed providers fail/misconfigured, use local OCR (tesseract)
        try:
            text = await asyncio.to_thread(self._tesseract_text, image_bytes)
            if text:
                return [], text, None
        except Exception:
            logging.getLogger(__name__).exception("cv_provider.tesseract_failed")
        # Fallback: no provider
        self._set_last_ocr_meta(
            ocr_confidence=0.0,
            ocr_engine=None,
            ocr_word_count=0,
            cv_model_confidence=None,
            cv_extraction_method="no_provider",
        )
        return [], "", None

    def _ollama_labels_and_text(self, image_bytes: bytes, *, mode: str = "triage") -> Tuple[List[str], str, Optional[Dict]]:
        """Call Ollama REST API with a vision model to get labels + OCR-like text.

        Expects Ollama running locally on 127.0.0.1:11434.
        """
        queue_timeout = max(
            0.0,
            min(float(os.getenv("CV_VISION_QUEUE_TIMEOUT_SEC", "0.25") or 0.25), 5.0),
        )
        if not _VISION_PROVIDER_GATE.acquire(timeout=queue_timeout):
            raise VisionProviderBusy("vision_provider_capacity_exhausted")
        try:
            return self._ollama_labels_and_text_authorized(image_bytes, mode=mode)
        finally:
            _VISION_PROVIDER_GATE.release()

    def _ollama_labels_and_text_authorized(
        self, image_bytes: bytes, *, mode: str = "triage",
    ) -> Tuple[List[str], str, Optional[Dict]]:
        """Call Ollama after process-level vision admission has been granted."""
        from src.app.cv.image_normalizer import normalize_image_bytes
        # Preserve original bytes for OCR/forensics; identity inference gets a
        # bounded view so visual tokens cannot consume the whole 4096 context.
        normalized = normalize_image_bytes(image_bytes, max_dim=512)
        img_b64 = base64.b64encode(normalized.image_bytes).decode("ascii")
        prompt = _PRODUCT_IDENTITY_PROMPT if mode == "visual_search" else _TRIAGE_PROMPT
        from src.app.services.local_model_roles import execute_local_model_role, configured_digest
        from src.app.services.model_transports import make_ollama_generate_transport
        output = execute_local_model_role(
            prompt, role='product_identity', purpose='browser_image_identity',
            prompt_id='managed-cv-identity-v1', model=self.model,
            digest=configured_digest('CV_IDENTITY_MODEL_DIGEST'),
            context_hash=hashlib.sha256(image_bytes).hexdigest(),
            timeout_s=float(os.getenv('CV_VISION_TOTAL_TIMEOUT_SEC', '60')),
            max_output_tokens=int(os.getenv('CV_VISION_MAX_OUTPUT_TOKENS', '384')),
            transport=make_ollama_generate_transport(images=[img_b64],
                keep_alive=os.getenv('OLLAMA_KEEP_ALIVE', '2m'),
                options={'temperature':0}),
        )

        # Try to parse JSON from the model's response
        product_identity: Optional[Dict] = None
        try:
            cleaned = (output or "").strip()
            # Remove common Markdown code fences produced by vision models.
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("` \n")
                # If it began with ```json, drop that token.
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].lstrip()
            cleaned = cleaned.replace("```", "").strip()

            start = cleaned.find("{")
            end = cleaned.rfind("}")
            candidate = None
            if start != -1 and end != -1 and end > start:
                candidate = cleaned[start : end + 1]
            elif ("\"labels\"" in cleaned or "'labels'" in cleaned) and ":" in cleaned:
                # Some models forget the outer braces. Wrap and try again.
                candidate = "{" + cleaned.strip().strip(",") + "}"

            if candidate:
                obj = json.loads(candidate)
                labels = [str(x).lower() for x in (obj.get("labels", []) or [])]
                text = str(obj.get("text", "") or "")
                # Extract product identity fields when in visual_search mode
                if mode == "visual_search":
                    _brand = obj.get("brand")
                    _model = obj.get("model")
                    _category = obj.get("category")
                    if any(v for v in (_brand, _model, _category)):
                        product_identity = {
                            "brand": str(_brand).strip() if _brand else None,
                            "model": str(_model).strip() if _model else None,
                            "category": str(_category).strip().lower() if _category else None,
                        }
                        # Also inject brand/model into labels for downstream compat
                        if _brand and str(_brand).lower() not in " ".join(labels):
                            labels.append(str(_brand).lower())
                        if _model and str(_model).lower() not in " ".join(labels):
                            labels.append(str(_model).lower())
                return labels, text, product_identity
        except Exception:
            logging.getLogger(__name__).exception("cv_provider.ollama_parse_failed output=%s", output)
            pass
        # Fallback: heuristics (split by punctuation/space and pick known tokens)
        tokens = [t.strip().lower() for t in output.replace("\n", " ").split(" ") if t.strip()]
        hints = {"screen", "crack", "hinge", "keyboard", "charger", "battery", "adapter"}
        labels = [t for t in tokens if t in hints][:10]
        return labels, "", None

    def _stage_b_threshold(self) -> float:
        try:
            return max(0.0, min(1.0, float(os.getenv("CV_STAGE_B_OCR_CONFIDENCE_MIN", "0.45") or 0.45)))
        except Exception:
            return 0.45

    def _needs_stage_b(self, text: str, confidence: float) -> bool:
        txt = str(text or "").strip()
        if not txt:
            return True
        if float(confidence or 0.0) < self._stage_b_threshold():
            return True
        # Very short text from noisy screenshots usually means we missed overlay data.
        return len(txt) < 12

    def _tesseract_text(self, image_bytes: bytes) -> str:
        try:
            _ocr_provider = (os.getenv("CV_OCR_PROVIDER") or "tesseract")
            out = extract_text_stage_a(
                image_bytes,
                provider=_ocr_provider,
                fallback=(os.getenv("CV_OCR_FALLBACK") or None),
            )
            stage_a_text = " ".join(str(out.get("text") or "").split())[:2000]
            stage_a_conf = float(out.get("confidence") or 0.0)
            stage_a_engine = str(out.get("provider") or _ocr_provider or "").strip() or None
            # Skip Stage B when OCR is intentionally disabled — it would also return
            # empty text, so the deep multi-contrast pass adds no value and only wastes time.
            if _ocr_provider in ("disabled", "none", "off"):
                self._set_last_ocr_meta(
                    ocr_confidence=stage_a_conf,
                    ocr_engine=stage_a_engine,
                    ocr_word_count=len([tok for tok in stage_a_text.split() if tok.strip()]),
                    cv_model_confidence=None,
                    cv_extraction_method="ocr_stage_a",
                )
                return stage_a_text
            if not self._needs_stage_b(stage_a_text, stage_a_conf):
                self._set_last_ocr_meta(
                    ocr_confidence=stage_a_conf,
                    ocr_engine=stage_a_engine,
                    ocr_word_count=len([tok for tok in stage_a_text.split() if tok.strip()]),
                    cv_model_confidence=None,
                    cv_extraction_method="ocr_stage_a",
                )
                return stage_a_text

            # Stage B: triggered fallback (multi-contrast + bottom-band ROI passes).
            from src.app.cv.cv_pipeline import run_risk_triggered_multicontrast_ocr

            deep = run_risk_triggered_multicontrast_ocr(
                image_bytes,
                ocr_provider=_ocr_provider,
                enabled=True,
            )
            stage_b_text = " ".join(str(deep.get("best_text") or "").split())[:2000]
            stage_b_conf = float(deep.get("best_confidence") or 0.0)
            if len(stage_b_text) > len(stage_a_text):
                self._set_last_ocr_meta(
                    ocr_confidence=stage_b_conf if stage_b_conf > 0 else stage_a_conf,
                    ocr_engine=stage_a_engine,
                    ocr_word_count=len([tok for tok in stage_b_text.split() if tok.strip()]),
                    cv_model_confidence=None,
                    cv_extraction_method="ocr_stage_b_multicontrast",
                )
                return stage_b_text
            self._set_last_ocr_meta(
                ocr_confidence=stage_a_conf,
                ocr_engine=stage_a_engine,
                ocr_word_count=len([tok for tok in stage_a_text.split() if tok.strip()]),
                cv_model_confidence=None,
                cv_extraction_method="ocr_stage_a",
            )
            return stage_a_text
        except Exception:
            logging.getLogger(__name__).exception("tesseract OCR failed")
            self._set_last_ocr_meta(
                ocr_confidence=0.0,
                ocr_engine=str(os.getenv("CV_OCR_PROVIDER") or "tesseract"),
                ocr_word_count=0,
                cv_model_confidence=None,
                cv_extraction_method="ocr_failed",
            )
            return ""
