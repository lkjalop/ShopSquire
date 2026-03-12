from __future__ import annotations

import os
import json
import base64
from typing import Dict, Optional, Tuple, List
import logging
from src.app.security.url_guard import ensure_safe_outbound_url

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


class ManagedCVProvider:
    """Thin wrapper around a managed CV API for labels + OCR.

    Supports Google Vision (if installed) and Ollama vision via REST.
    """

    def __init__(self):
        self.provider = os.getenv("CV_PROVIDER", "none").lower()
        self.model = os.getenv("CV_MODEL", "llava")

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
        if self.provider == "google":
            try:
                from google.cloud import vision  # type: ignore
                client = vision.ImageAnnotatorClient()
                image = vision.Image(content=image_bytes)
                response = client.annotate_image(
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
                return labels, text, None
            except Exception:
                pass
        if self.provider == "ollama":
            try:
                return self._ollama_labels_and_text(image_bytes, mode=mode)
            except Exception:
                # Fall through to local OCR so the pipeline still has text evidence.
                logging.getLogger(__name__).exception("cv_provider.ollama_failed")
        # Degradation path: if managed providers fail/misconfigured, use local OCR (tesseract)
        try:
            text = self._tesseract_text(image_bytes)
            if text:
                return [], text, None
        except Exception:
            logging.getLogger(__name__).exception("cv_provider.tesseract_failed")
        # Fallback: no provider
        return [], "", None

    def _ollama_labels_and_text(self, image_bytes: bytes, *, mode: str = "triage") -> Tuple[List[str], str, Optional[Dict]]:
        """Call Ollama REST API with a vision model to get labels + OCR-like text.

        Expects Ollama running locally on 127.0.0.1:11434.
        """
        import urllib.request
        import urllib.error

        img_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = _PRODUCT_IDENTITY_PROMPT if mode == "visual_search" else _TRIAGE_PROMPT
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
        }).encode("utf-8")
        base = (os.getenv("OLLAMA_URL", "http://127.0.0.1:11434") or "http://127.0.0.1:11434").rstrip("/")
        url = f"{base}/api/generate"
        ensure_safe_outbound_url(url)
        timeout = float(os.getenv("CV_VISION_TIMEOUT_SEC", "20") or 20)

        # Try configured model first, then a small fallback list for resilience.
        model_candidates = []
        for m in (self.model, os.getenv("CV_VISION_MODEL"), os.getenv("OLLAMA_DEFAULT_MODEL"), "llava-latest:latest", "llava:latest", "llava-latest", "llava"):
            if m and str(m).strip():
                model_candidates.append(str(m).strip())
        # stable de-dupe preserving order
        seen = set()
        model_candidates = [m for m in model_candidates if m not in seen and not seen.add(m)]

        last_err = None
        for model_name in model_candidates[:6]:
            req = urllib.request.Request(
                url=url,
                data=json.dumps(
                    {
                        "model": model_name,
                        "prompt": prompt,
                        "images": [img_b64],
                        "stream": False,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    output = str(data.get("response") or "")
                # Parse below; if parsing fails we'll still fall back to heuristics.
                break
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                last_err = f"http_error status={getattr(e, 'code', None)} body={body[:200]}"
                continue
            except urllib.error.URLError as e:
                last_err = f"url_error {e}"
                continue
            except Exception as e:
                last_err = f"error {type(e).__name__}: {e}"
                logging.getLogger(__name__).exception("cv_provider.ollama_call_failed model=%s err=%s", model_name, last_err)
                continue
        else:
            logging.getLogger(__name__).warning("cv_provider.ollama_unreachable url=%s err=%s", url, last_err)
            return [], "", None

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
            # Skip Stage B when OCR is intentionally disabled — it would also return
            # empty text, so the deep multi-contrast pass adds no value and only wastes time.
            if _ocr_provider in ("disabled", "none", "off"):
                return stage_a_text
            if not self._needs_stage_b(stage_a_text, stage_a_conf):
                return stage_a_text

            # Stage B: triggered fallback (multi-contrast + bottom-band ROI passes).
            from src.app.cv.cv_pipeline import run_risk_triggered_multicontrast_ocr

            deep = run_risk_triggered_multicontrast_ocr(
                image_bytes,
                ocr_provider=_ocr_provider,
                enabled=True,
            )
            stage_b_text = " ".join(str(deep.get("best_text") or "").split())[:2000]
            if len(stage_b_text) > len(stage_a_text):
                return stage_b_text
            return stage_a_text
        except Exception:
            logging.getLogger(__name__).exception("tesseract OCR failed")
            return ""
