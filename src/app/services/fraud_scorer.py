from __future__ import annotations

from typing import Dict, Optional, Tuple, Any, List
import logging
import json
import os
import re
import uuid
import ipaddress

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


def _is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(value or "").strip())
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except Exception:
        return False


def compute_signal_multipliers(
    rows: List[Dict[str, Any]],
    *,
    min_samples: int = 5,
    floor: float = 0.5,
    ceil: float = 1.5,
) -> Dict[str, float]:
    """Learn a per-signal weight multiplier from outcome feedback (the fraud feedback loop, pure).

    For each signal, precision = confirmed_fraud / (confirmed_fraud + false_positive) over the cases
    where the signal fired; multiplier = floor + (ceil-floor) * precision — so a signal that mostly
    fires on CONFIRMED fraud is amplified toward `ceil`, one that mostly fires on FALSE POSITIVES is
    damped toward `floor`. A signal is only adjusted once it has >= min_samples labeled firings
    (otherwise omitted == neutral 1.0). No I/O; deterministic. This is what turns static weights into
    weights that LEARN from confirmed/false-positive labels."""
    pos: Dict[str, int] = {}
    neg: Dict[str, int] = {}
    for r in rows or []:
        label = str((r or {}).get("label") or "").strip().lower()
        sigs = (r or {}).get("signals") or {}
        if not isinstance(sigs, dict):
            continue
        for s, v in sigs.items():
            if not v:
                continue
            if label == "confirmed_fraud":
                pos[s] = pos.get(s, 0) + 1
            elif label == "false_positive":
                neg[s] = neg.get(s, 0) + 1
    out: Dict[str, float] = {}
    for s in set(pos) | set(neg):
        c, f = pos.get(s, 0), neg.get(s, 0)
        if c + f < int(min_samples):
            continue  # insufficient evidence -> neutral
        precision = c / (c + f)
        out[s] = round(floor + (ceil - floor) * precision, 4)
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
        "geoip_lookup_unavailable": 0.12,
        "gnn_ring_risk_medium": 0.22,
        "gnn_ring_risk_high": 0.38,
        "behavioral_anomaly_medium": 0.18,
        "behavioral_anomaly_high": 0.32,
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
        "geoip_lookup_unavailable": "network",
        "gnn_ring_risk_medium": "graph",
        "gnn_ring_risk_high": "graph",
        "behavioral_anomaly_medium": "behavior",
        "behavioral_anomaly_high": "behavior",
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

    _FEEDBACK_DDL = (
        "CREATE TABLE IF NOT EXISTS fraud_feedback ("
        "id TEXT PRIMARY KEY, case_id TEXT, label TEXT, score REAL, "
        "signals_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )

    def record_fraud_outcome(
        self,
        case_id: Optional[str],
        label: str,
        *,
        signals: Optional[Dict[str, bool]] = None,
        score: Optional[float] = None,
    ) -> bool:
        """Record a resolved outcome — the feedback the adaptive weights learn from. label is one of
        confirmed_fraud / false_positive / legitimate. Lazily ensures the table; never raises."""
        lbl = str(label or "").strip().lower()
        if lbl not in ("confirmed_fraud", "false_positive", "legitimate"):
            return False
        try:
            fired = {str(k): True for k, v in (signals or {}).items() if v}
            with db_session() as db:
                db.execute(text(self._FEEDBACK_DDL))
                db.execute(
                    text("INSERT INTO fraud_feedback (id, case_id, label, score, signals_json) "
                         "VALUES (:id, :c, :l, :s, :j)"),
                    {"id": uuid.uuid4().hex, "c": str(case_id or ""), "l": lbl,
                     "s": float(score or 0.0), "j": json.dumps(fired)},
                )
                db.commit()
            return True
        except Exception:
            return False

    def learned_signal_weights(self) -> Dict[str, float]:
        """Per-signal multipliers derived from accumulated feedback. Empty when there is no feedback
        (so scoring stays at the static weights). Never raises."""
        rows: List[Any] = []
        try:
            with db_session() as db:
                db.execute(text(self._FEEDBACK_DDL))
                rows = list(db.execute(text("SELECT label, signals_json FROM fraud_feedback")).fetchall())
        except Exception:
            return {}
        parsed: List[Dict[str, Any]] = []
        for r in rows:
            try:
                sigs = json.loads(r[1] or "{}")
            except Exception:
                sigs = {}
            parsed.append({"label": r[0], "signals": sigs})
        return compute_signal_multipliers(parsed)

    def calculate_score(self, signals: Dict[str, bool]) -> float:
        score = 0.0
        max_possible = 0.0
        all_weights: Dict[str, float] = {}
        all_weights.update(self.WEIGHTS)
        all_weights.update(self.CV_WEIGHTS)
        # Adaptive weights (FRAUD_ADAPTIVE_WEIGHTS, default OFF): scale each signal's weight by the
        # multiplier learned from confirmed/false-positive feedback. Off -> identical to static.
        mult: Dict[str, float] = {}
        if str(os.getenv("FRAUD_ADAPTIVE_WEIGHTS", "0")).strip().lower() in ("1", "true", "yes", "on"):
            try:
                mult = self.learned_signal_weights()
            except Exception:
                mult = {}
        for k, v in signals.items():
            w = all_weights.get(k, 0.1) * float(mult.get(k, 1.0))
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
        # MAESTRO boundary (audit): record that the fraud agent scored within its tool/data scope.
        # Clean by definition (score_fraud/orders are in-boundary); in 'block' mode an out-of-scope
        # call would raise. Never affects the score.
        try:
            from src.app.security.maestro_boundaries import record_agent_action as _maestro
            from src.app.services.decision_log import log_trace_event as _fs_log
            _maestro(agent_name="Fraud_Scoring_Agent", tool_name="score_fraud",
                     data_scope="orders", trace_id=(case_id or None), log_fn=_fs_log)
        except Exception:
            pass
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
        if session_data is not None:
            session_data["fraud_summary"] = self.to_merchant_dict(score=score, risk_level=level, signals=signals)
        return score, level, signals

    def get_top_evidence(
        self,
        signals: Dict[str, bool],
        top_n: int = 3,
    ) -> Dict[str, Any]:
        """SHAP-style signal attribution: weight × active → top-N evidence strings + conformal interval.

        Returns:
            {
                "top_evidence": ["serial_mismatch (0.40)", "image_hash_match_fraud_db (0.35)", ...],
                "confidence_interval": [lo, hi],   # score ± 0.08 clamped [0, 1]
                "attribution": {"signal_name": weight, ...}  # all active signals with weights
            }
        """
        all_weights = {**self.WEIGHTS, **self.CV_WEIGHTS}
        active = [(sig, all_weights.get(sig, 0.05)) for sig, active in (signals or {}).items() if active]
        active.sort(key=lambda x: x[1], reverse=True)
        top_evidence = [f"{sig} ({w:.2f})" for sig, w in active[:top_n]]
        attribution = {sig: round(w, 3) for sig, w in active}
        score = self.calculate_score(signals)
        confidence_interval = [
            round(max(0.0, score - 0.08), 3),
            round(min(1.0, score + 0.08), 3),
        ]
        return {
            "top_evidence": top_evidence,
            "confidence_interval": confidence_interval,
            "attribution": attribution,
        }

    def score_with_evidence(
        self,
        base_signals: Dict[str, bool],
        expected_serial: Optional[str] = None,
        observed_serial: Optional[str] = None,
        image_phash: Optional[str] = None,
        session_data: Optional[Dict] = None,
        case_id: Optional[str] = None,
        top_n: int = 3,
    ) -> Tuple[float, str, Dict[str, bool], Dict[str, Any]]:
        """Like score_with_enrichment but also returns evidence attribution.

        Returns: (score, level, signals, evidence_dict)
        evidence_dict has keys: top_evidence, confidence_interval, attribution
        """
        score, level, signals = self.score_with_enrichment(
            base_signals=base_signals,
            expected_serial=expected_serial,
            observed_serial=observed_serial,
            image_phash=image_phash,
            session_data=session_data,
            case_id=case_id,
        )
        evidence = self.get_top_evidence(signals, top_n=top_n)
        return score, level, signals, evidence

    def to_merchant_dict(self, *, score: float, risk_level: str, signals: Dict[str, bool]) -> Dict[str, Any]:
        from src.app.services.response_normalizer import ResponseNormalizer

        return {
            "score": round(float(score), 4),
            "risk_level": str(risk_level or "minimal"),
            "summary": ResponseNormalizer.fraud_score_to_english(risk_level, score, signals),
            "active_signals": [k for k, v in (signals or {}).items() if v],
        }

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

        # Graph/GNN risk scorer: optional but first-class when enabled.
        try:
            gnn_enabled = str(os.getenv("FRAUD_GNN_ENABLED", "1")).lower() in ("1", "true", "yes")
        except Exception:
            gnn_enabled = False
        if gnn_enabled:
            try:
                from src.app.services.gnn_fraud_detector import predict_fraud_risk

                account_id = str(session_data.get("account_id") or "").strip()
                if account_id:
                    gnn = predict_fraud_risk(account_id)
                    gnn_score = float(getattr(gnn, "gnn_score", 0.0) or 0.0)
                    gnn_high_min = float(os.getenv("FRAUD_GNN_HIGH_RISK_MIN", "0.72") or 0.72)
                    gnn_med_min = float(os.getenv("FRAUD_GNN_MEDIUM_RISK_MIN", "0.55") or 0.55)
                    if gnn_score >= gnn_high_min:
                        signals["gnn_ring_risk_high"] = True
                    elif gnn_score >= gnn_med_min:
                        signals["gnn_ring_risk_medium"] = True
                    if bool(getattr(gnn, "ring_detected", False)):
                        signals["account_device_ip_ring_hit"] = True
                        signals["shipping_address_clustered"] = True
                    session_data["gnn_risk_score"] = round(gnn_score, 4)
                    session_data["gnn_method"] = str(getattr(gnn, "method", "heuristic"))
                    session_data["gnn_ring_detected"] = bool(getattr(gnn, "ring_detected", False))
                    session_data["gnn_explanation"] = str(getattr(gnn, "explanation", ""))[:400]
            except Exception:
                pass

        # Historical anomaly detection over merchant/session series.
        try:
            from src.app.services.anomaly_detector import AnomalyDetector

            detector = AnomalyDetector()
            histories = self._extract_histories(session_data)
            latest_metrics = {
                domain: float(values[-1])
                for domain, values in histories.items()
                if isinstance(values, list) and values
            }
            anomalies = detector.detect_metrics(latest_metrics, histories=histories)
            if anomalies:
                top = max(anomalies, key=lambda item: float(item.confidence))
                if float(top.confidence) >= 0.7:
                    signals["behavioral_anomaly_high"] = True
                else:
                    signals["behavioral_anomaly_medium"] = True
                session_data["anomaly_summary"] = {
                    "count": len(anomalies),
                    "top_severity": top.severity,
                    "summary": "; ".join(
                        str(a.plain_english or "").strip()
                        for a in anomalies[:3]
                        if str(a.plain_english or "").strip()
                    )[:600],
                    "results": [a.to_dict() for a in anomalies[:5]],
                }
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
                elif _is_public_ip(source_ip):
                    signals["geoip_lookup_unavailable"] = True
            # Mid-session country change
            prev_country = str(session_data.get("previous_ip_country") or "").upper()
            curr_country = str(session_data.get("ip_country") or "").upper()
            if prev_country and curr_country and prev_country != curr_country:
                signals["mid_session_country_change"] = True
        except (ImportError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("fraud_scorer.geoip_enrichment_failed: %s", exc)
            source_ip = str(session_data.get("ip") or session_data.get("source_ip") or "")
            if _is_public_ip(source_ip):
                signals["geoip_lookup_unavailable"] = True

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

    @staticmethod
    def _extract_histories(session_data: Dict[str, Any]) -> Dict[str, List[float]]:
        key_map = {
            "purchase_velocity": [
                "purchase_velocity_series",
                "purchases_last_hour_series",
            ],
            "refund_rate": [
                "refund_rate_series",
                "returns_rate_series",
            ],
            "ip_velocity": [
                "ip_velocity_series",
                "ip_velocity_per_hour_series",
            ],
            "chargeback_rate": [
                "chargeback_rate_series",
            ],
        }
        out: Dict[str, List[float]] = {}
        for domain, keys in key_map.items():
            for key in keys:
                raw = session_data.get(key)
                if isinstance(raw, list):
                    vals: List[float] = []
                    for item in raw:
                        try:
                            vals.append(float(item))
                        except Exception:
                            continue
                    if vals:
                        out[domain] = vals
                        break
        # Promote current point into a short series when only a current value is available.
        scalar_fallbacks = {
            "purchase_velocity": session_data.get("purchases_last_hour"),
            "ip_velocity": session_data.get("ip_velocity_per_hour"),
        }
        for domain, raw in scalar_fallbacks.items():
            if domain in out:
                continue
            try:
                if raw is not None:
                    out[domain] = [float(raw)]
            except Exception:
                continue
        return out
