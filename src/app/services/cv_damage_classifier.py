from __future__ import annotations

import os
from typing import Any, Dict, Tuple


class DamageClassifier:
    """Classify damage type and severity from image bytes.

    Priority:
    1. Optional trained model (`model_path`) over engineered features.
    2. Calibrated heuristic model over detector output + image quality signals.
    """

    DAMAGE_TYPES = [
        "screen_crack",
        "screen_scratch",
        "body_dent",
        "body_scratch",
        "hinge_damage",
        "keyboard_damage",
        "port_damage",
        "cosmetic_wear",
        "no_visible_damage",
        "unknown",
    ]
    SEVERITY_LEVELS = ["none", "minor", "moderate", "severe", "total_loss"]

    def __init__(self, model_path: str | None = None, yolo_model_path: str | None = None):
        self.model_path = model_path
        self.model = None
        self.yolo_model_path = yolo_model_path
        self.yolo = None
        self.review_threshold = float(os.getenv("CV_DAMAGE_REVIEW_THRESHOLD", "0.62"))
        self._load_model()
        self._load_yolo()

    def classify(self, image_bytes: bytes) -> Dict[str, Any]:
        detections = self.detect_objects(image_bytes)
        image_stats = self._extract_image_stats(image_bytes)

        if self.model is not None:
            try:
                feats = self._build_features(detections, image_stats)
                pred = self._predict_with_model(feats)
                return self._finalize_result(
                    status="model_predicted",
                    note="trained_damage_model",
                    damage_type=pred[0],
                    severity=pred[1],
                    confidence=pred[2],
                    detections=detections,
                    image_stats=image_stats,
                )
            except Exception:
                pass

        heur_type, heur_sev, heur_conf = self._heuristic_predict(detections, image_stats)
        status = "heuristic_predicted" if detections else "heuristic_no_detection"
        note = "calibrated_heuristic" if detections else "no_detector_labels_using_image_stats"
        return self._finalize_result(
            status=status,
            note=note,
            damage_type=heur_type,
            severity=heur_sev,
            confidence=heur_conf,
            detections=detections,
            image_stats=image_stats,
        )

    def _load_model(self) -> None:
        if not self.model_path:
            return
        try:
            import joblib  # type: ignore

            self.model = joblib.load(self.model_path)
        except Exception:
            self.model = None

    def _load_yolo(self) -> None:
        if not self.yolo_model_path:
            return
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception:
            return
        try:
            self.yolo = YOLO(self.yolo_model_path)
        except Exception:
            self.yolo = None

    def detect_objects(self, image_bytes: bytes) -> list[dict]:
        if not self.yolo:
            return []
        try:
            inp: Any = image_bytes
            try:
                from PIL import Image  # type: ignore
                import numpy as np  # type: ignore

                img = Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB")
                inp = np.array(img)
            except Exception:
                inp = image_bytes

            results = self.yolo(inp)
            detections = []
            for r in results:
                for box in r.boxes:
                    detections.append(
                        {
                            "label": (
                                getattr(r.names, "get", lambda x: None)(int(box.cls))  # type: ignore[attr-defined]
                                if hasattr(r, "names")
                                else None
                            ),
                            "confidence": float(box.conf),
                            "xyxy": [float(x) for x in box.xyxy[0].tolist()],
                        }
                    )
            return detections
        except Exception:
            return []

    def _extract_image_stats(self, image_bytes: bytes) -> Dict[str, float]:
        try:
            from PIL import Image  # type: ignore
            import numpy as np  # type: ignore

            img = Image.open(__import__("io").BytesIO(image_bytes)).convert("L")
            arr = np.array(img, dtype="float32")
            mean = float(arr.mean()) / 255.0
            std = float(arr.std()) / 255.0
            # Simple edge density proxy.
            gx = abs(arr[:, 1:] - arr[:, :-1]).mean() / 255.0
            gy = abs(arr[1:, :] - arr[:-1, :]).mean() / 255.0
            edge = float((gx + gy) / 2.0)
            return {"mean_luma": mean, "std_luma": std, "edge_density": edge}
        except Exception:
            return {"mean_luma": 0.5, "std_luma": 0.0, "edge_density": 0.0}

    def _build_features(self, detections: list[dict], image_stats: Dict[str, float]) -> Dict[str, float]:
        labels = [str(d.get("label") or "").lower() for d in detections]
        confs = [float(d.get("confidence") or 0.0) for d in detections]
        return {
            "det_count": float(len(detections)),
            "det_conf_avg": (sum(confs) / len(confs)) if confs else 0.0,
            "has_crack": 1.0 if any("crack" in l for l in labels) else 0.0,
            "has_scratch": 1.0 if any("scratch" in l for l in labels) else 0.0,
            "has_dent": 1.0 if any("dent" in l for l in labels) else 0.0,
            "has_hinge": 1.0 if any("hinge" in l for l in labels) else 0.0,
            "has_keyboard": 1.0 if any("keyboard" in l for l in labels) else 0.0,
            "has_port": 1.0 if any("port" in l for l in labels) else 0.0,
            "edge_density": float(image_stats.get("edge_density", 0.0)),
            "std_luma": float(image_stats.get("std_luma", 0.0)),
        }

    def _predict_with_model(self, feats: Dict[str, float]) -> Tuple[str, str, float]:
        model = self.model
        feat_vec = [list(feats.values())]
        damage_type = "unknown"
        severity = "moderate"
        confidence = 0.5
        if hasattr(model, "predict"):
            pred = model.predict(feat_vec)
            if pred is not None and len(pred) > 0:
                if isinstance(pred[0], (tuple, list)) and len(pred[0]) >= 2:
                    damage_type = str(pred[0][0])
                    severity = str(pred[0][1])
                else:
                    damage_type = str(pred[0])
        if hasattr(model, "predict_proba"):
            try:
                probs = model.predict_proba(feat_vec)
                if probs is not None and len(probs) > 0:
                    row = probs[0]
                    confidence = max(float(x) for x in row)
            except Exception:
                confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        if severity not in self.SEVERITY_LEVELS:
            severity = "moderate"
        if damage_type not in self.DAMAGE_TYPES:
            damage_type = "unknown"
        return damage_type, severity, confidence

    def _heuristic_predict(self, detections: list[dict], image_stats: Dict[str, float]) -> Tuple[str, str, float]:
        labels = [str(d.get("label") or "").lower() for d in detections]
        confs = [float(d.get("confidence") or 0.0) for d in detections]
        conf_avg = (sum(confs) / len(confs)) if confs else 0.45
        edge = float(image_stats.get("edge_density") or 0.0)

        damage_type = "unknown"
        severity = "minor"
        if any("crack" in l for l in labels):
            damage_type = "screen_crack"
            severity = "severe" if conf_avg > 0.72 or edge > 0.20 else "moderate"
        elif any("scratch" in l for l in labels):
            damage_type = "screen_scratch" if any("screen" in l for l in labels) else "body_scratch"
            severity = "minor" if conf_avg < 0.7 else "moderate"
        elif any("dent" in l for l in labels):
            damage_type = "body_dent"
            severity = "moderate"
        elif any("hinge" in l for l in labels):
            damage_type = "hinge_damage"
            severity = "severe"
        elif any("keyboard" in l for l in labels):
            damage_type = "keyboard_damage"
            severity = "moderate"
        elif any("port" in l for l in labels):
            damage_type = "port_damage"
            severity = "moderate"
        elif detections:
            damage_type = "cosmetic_wear"
            severity = "minor"
        else:
            if edge < 0.06:
                damage_type = "no_visible_damage"
                severity = "none"
            else:
                damage_type = "unknown"
                severity = "minor"

        confidence = conf_avg if detections else (0.68 if damage_type == "no_visible_damage" else 0.42)
        confidence = max(0.0, min(1.0, confidence))
        return damage_type, severity, confidence

    def _finalize_result(
        self,
        *,
        status: str,
        note: str,
        damage_type: str,
        severity: str,
        confidence: float,
        detections: list[dict],
        image_stats: Dict[str, float],
    ) -> Dict[str, Any]:
        # Calibrate confidence for downstream quality gates
        try:
            from src.app.services.confidence_calibration import calibrate_confidence
            conf_cal = calibrate_confidence(confidence, agent_type="cv_damage")
        except Exception:
            conf_cal = confidence
        needs_review = float(conf_cal) < self.review_threshold or damage_type in ("unknown",)
        sev_map = {"none": 0.0, "minor": 0.25, "moderate": 0.5, "severe": 0.75, "total_loss": 1.0}
        return {
            "status": status,
            "note": note,
            "damage_type": damage_type,
            "severity": severity,
            "confidence": confidence,
            "confidence_calibrated": float(max(0.0, min(1.0, conf_cal))),
            "severity_score": float(sev_map.get(severity, 0.5)),
            "needs_human_review": needs_review,
            "review_threshold": self.review_threshold,
            "detections": detections,
            "image_stats": image_stats,
            "model_loaded": self.model is not None,
            "yolo_loaded": self.yolo is not None,
            "model_path": self.model_path,
            "yolo_model_path": self.yolo_model_path,
        }
