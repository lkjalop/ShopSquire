from __future__ import annotations

import os
import json
import base64
from typing import Tuple, List


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
                pass
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
        req = urllib.request.Request(
            url="http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                output = str(data.get("response") or "")
        except urllib.error.URLError:
            return [], ""
        except Exception:
            return [], ""

        # Try to parse JSON from the model's response
        try:
            start = output.find("{")
            if start != -1:
                obj = json.loads(output[start:])
                labels = [str(x).lower() for x in obj.get("labels", [])]
                text = str(obj.get("text", ""))
                return labels, text
        except Exception:
            pass
        # Fallback: heuristics (split by punctuation/space and pick known tokens)
        tokens = [t.strip().lower() for t in output.replace("\n", " ").split(" ") if t.strip()]
        hints = {"screen", "crack", "hinge", "keyboard", "charger", "battery", "adapter"}
        labels = [t for t in tokens if t in hints][:10]
        return labels, ""
