from __future__ import annotations

import os
import json
import base64
from typing import Tuple, List
import logging
from src.app.security.url_guard import ensure_safe_outbound_url


class ManagedCVProvider:
    """Thin wrapper around a managed CV API for labels + OCR.

    Supports Google Vision (if installed) and Ollama vision via REST.
    """

    def __init__(self):
        self.provider = os.getenv("CV_PROVIDER", "none").lower()
        self.model = os.getenv("CV_MODEL", "llava")

    async def get_labels_and_text(self, image_bytes: bytes) -> Tuple[List[str], str]:
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
                return labels, text
            except Exception:
                pass
        if self.provider == "ollama":
            try:
                return self._ollama_labels_and_text(image_bytes)
            except Exception:
                # Fall through to local OCR so the pipeline still has text evidence.
                logging.getLogger(__name__).exception("cv_provider.ollama_failed")
        # Degradation path: if managed providers fail/misconfigured, use local OCR (tesseract)
        try:
            text = self._tesseract_text(image_bytes)
            if text:
                return [], text
        except Exception:
            logging.getLogger(__name__).exception("cv_provider.tesseract_failed")
        # Fallback: no provider
        return [], ""

    def _ollama_labels_and_text(self, image_bytes: bytes) -> Tuple[List[str], str]:
        """Call Ollama REST API with a vision model to get labels + OCR-like text.

        Expects Ollama running locally on 127.0.0.1:11434.
        """
        import urllib.request
        import urllib.error

        img_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = (
            "You are an e-commerce vision assistant. Analyze the provided image and "
            "return a compact JSON object with keys 'labels' (array of lowercase keywords) "
            "and 'text' (any visible serial/receipt text snippets). Use laptop-related labels like "
            "screen, crack, hinge, keyboard, charger when relevant. Example: {\"labels\":[\"screen\",\"crack\"],\"text\":\"SN-ABC123\"}."
        )
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
            return [], ""

        # Try to parse JSON from the model's response
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
                return labels, text
        except Exception:
            logging.getLogger(__name__).exception("cv_provider.ollama_parse_failed output=%s", output)
            pass
        # Fallback: heuristics (split by punctuation/space and pick known tokens)
        tokens = [t.strip().lower() for t in output.replace("\n", " ").split(" ") if t.strip()]
        hints = {"screen", "crack", "hinge", "keyboard", "charger", "battery", "adapter"}
        labels = [t for t in tokens if t in hints][:10]
        return labels, ""

    def _tesseract_text(self, image_bytes: bytes) -> str:
        try:
            from PIL import Image
            import pytesseract

            img = Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB")
            # Keep it conservative: tesseract can be noisy; strip and cap.
            txt = pytesseract.image_to_string(img) or ""
            txt = " ".join(txt.split())
            return txt[:2000]
        except Exception:
            logging.getLogger(__name__).exception("tesseract OCR failed")
            return ""
