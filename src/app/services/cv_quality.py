from __future__ import annotations

from typing import Any, Dict, List
import os


def _clip_scores(image_bytes: bytes, labels: List[str]) -> Dict[str, Any]:
    try:
        import torch  # type: ignore
        import open_clip  # type: ignore
        from PIL import Image
        from io import BytesIO
    except Exception as exc:
        return {"error": str(exc), "scores": {}, "provider": "clip"}

    try:
        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        tokenizer = open_clip.get_tokenizer("ViT-B-32")
        image = preprocess(Image.open(BytesIO(image_bytes))).unsqueeze(0)
        text = tokenizer(labels)
        with torch.no_grad():
            image_features = model.encode_image(image)
            text_features = model.encode_text(text)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            logits = (image_features @ text_features.T).squeeze(0)
            probs = logits.softmax(dim=-1).cpu().tolist()
        scores = {label: float(prob) for label, prob in zip(labels, probs)}
        return {"scores": scores, "provider": "clip"}
    except Exception as exc:
        return {"error": str(exc), "scores": {}, "provider": "clip"}


def score_quality(image_bytes: bytes, labels: List[str]) -> Dict[str, Any]:
    # CLIP-based quality scoring is optional and can be heavy/unstable on some
    # Windows setups (model downloads + large tensor ops). Keep it opt-in.
    try:
        enabled = os.getenv("CV_CLIP_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        enabled = False
    if os.getenv("PYTEST_CURRENT_TEST"):
        enabled = False
    if not enabled:
        return {"scores": {}, "provider": "clip_disabled"}
    return _clip_scores(image_bytes, labels)
