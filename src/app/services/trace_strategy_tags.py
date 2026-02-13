from __future__ import annotations

import os
import re
from typing import Any, Dict, List


def _uniq(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        val = str(item or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _is_non_english_signal(query: str, locale: str | None) -> bool:
    q = str(query or "")
    if locale and str(locale).lower() not in ("en", "en-us", "en-gb"):
        return True
    # Light heuristic for demo tagging; not used for policy decisions.
    if bool(re.search(r"[^\x00-\x7F]", q)):
        return True
    common_non_en = ("hola", "gracias", "bonjour", "merci", "hola", "como", "precio", "ordenador", "portatil")
    ql = q.lower()
    return any(tok in ql for tok in common_non_en)


def build_strategy_trace_correlation(
    *,
    query: str,
    nlp: Dict[str, Any] | None,
    constraints: Dict[str, Any] | None,
    context: Dict[str, Any] | None,
    flags: Dict[str, Any] | None,
) -> Dict[str, Any]:
    nlp = nlp or {}
    constraints = constraints or {}
    context = context or {}
    flags = flags or {}
    kv = (context.get("kv") if isinstance(context.get("kv"), dict) else {}) or {}

    tags: List[str] = []
    hidden: Dict[str, Any] = {
        "domains": {},
        "reasoning": {},
    }

    intent = str(nlp.get("intent") or "")
    intent_conf = float(nlp.get("intent_confidence") or 0.0)
    entities = nlp.get("entities") if isinstance(nlp.get("entities"), dict) else {}
    slots = nlp.get("slots") if isinstance(nlp.get("slots"), dict) else {}
    use_case = entities.get("use_case") or (nlp.get("preferences") or {}).get("use_case")
    locale = constraints.get("locale") or kv.get("locale")

    # NLU quality + entity extraction depth.
    tags.append("nlu:intent_present" if intent else "nlu:intent_missing")
    tags.append("nlu:intent_conf_high" if intent_conf >= 0.75 else ("nlu:intent_conf_medium" if intent_conf >= 0.45 else "nlu:intent_conf_low"))
    if constraints.get("budget_min") is not None or constraints.get("budget_max") is not None:
        tags.append("nlu:entity_budget")
    if constraints.get("brands"):
        tags.append("nlu:entity_brand")
    if constraints.get("specs"):
        tags.append("nlu:entity_specs")
    if use_case:
        tags.append("nlu:entity_use_case")
    hidden["domains"]["nlu"] = {
        "intent": intent or None,
        "intent_confidence": intent_conf,
        "entity_count": len([k for k in ("budget_min", "budget_max", "brands", "specs") if constraints.get(k)]),
        "slot_keys": sorted(list(slots.keys()))[:20],
    }

    # Lifecycle personalization (new/repeat/high-ltv) for upsell timing context.
    total_orders = int(kv.get("total_orders") or 0)
    ltv_cents = int(kv.get("lifetime_value_cents") or kv.get("ltv_cents") or 0)
    if total_orders <= 1:
        tags.append("lifecycle:new_user")
        lifecycle = "new_user"
    else:
        tags.append("lifecycle:repeat_user")
        lifecycle = "repeat_user"
    if ltv_cents >= 300000:
        tags.append("lifecycle:high_ltv")
    hidden["domains"]["lifecycle"] = {
        "segment": lifecycle,
        "total_orders": total_orders,
        "lifetime_value_cents": ltv_cents,
    }

    # Payment expansion signals from enabled providers.
    caps = flags.get("CAPABILITIES") if isinstance(flags.get("CAPABILITIES"), dict) else {}
    payment_caps = ["paypal", "revolut", "googlepay", "afterpay"]
    enabled = [p for p in payment_caps if bool((caps.get(p) or {}).get("enabled"))]
    tags.append("payments:multi_provider" if len(enabled) >= 2 else "payments:single_provider")
    hidden["domains"]["payments"] = {
        "enabled_providers": enabled,
        "enabled_count": len(enabled),
        "provider_concentration_risk": "high" if len(enabled) <= 1 else ("medium" if len(enabled) == 2 else "low"),
    }

    # i18n readiness signals.
    non_en = _is_non_english_signal(query, locale)
    tags.append("i18n:non_english_traffic_detected" if non_en else "i18n:english_path")
    hidden["domains"]["i18n"] = {
        "locale": locale,
        "non_english_detected": non_en,
        "query_len": len(str(query or "")),
    }

    # Supply-chain integrity (SLSA posture) signals.
    slsa_level = str(os.getenv("SLSA_LEVEL", "") or "").strip()
    if slsa_level:
        tags.append(f"slsa:level_{slsa_level}")
    else:
        tags.append("slsa:level_unknown")
    hidden["domains"]["slsa"] = {
        "slsa_level": slsa_level or None,
        "sbom_ready_signal": bool(os.getenv("SBOM_PATH") or os.path.exists("sbom.json")),
    }

    # Platform-readiness tags user asked to correlate in trace drilldown.
    if bool(os.getenv("REDIS_URL")):
        tags.append("platform:caching_partial")
    if bool(os.getenv("RQ_REDIS_URL") or os.getenv("REDIS_URL")):
        tags.append("platform:async_partial")
    tags.append("platform:zero_trust_not_done")
    tags.append("platform:advanced_anomaly_partial")
    tags.append("platform:chaos_partial")
    tags.append("platform:observability_slo_partial")
    tags.append("platform:ai_act_partial")
    hidden["domains"]["platform_readiness"] = {
        "caching": "partial",
        "async_processing": "partial",
        "zero_trust": "not_done",
        "advanced_anomaly_detection": "partial",
        "chaos_engineering": "partial",
        "observability_slo": "partial",
        "ai_act": "partial",
    }

    tags = _uniq(tags)
    hidden["reasoning"]["summary"] = (
        "Tags correlate NLU extraction quality, lifecycle segment, payment diversity, i18n signals, "
        "supply-chain integrity posture, and platform-readiness gaps for decision-trace drilldown."
    )
    return {"tags": tags, "hidden": hidden}

