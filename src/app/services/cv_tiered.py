from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.app.services.cv_triage_basic import BasicCVTriage
from src.app.services.tier_router import TierRouter
from src.app.services.trace_broker import publish as _publish_trace
from src.app.services.cv_damage_classifier import DamageClassifier
from src.app.services.cv_explain import explain_cv
from src.app.services.image_forensics import ImageForensicsService
from src.app.services.cv_tier2_pipeline import run_tier2
from src.app.services.cv_model_pack import get_model_pack
from src.app.observability.metrics import record_cv_tier, record_cv_processing
from src.app.observability.telemetry import telemetry_emit
from src.app.policy.vertical_pack import load_vertical_pack
from src.app.rules.image_quality import assess_image_quality
from src.app.deps import get_redis
import os
import time
import math


@dataclass
class CVTierDecision:
    tier: int
    reason: str
    model: Optional[str]


class TieredCVProvider:
    """Tiered CV provider that selects a CV analysis strategy based on TierRouter.

    - Tier 0/1: BasicCVTriage (fast, label/text heuristics)
    - Tier 2: Enhanced path (placeholder: currently BasicCVTriage with extra metadata)
    """

    def __init__(self, flags: Dict[str, Any] | None = None):
        self.flags = flags or {}
        # TierRouter also handles cache-first logic when available
        try:
            self.router = TierRouter(cache_backend=None, flags=self.flags)
        except Exception:
            self.router = None
        self.basic = BasicCVTriage()
        self.pack = get_model_pack(self.flags.get("CV_MODEL_PACK"))
        # Prefer pack-defined detector model when governance allows; fallback to flags
        try:
            det_model = None
            det_cfg = self.pack.get("detector") if isinstance(self.pack.get("detector"), dict) else {}
            det_model = det_cfg.get("model")
        except Exception:
            det_model = None
        self.damage_classifier = DamageClassifier(
            model_path=self.flags.get("CV_DAMAGE_MODEL"),
            yolo_model_path=self.flags.get("CV_DAMAGE_YOLO_MODEL") or det_model,
        )
        self.forensics = ImageForensicsService()
        # self.pack already set above

    async def process(self, content: bytes, meta: Dict[str, Any] | None = None, trace_id: str | None = None) -> Dict[str, Any]:
        """Backward-compatible entrypoint used by older callers/tests.

        Parameters:
        - content: raw image bytes
        - meta: optional metadata (e.g., phash)
        - trace_id: optional trace id for emitting trace events

        Returns a standardized dict with tier0/tier1/tier2 summaries and
        `tiered` flag so callers/tests can rely on a stable shape.
        """
        meta = meta or {}
        # Minimal tier0 info
        size_bytes = len(content or b"")
        tier0 = {"size_bytes": size_bytes, "phash": meta.get("phash")}

        # Derive labels/extracted_text naively for the basic analyzer
        labels = []
        extracted_text = ""
        try:
            analysis = await self.analyze(
                labels,
                extracted_text,
                context={"trace_id": trace_id, "image_bytes": content, **(meta or {})},
            )
        except Exception:
            analysis = {}

        # Build a minimal tier2 structure mirroring analysis for compatibility
        tier1 = analysis if isinstance(analysis, dict) else {}
        tier2 = {"reverse_hits": [], "serial": None, "forensics": {}, **(tier1 or {})}

        return {
            "tiered": True,
            "tier0": tier0,
            "tier1": tier1,
            "tier2": tier2,
            "total_latency_ms": 0,
            "escalated": bool(tier1.get("needs_human_review")) if isinstance(tier1, dict) else False,
        }

    async def analyze(self, labels: List[str], extracted_text: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        ctx = context or {}
        intent_result = {"handled": False, "confidence": 1.0}
        security = {"risk_adj": float(ctx.get("risk_adj", 0.0))}
        query = (ctx.get("query") or "").strip().lower()
        image_bytes = ctx.get("image_bytes")
        force_tier2 = bool(ctx.get("force_tier2"))
        query = str(ctx.get("query") or "")
        t0 = __import__("time").perf_counter()

        actor = str(ctx.get("uid") or ctx.get("source_ip") or ctx.get("trace_id") or "anon")[:120]

        def _complexity_score() -> float:
            txt = f"{query} {extracted_text}".strip().lower()
            score = 0.0
            score += min(0.45, len(txt) / 5000.0)
            trigger_terms = ("force tier2", "forensics", "re-run", "retry", "bypass", "override", "urgent")
            score += 0.07 * sum(1 for t in trigger_terms if t in txt)
            score += 0.08 if bool(ctx.get("risk_adj", 0.0) and float(ctx.get("risk_adj", 0.0)) > 0.5) else 0.0
            return float(min(1.0, score))

        if force_tier2:
            max_complexity = float(os.getenv("CV_TIER2_FORCE_COMPLEXITY_MAX", "0.75") or 0.75)
            comp = _complexity_score()
            if comp > max_complexity:
                return {
                    "status": "review_required",
                    "tier": 1,
                    "tier_reason": "force_tier2_complexity_ceiling",
                    "needs_human_review": True,
                    "complexity_score": round(comp, 4),
                }

        # Tier0 gate: cheap image quality validation before any heavier work.
        # Off by default unless explicitly enabled via flags/env.
        try:
            t0_enabled = bool(self.flags.get("TIER0_RULES_ENABLED")) or (
                str(__import__("os").getenv("TIER0_RULES_ENABLED", "0")).strip().lower() in ("1", "true", "yes")
            )
        except Exception:
            t0_enabled = False
        if t0_enabled and isinstance(image_bytes, (bytes, bytearray)) and image_bytes:
            try:
                pack_id = str(ctx.get("vertical_pack") or "electronics")
                pack = load_vertical_pack(pack_id)
                iq_min = float(pack.thresholds.get("image_quality_min", 0.6))
            except Exception:
                iq_min = 0.6
            iq = assess_image_quality([("image", bytes(image_bytes))], min_quality_score=iq_min)
            if not iq.ok:
                return {
                    "status": "rejected",
                    "tier": 0,
                    "tier_reason": "image_quality_failed",
                    "confidence": 1.0,
                    "needs_human_review": False,
                    "image_quality": {"score": iq.score, "reasons": iq.reasons, "details": iq.details},
                }

        # Default to Tier 1 when router is unavailable
        tier_dec = None
        if force_tier2:
            tier_dec = CVTierDecision(tier=2, reason="force_tier2", model=self.flags.get("MODEL_T2"))
        elif self.router is not None:
            try:
                tier_dec = self.router.route(query=query, context=ctx, intent_result=intent_result, security_analysis=security)
            except Exception:
                tier_dec = None

        if tier_dec is None:
            # Fallback to Tier 1
            analysis = await self.basic.analyze(labels, extracted_text)
            analysis["tier"] = 1
            analysis["model"] = self.flags.get("MODEL_T1")
            analysis["tier_reason"] = "default"
            try:
                record_cv_tier(1)
                record_cv_processing(1, __import__("time").perf_counter() - t0)
            except Exception:
                pass
            # publish tier decision for realtime trace UX (best-effort)
            try:
                trace_id = (ctx or {}).get("trace_id")
                if trace_id:
                    ev = {
                        "trace_id": trace_id,
                        "event_type": "model_selection",
                        "source_type": "cv_provider",
                        "source_id": "tiered_cv",
                        "payload": {"tier": 1, "model": analysis.get("model"), "reason": "default", "confidence": analysis.get("confidence")},
                    }
                    await _publish_trace(trace_id, ev)
            except Exception:
                pass
            return analysis

        if tier_dec.tier < 2:
            analysis = await self.basic.analyze(labels, extracted_text)
            analysis["tier"] = tier_dec.tier
            analysis["model"] = tier_dec.model or self.flags.get("MODEL_T1")
            analysis["tier_reason"] = tier_dec.reason
            try:
                record_cv_tier(int(analysis.get("tier") or 1))
                record_cv_processing(int(analysis.get("tier") or 1), __import__("time").perf_counter() - t0)
            except Exception:
                pass
            # publish tier decision
            try:
                trace_id = (ctx or {}).get("trace_id")
                if trace_id:
                    ev = {
                        "trace_id": trace_id,
                        "event_type": "model_selection",
                        "source_type": "cv_provider",
                        "source_id": "tiered_cv",
                        "payload": {"tier": analysis.get("tier"), "model": analysis.get("model"), "reason": analysis.get("tier_reason"), "confidence": analysis.get("confidence")},
                    }
                    await _publish_trace(trace_id, ev)
            except Exception:
                pass
            return analysis

        # Tier 2 path: enhanced analysis (damage classifier + forensics + model pack)
        # Budget guard: per-actor hourly cap to avoid Tier2 cost DoS.
        try:
            r = get_redis()
            max_hour = int(os.getenv("CV_TIER2_MAX_PER_HOUR_PER_ACTOR", "10") or 10)
            bucket = int(time.time() // 3600)
            key = f"cv:tier2:actor:{bucket}:{actor}"
            used = int(r.get(key) or 0)
            if used >= max_hour:
                return {
                    "status": "review_required",
                    "tier": 1,
                    "tier_reason": "tier2_budget_exhausted_hitl",
                    "needs_human_review": True,
                    "decision_action": "request_more_data",
                }
            r.incrby(key, 1)
            r.expire(key, 3700)

            # 3-sigma spike monitor against last 24 hourly buckets.
            vals = []
            now_bucket = int(time.time() // 3600)
            for i in range(1, 25):
                vals.append(int(r.get(f"cv:tier2:actor:{now_bucket-i}:{actor}") or 0))
            mean = (sum(vals) / len(vals)) if vals else 0.0
            var = (sum((v - mean) ** 2 for v in vals) / len(vals)) if vals else 0.0
            std = math.sqrt(var)
            current = int(r.get(key) or 0)
            if std > 0 and current > (mean + 3.0 * std) and current >= 6:
                telemetry_emit(
                    {
                        "component": "cv_tier2",
                        "event": "tier2_usage_spike",
                        "actor": actor,
                        "current": current,
                        "baseline_mean": round(mean, 3),
                        "baseline_std": round(std, 3),
                    },
                    severity="warning",
                    sourcetype="shopsquire:security",
                )
        except Exception:
            pass

        enhanced = await self.basic.analyze(labels, extracted_text)
        enhanced["tier"] = 2
        enhanced["model"] = tier_dec.model or self.flags.get("MODEL_T2")
        enhanced["tier_reason"] = tier_dec.reason
        enhanced["needs_human_review"] = True if enhanced.get("confidence", 0.0) < 0.8 else enhanced.get("needs_human_review", False)
        try:
            if isinstance(image_bytes, (bytes, bytearray)) and image_bytes:
                damage = self.damage_classifier.classify(bytes(image_bytes))
                enhanced["damage_classifier"] = damage
        except Exception:
            enhanced["damage_classifier"] = {"error": "damage_classifier_failed"}
        try:
            if isinstance(image_bytes, (bytes, bytearray)) and image_bytes:
                enhanced["forensics"] = self.forensics.analyze_image(bytes(image_bytes))
        except Exception:
            enhanced["forensics"] = {"error": "forensics_failed"}
        try:
            if isinstance(image_bytes, (bytes, bytearray)) and image_bytes:
                tier2 = run_tier2(bytes(image_bytes), meta=ctx, pack_id=self.pack.get("id"))
                enhanced["tier2"] = tier2
                enhanced["evidence_tags"] = tier2.get("evidence_tags") or []
                enhanced["cv_signals"] = tier2.get("signals") or {}
                try:
                    det = (tier2.get("detector") or {}).get("summary") or {}
                    quality_scores = (tier2.get("quality") or {}).get("scores") or {}
                    top_quality = None
                    if isinstance(quality_scores, dict) and quality_scores:
                        top_quality = sorted(quality_scores.items(), key=lambda x: x[1], reverse=True)[:2]
                    enhanced["tier2_summary"] = {
                        "model_pack": tier2.get("model_pack"),
                        "detected": (det.get("unique") or [])[:5],
                        "ocr_provider": (tier2.get("ocr") or {}).get("provider"),
                        "quality_top": top_quality,
                        "manipulation_score": (tier2.get("forensics") or {}).get("manipulation_score"),
                    }
                except Exception:
                    enhanced["tier2_summary"] = {"model_pack": tier2.get("model_pack")}
        except Exception:
            enhanced["tier2"] = {"error": "tier2_failed"}
        # publish tier decision for Tier 2 (escalation)
        # Interpret Tier2 verdict (if present) to set review/decision guidance
        try:
            tier2 = enhanced.get("tier2") or {}
            verdict = tier2.get("verdict") or (tier2.get("forensics") or {}).get("verdict") or None
            # Attach verdict to enhanced response
            enhanced["verdict"] = verdict
            # Deterministic explanation (no LLM) for UI/tickets.
            try:
                enhanced["explanation"] = explain_cv(
                    tier2_summary=enhanced.get("tier2_summary") if isinstance(enhanced.get("tier2_summary"), dict) else None,
                    evidence_tags=enhanced.get("evidence_tags") if isinstance(enhanced.get("evidence_tags"), list) else None,
                    verdict=verdict if isinstance(verdict, dict) else None,
                )
                if isinstance(enhanced.get("explanation"), dict):
                    if enhanced["explanation"].get("risk_band") == "high":
                        enhanced["needs_human_review"] = True
            except Exception:
                pass
            # Decision_action and needs_human_review mapping
            if isinstance(verdict, dict):
                action = verdict.get("verdict")
                enhanced["decision_action"] = action
                if action == "approve":
                    enhanced["needs_human_review"] = False
                elif action == "deny":
                    # Deny is sensitive; escalate for human confirmation by default
                    enhanced["needs_human_review"] = True
                else:
                    # request_more_data or others: stay automated but require follow-up
                    enhanced["needs_human_review"] = False
            else:
                enhanced["decision_action"] = None

            trace_id = (ctx or {}).get("trace_id")
            if trace_id:
                ev = {
                    "trace_id": trace_id,
                    "event_type": "cv_pipeline",
                    "source_type": "cv_provider",
                    "source_id": "tiered_cv",
                    "payload": {
                        "tier": 2,
                        "model": enhanced.get("model"),
                        "reason": enhanced.get("tier_reason"),
                        "confidence": enhanced.get("confidence"),
                        "human_review": enhanced.get("needs_human_review"),
                        "decision_action": enhanced.get("decision_action"),
                        "verdict": verdict,
                        "evidence_tags": enhanced.get("evidence_tags"),
                        "cv_signals": enhanced.get("cv_signals"),
                        "model_pack": (enhanced.get("tier2") or {}).get("model_pack"),
                        "tier2_summary": enhanced.get("tier2_summary"),
                    },
                }
                await _publish_trace(trace_id, ev)
        except Exception:
            pass
        try:
            record_cv_tier(2)
            record_cv_processing(2, __import__("time").perf_counter() - t0)
        except Exception:
            pass
        return enhanced


# Backwards-compatible alias expected by tests/importers
TieredCV = TieredCVProvider
