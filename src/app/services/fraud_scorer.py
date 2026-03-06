from __future__ import annotations

from typing import Dict, Optional, Tuple, Any, List
import logging
import json
import os
import re

from sqlalchemy import text
from src.app.models.db import db_session
from src.app.services.neo4j_graph import (
    account_device_ip_ring_signal,
    shipping_address_cluster_signal,
    upsert_account_device_ip_event,
)

logger = logging.getLogger("shopsquire.fraud_scorer")


def _coerce_hash_set(raw: Any) -> set[str]:
    out: set[str] = set()
    if raw is None:
        return out
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return out
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                raw = parsed
            else:
                raw = re.split(r"[,\s]+", s)
        except Exception:
            raw = re.split(r"[,\s]+", s)
    if isinstance(raw, list):
        for item in raw:
            v = str(item or "").strip().lower()
            if v:
                out.add(v)
    return out


def _load_hash_intel(*, env_hashes: str, env_path: str) -> set[str]:
    out: set[str] = set()
    try:
        out.update(_coerce_hash_set(os.getenv(env_hashes)))
    except Exception:
        pass
    try:
        p = str(os.getenv(env_path) or "").strip()
        if p and os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                raw = f.read()
            out.update(_coerce_hash_set(raw))
    except Exception:
        pass
    return out


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
        "ip_velocity_spike": 0.30,
        "shipping_address_clustered": 0.30,
        "account_device_ip_ring_hit": 0.30,
        "ja3_known_fraud_tool": 0.35,
        "ja4_known_fraud_tool": 0.35,
        "geoip_high_risk_country": 0.20,
        "geoip_country_mismatch": 0.30,
        "asn_datacenter_session": 0.25,
        "asn_known_proxy_tor": 0.30,
        "mid_session_country_change": 0.35,
        # Behavioral biometrics
        "biometric_mouse_bot_pattern": 0.30,
        "biometric_typing_bot_pattern": 0.30,
        "biometric_tap_bot_pattern": 0.25,
        "biometric_scroll_uniform": 0.15,
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
    FEATURE_GROUPS = {
        "image_hash_match_fraud_db": "identity",
        "exif_date_mismatch": "cv",
        "stock_photo_detected": "cv",
        "manipulation_detected": "cv",
        "high_return_frequency": "history",
        "account_age_under_30_days": "account",
        "previous_fraud_flag": "history",
        "chargeback_history": "history",
        "serial_mismatch": "cv",
        "product_category_mismatch": "cv",
        "damage_not_visible": "cv",
        "unusual_purchase_velocity": "behavior",
        "geographic_anomaly": "geo",
        "device_fingerprint_mismatch": "device",
        "session_hijack_indicators": "device",
        "return_pattern_abuse": "returns",
        "coupon_stacking_attempt": "commerce",
        "price_manipulation_attempt": "commerce",
        "ip_velocity_spike": "network",
        "shipping_address_clustered": "graph",
        "account_device_ip_ring_hit": "graph",
        "ja3_known_fraud_tool": "tls_fingerprint",
        "ja4_known_fraud_tool": "tls_fingerprint",
        "geoip_high_risk_country": "geo",
        "geoip_country_mismatch": "geo",
        "asn_datacenter_session": "network",
        "asn_known_proxy_tor": "network",
        "mid_session_country_change": "geo",
        "cv_blur_score_low": "cv",
        "cv_histogram_anomaly": "cv",
        "cv_metadata_stripped": "cv",
        "cv_timestamp_impossible": "cv",
        "cv_duplicate_hash": "cv",
        "rapid_photo_submission": "behavior",
        # Behavioral biometrics
        "biometric_mouse_bot_pattern": "biometrics",
        "biometric_typing_bot_pattern": "biometrics",
        "biometric_tap_bot_pattern": "biometrics",
        "biometric_scroll_uniform": "biometrics",
    }

    @classmethod
    def feature_registry(cls) -> Dict[str, Any]:
        out = []
        all_weights: Dict[str, float] = {}
        all_weights.update(cls.WEIGHTS)
        all_weights.update(cls.CV_WEIGHTS)
        for name, weight in sorted(all_weights.items(), key=lambda x: x[0]):
            out.append(
                {
                    "name": name,
                    "weight": float(weight),
                    "group": str(cls.FEATURE_GROUPS.get(name) or "other"),
                    "enabled": True,
                }
            )
        return {
            "version": "fraud_feature_registry_v1",
            "feature_count": len(out),
            "features": out,
        }

    def monitoring_snapshot(self, signals: Dict[str, bool], *, decision_outcome: str | None = None) -> Dict[str, Any]:
        all_weights: Dict[str, float] = {}
        all_weights.update(self.WEIGHTS)
        all_weights.update(self.CV_WEIGHTS)
        active: List[str] = []
        weighted_sum = 0.0
        max_possible = 0.0
        by_group: Dict[str, int] = {}
        for name, weight in all_weights.items():
            max_possible += float(weight)
            if bool((signals or {}).get(name)):
                active.append(name)
                weighted_sum += float(weight)
                grp = str(self.FEATURE_GROUPS.get(name) or "other")
                by_group[grp] = int(by_group.get(grp, 0) + 1)
        fp_cost = 0.0
        try:
            fp_unit = float(__import__("os").getenv("FRAUD_FALSE_POSITIVE_COST_USD", "7.5") or 7.5)
            if str(decision_outcome or "").lower() in ("false_positive", "fp"):
                fp_cost = round(fp_unit * max(1, len(active)), 2)
        except Exception:
            fp_cost = 0.0
        return {
            "registry_version": "fraud_feature_registry_v1",
            "active_feature_count": len(active),
            "active_features": active,
            "feature_coverage": round(float(len(active)) / float(max(1, len(all_weights))), 4),
            "weighted_risk_signal": round(float(weighted_sum) / float(max(1e-9, max_possible)), 4),
            "active_by_group": by_group,
            "estimated_false_positive_cost_usd": fp_cost,
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
        try:
            if float(session_data.get("ip_velocity_per_hour") or 0.0) >= 20.0:
                signals["ip_velocity_spike"] = True
        except Exception:
            pass
        try:
            # Address cluster features may come from graph/risk service.
            cluster_size = int(session_data.get("shipping_address_cluster_size") or 0)
            if cluster_size >= 4:
                signals["shipping_address_clustered"] = True
        except Exception:
            pass
        # Optional Neo4j pilot: relationship-heavy fraud ring detection.
        try:
            graph = shipping_address_cluster_signal(
                shipping_address_hash=str(session_data.get("shipping_address_hash") or ""),
                account_id=str(session_data.get("account_id") or ""),
                device_fingerprint=str(session_data.get("device_fingerprint") or ""),
            )
            if int(graph.get("cluster_size") or 0) >= 4 or bool(graph.get("ring_hit")):
                signals["shipping_address_clustered"] = True
                session_data["neo4j_ring_risk"] = float(graph.get("ring_risk") or 0.0)
                session_data["neo4j_cluster_size"] = int(graph.get("cluster_size") or 0)
        except Exception:
            pass
        # §13: Account-device-IP synthetic identity ring detection via Neo4j graph.
        try:
            _ = upsert_account_device_ip_event(
                account_id=str(session_data.get("account_id") or ""),
                device_fingerprint=str(session_data.get("device_fingerprint") or ""),
                source_ip=str(session_data.get("ip") or session_data.get("source_ip") or ""),
                shipping_address_hash=str(session_data.get("shipping_address_hash") or ""),
            )
            ring = account_device_ip_ring_signal(
                account_id=str(session_data.get("account_id") or ""),
                device_fingerprint=str(session_data.get("device_fingerprint") or ""),
                source_ip=str(session_data.get("ip") or session_data.get("source_ip") or ""),
            )
            if bool(ring.get("ring_hit")):
                signals["shipping_address_clustered"] = True
                signals["account_device_ip_ring_hit"] = True
            session_data["neo4j_account_device_ip_ring"] = ring
        except Exception:
            pass

        # ── JA3/JA4 TLS fingerprint signals ──
        try:
            ja3_hash = str(session_data.get("ja3_hash") or "").strip()
            ja4_hash = str(session_data.get("ja4_hash") or "").strip()
            known_fraud_ja3 = _coerce_hash_set(session_data.get("known_fraud_ja3_hashes"))
            known_fraud_ja4 = _coerce_hash_set(session_data.get("known_fraud_ja4_hashes"))
            known_fraud_ja3.update(
                _load_hash_intel(env_hashes="FRAUD_KNOWN_JA3_HASHES", env_path="FRAUD_JA3_INTEL_PATH")
            )
            known_fraud_ja4.update(
                _load_hash_intel(env_hashes="FRAUD_KNOWN_JA4_HASHES", env_path="FRAUD_JA4_INTEL_PATH")
            )
            if ja3_hash and ja3_hash.lower() in known_fraud_ja3:
                signals["ja3_known_fraud_tool"] = True
            if ja4_hash and ja4_hash.lower() in known_fraud_ja4:
                signals["ja4_known_fraud_tool"] = True
            if bool(session_data.get("ja3_intel_hit")):
                signals["ja3_known_fraud_tool"] = True
            if bool(session_data.get("ja4_intel_hit")):
                signals["ja4_known_fraud_tool"] = True
        except Exception:
            pass

        # ── GeoIP + ASN signals ──
        try:
            from src.app.services.geoip import enrich_ip
            source_ip = str(session_data.get("ip") or session_data.get("source_ip") or "")
            if source_ip:
                geo = enrich_ip(source_ip) or {}
                if geo:
                    # High-risk country
                    if float(geo.get("risk") or 0.0) >= 0.7:
                        signals["geoip_high_risk_country"] = True
                    # Country mismatch (IP country vs billing country)
                    billing_country = str(session_data.get("billing_country") or "").upper()
                    ip_country = str(geo.get("country") or "").upper()
                    if billing_country and ip_country and billing_country != ip_country:
                        signals["geoip_country_mismatch"] = True
                    # ASN: datacenter / hosting provider
                    if bool(geo.get("is_hosting")):
                        signals["asn_datacenter_session"] = True
                    # ASN: known VPN/proxy/Tor
                    if bool(geo.get("is_vpn")):
                        signals["asn_known_proxy_tor"] = True
            # Mid-session country change
            prev_country = str(session_data.get("previous_ip_country") or "").upper()
            curr_country = str(session_data.get("ip_country") or "").upper()
            if prev_country and curr_country and prev_country != curr_country:
                signals["mid_session_country_change"] = True
        except (ImportError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("fraud_scorer.geoip_enrichment_failed: %s", exc)

        # ── Behavioral biometrics (mouse, typing, tap, scroll) ──
        try:
            from src.app.services.behavioral_biometrics import analyze_session_biometrics
            bio = analyze_session_biometrics(session_data)
            if bio.signals:
                signals.update(bio.signals)
                session_data["biometric_risk_score"] = bio.risk_score
                session_data["biometric_is_bot_likely"] = bio.is_bot_likely
        except Exception:
            pass

        return signals
