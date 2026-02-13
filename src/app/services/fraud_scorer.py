from __future__ import annotations

from typing import Dict, Optional, Tuple, Any

from sqlalchemy import text
from src.app.models.db import db_session


class FraudScorer:
    WEIGHTS = {
        "image_hash_match_fraud_db": 0.35,
        "exif_date_mismatch": 0.15,
        "stock_photo_detected": 0.25,
        "manipulation_detected": 0.20,
        "high_return_frequency": 0.15,
        "account_age_under_30_days": 0.10,
        "previous_fraud_flag": 0.30,
        "chargeback_history": 0.25,
        "serial_mismatch": 0.40,
        "product_category_mismatch": 0.30,
        "damage_not_visible": 0.20,
        "unusual_purchase_velocity": 0.25,
        "geographic_anomaly": 0.30,
        "device_fingerprint_mismatch": 0.35,
        "session_hijack_indicators": 0.40,
        "return_pattern_abuse": 0.30,
        "coupon_stacking_attempt": 0.20,
        "price_manipulation_attempt": 0.35,
    }

    # NEW: CV-related signals (pre-LLM cheap checks)
    CV_WEIGHTS = {
        "cv_blur_score_low": 0.15,
        "cv_histogram_anomaly": 0.20,
        "cv_metadata_stripped": 0.25,
        "cv_timestamp_impossible": 0.30,
        "cv_duplicate_hash": 0.35,
        "rapid_photo_submission": 0.20,
    }

    def calculate_score(self, signals: Dict[str, bool]) -> float:
        score = 0.0
        max_possible = 0.0
        for k, v in signals.items():
            w = self.WEIGHTS.get(k, 0.1)
            max_possible += w
            if v:
                score += w
        return min(1.0, score / max_possible) if max_possible > 0 else 0.0

    def get_risk_level(self, score: float) -> str:
        if score >= 0.7:
            return "high"
        if score >= 0.4:
            return "medium"
        if score >= 0.2:
            return "low"
        return "minimal"

    # --- Enrichment helpers ---
    def check_phash(self, phash: Optional[str]) -> Tuple[bool, int, bool]:
        """Return (found, times_seen, confirmed_fraud) from fraud_image_hashes.
        If found and times_seen>1 or confirmed_fraud==1, treat as risky.
        """
        if not phash:
            return False, 0, False
        try:
            with db_session() as db:
                row = db.execute(
                    text("SELECT times_seen, confirmed_fraud FROM fraud_image_hashes WHERE phash = :ph"),
                    {"ph": phash},
                ).fetchone()
                if not row:
                    return False, 0, False
                return True, int(row[0] or 0), bool(row[1] or 0)
        except Exception:
            return False, 0, False

    def upsert_phash(self, phash: Optional[str], case_id: Optional[str]) -> None:
        if not phash:
            return
        try:
            with db_session() as db:
                db.execute(
                    text(
                        "INSERT INTO fraud_image_hashes (phash, first_seen_case_id, times_seen, confirmed_fraud) "
                        "VALUES (:ph, :cid, 1, 0) ON CONFLICT(phash) DO UPDATE SET times_seen = fraud_image_hashes.times_seen + 1"
                    ),
                    {"ph": phash, "cid": case_id or ""},
                )
                db.commit()
        except Exception:
            pass

    def serial_mismatch(self, expected: Optional[str], observed: Optional[str]) -> bool:
        if not expected or not observed:
            return False
        return expected.strip().lower() != observed.strip().lower()

    def score_with_enrichment(
        self,
        base_signals: Dict[str, bool],
        expected_serial: Optional[str],
        observed_serial: Optional[str],
        image_phash: Optional[str],
        session_data: Optional[Dict] = None,
        case_id: Optional[str] = None,
    ) -> Tuple[float, str, Dict[str, bool]]:
        signals = dict(base_signals or {})
        if session_data:
            signals.update(BehavioralFraudDetector().analyze_session(session_data))
        # Serial mismatch
        if self.serial_mismatch(expected_serial, observed_serial):
            signals["serial_mismatch"] = True
        # phash enrichment
        found, times_seen, confirmed = self.check_phash(image_phash)
        risky = found and (times_seen > 1 or confirmed)
        signals["image_hash_match_fraud_db"] = bool(risky)
        # Record phash occurrence
        try:
            self.upsert_phash(image_phash, case_id)
        except Exception:
            pass
        score = self.calculate_score(signals)
        level = self.get_risk_level(score)
        return score, level, signals

    def pre_llm_cv_check(self, image_data: Dict[str, Any]) -> Dict[str, bool]:
        """Run cheap CV checks before any ML model. Returns a dict of boolean signals.

        Expects keys like: blur_score (float 0-1), histogram_anomaly (bool), exif (dict or None),
        photo_timestamp (int/float seconds), order_timestamp (int/float), phash_duplicate (bool).
        """
        signals: Dict[str, bool] = {}
        # 1. Blur score
        try:
            blur = float(image_data.get("blur_score")) if image_data.get("blur_score") is not None else None
            if blur is not None and blur < 0.3:
                signals["cv_blur_score_low"] = True
        except Exception:
            pass

        # 2. Histogram anomaly
        if image_data.get("histogram_anomaly"):
            signals["cv_histogram_anomaly"] = True

        # 3. EXIF/metadata stripped
        if image_data.get("exif") is None and image_data.get("expected_exif"):
            signals["cv_metadata_stripped"] = True

        # 4. Timestamp logic
        try:
            photo_ts = image_data.get("photo_timestamp")
            order_ts = image_data.get("order_timestamp")
            delivery_ts = image_data.get("delivery_timestamp")
            if photo_ts and order_ts and float(photo_ts) < float(order_ts):
                signals["cv_timestamp_impossible"] = True
            if photo_ts and delivery_ts and float(photo_ts) < float(delivery_ts):
                signals["claim_before_delivery"] = True
        except Exception:
            pass

        # 5. Duplicate phash
        if image_data.get("phash_duplicate"):
            signals["cv_duplicate_hash"] = True

        # 6. Rapid submission indicator
        if image_data.get("rapid_submission"):
            signals["rapid_photo_submission"] = True

        return signals


class BehavioralFraudDetector:
    def analyze_session(self, session_data: dict) -> dict:
        signals = {}
        if session_data.get("purchases_last_hour", 0) > 5:
            signals["unusual_purchase_velocity"] = True
        if session_data.get("ip_country") and session_data.get("shipping_country"):
            if session_data.get("ip_country") != session_data.get("shipping_country"):
                signals["geographic_anomaly"] = True
        if session_data.get("device_changed_mid_session"):
            signals["device_fingerprint_mismatch"] = True
        if session_data.get("session_hijack_indicators"):
            signals["session_hijack_indicators"] = True
        if session_data.get("returns_last_30_days", 0) > 3:
            signals["return_pattern_abuse"] = True
        if session_data.get("coupon_stack_attempt"):
            signals["coupon_stacking_attempt"] = True
        if session_data.get("price_manipulation_attempt"):
            signals["price_manipulation_attempt"] = True
        return signals
