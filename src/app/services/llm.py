from __future__ import annotations

import json
import subprocess
import time
import os
import httpx
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.app.config import get_settings
from src.app.services.token_budget import TokenBudget, estimate_tokens
from src.app.deps import get_redis
from src.app.security.agent_events import AgentInteractionType, log_agent_security_event
from src.app.security.supply_chain import SupplyChainMonitor
from src.app.observability.metrics import record_llm_usage, record_llm_fallback
from src.app.services.secrets_manager import get_secret
from src.app.services.decision_log import log_trace_event
from src.app.rules.tenant_config_store import TenantConfigStore


_ROUTING_EVENTS_LOCK = threading.Lock()
_ROUTING_EVENTS = deque(maxlen=max(1000, int(os.getenv("LLM_ROUTING_EVENTS_MAX", "5000") or 5000)))


def _record_routing_event(
    *,
    provider: str,
    model: str | None,
    status: str,
    retries: int,
    backoff_ms: int,
    tier: str | None = None,
    tenant_id: str | None = None,
) -> None:
    try:
        with _ROUTING_EVENTS_LOCK:
            _ROUTING_EVENTS.append(
                {
                    "ts": time.time(),
                    "provider": str(provider or "unknown"),
                    "model": str(model or ""),
                    "status": str(status or "unknown"),
                    "retries": int(retries or 0),
                    "backoff_ms": int(backoff_ms or 0),
                    "tier": str(tier or ""),
                    "tenant_id": str(tenant_id or ""),
                }
            )
    except Exception:
        pass


def get_llm_routing_metrics(*, window_minutes: int = 60, tenant_id: str | None = None) -> Dict[str, Any]:
    window_minutes = max(1, min(int(window_minutes or 60), 24 * 60))
    cutoff = time.time() - (window_minutes * 60)
    tenant_filter = str(tenant_id or "").strip()
    rows: List[Dict[str, Any]] = []
    try:
        with _ROUTING_EVENTS_LOCK:
            for ev in list(_ROUTING_EVENTS):
                try:
                    if float(ev.get("ts") or 0.0) < cutoff:
                        continue
                    if tenant_filter:
                        ev_tid = str(ev.get("tenant_id") or "")
                        if ev_tid != tenant_filter:
                            continue
                    rows.append(dict(ev))
                except Exception:
                    continue
    except Exception:
        rows = []
    by_provider: Dict[str, Dict[str, Any]] = {}
    for ev in rows:
        p = str(ev.get("provider") or "unknown")
        cur = by_provider.setdefault(
            p,
            {"provider": p, "attempts": 0, "success": 0, "failed": 0, "retry_events": 0, "avg_backoff_ms": 0.0, "max_backoff_ms": 0},
        )
        cur["attempts"] += 1
        if ev.get("status") == "success":
            cur["success"] += 1
        elif ev.get("status") == "failed":
            cur["failed"] += 1
        if int(ev.get("retries") or 0) > 0:
            cur["retry_events"] += 1
        b = int(ev.get("backoff_ms") or 0)
        cur["avg_backoff_ms"] += float(b)
        cur["max_backoff_ms"] = max(int(cur["max_backoff_ms"] or 0), b)
    for p, cur in by_provider.items():
        at = int(cur["attempts"] or 0)
        cur["success_rate"] = (float(cur["success"]) / float(at)) if at > 0 else None
        cur["avg_backoff_ms"] = (float(cur["avg_backoff_ms"]) / float(at)) if at > 0 else 0.0

    # Compact time-series for dashboard sparkline/trend widgets.
    total_sec = max(60, int(window_minutes * 60))
    bucket_sec = max(60, total_sec // 24)
    start_ts = int(cutoff)
    buckets: Dict[int, Dict[str, Any]] = {}
    for ev in rows:
        try:
            ts = int(float(ev.get("ts") or 0.0))
        except Exception:
            ts = 0
        b = ((ts - start_ts) // bucket_sec) * bucket_sec + start_ts
        cur = buckets.setdefault(
            b,
            {
                "bucket_ts": b,
                "attempts": 0,
                "retry_events": 0,
                "backoff_ms_sum": 0.0,
                "max_backoff_ms": 0,
            },
        )
        cur["attempts"] += 1
        if int(ev.get("retries") or 0) > 0:
            cur["retry_events"] += 1
        backoff = int(ev.get("backoff_ms") or 0)
        cur["backoff_ms_sum"] += float(backoff)
        cur["max_backoff_ms"] = max(int(cur["max_backoff_ms"] or 0), backoff)
    series = []
    for b in sorted(buckets.keys()):
        cur = buckets[b]
        attempts = int(cur.get("attempts") or 0)
        avg_backoff = (float(cur.get("backoff_ms_sum") or 0.0) / float(max(attempts, 1))) if attempts > 0 else 0.0
        series.append(
            {
                "bucket_ts": b,
                "attempts": attempts,
                "retry_events": int(cur.get("retry_events") or 0),
                "avg_backoff_ms": avg_backoff,
                "max_backoff_ms": int(cur.get("max_backoff_ms") or 0),
            }
        )
    return {
        "window_minutes": window_minutes,
        "tenant_id": tenant_filter or None,
        "totals": {"attempts": len(rows), "providers": len(by_provider), "bucket_seconds": bucket_sec},
        "by_provider": sorted(by_provider.values(), key=lambda x: int(x.get("attempts") or 0), reverse=True),
        "series": series,
    }


@dataclass
class LLMResult:
    output: Dict[str, Any]
    tokens_prompt: int
    tokens_completion: int
    duration_seconds: float


class LLMProviderClient:
    def __init__(self, provider: str, model: str, api_key: str):
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key

    def _call_ollama_cli(self, model: str, prompt: str, timeout: int = 15) -> Optional[str]:
        """Call the local `ollama` CLI if available and return stdout text, else None."""
        try:
            # Use the ollama CLI: `ollama run <model> --prompt '<prompt>'`
            cmd: List[str] = ["ollama", "run", model, "--prompt", prompt]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if proc.returncode == 0:
                return proc.stdout.strip()
        except FileNotFoundError:
            # ollama CLI not installed
            return None
        except Exception:
            return None
        return None

    def rerank(self, candidates: list[Dict[str, Any]], constraints: Dict[str, Any], uid: str | None = None, trace_id: str | None = None) -> LLMResult:
        one = self.rerank_once(
            candidates,
            constraints,
            uid=uid,
            provider=(self.provider or "unknown"),
            model=(self.model or ""),
            allow_stub_fallback=True,
            trace_id=trace_id,
        )
        if one is not None:
            return one
        # Fallback: original deterministic local stub scoring
        # Compute simple scores mirroring RecommendationService.rerank
        t0 = time.perf_counter()
        def score(c: Dict[str, Any]) -> float:
            s = 0.0
            if (c.get("stock") or 0) > 0:
                s += 10.0
            price = c.get("price_cents", 0)
            budget = constraints.get("budget_max")
            if budget:
                if price <= budget:
                    s += 5.0
                    s += max(0.0, (budget - price) / max(budget, 1)) * 2.0
                else:
                    s -= 5.0
            brands = constraints.get("brands") or []
            if brands:
                name = (c.get("name") or "").lower()
                sku = (c.get("sku") or "").lower()
                if any(b in name or b in sku for b in brands):
                    s += 3.0
            return s

        ranked = sorted(candidates, key=score, reverse=True)
        # Token accounting: approximate by characters/4 for prompt and completion
        prompt_chars = sum(len((c.get("name") or "")) for c in candidates) + len(str(constraints))
        completion_chars = sum(len((c.get("name") or "")) for c in ranked[:3])
        prompt_tokens = max(1, prompt_chars // 4)
        completion_tokens = max(1, completion_chars // 4)
        dt = time.perf_counter() - t0
        return LLMResult(output={"ranked": ranked, "rationale": "LLM reranked candidates."}, tokens_prompt=prompt_tokens, tokens_completion=completion_tokens, duration_seconds=dt)

    def rerank_once(
        self,
        candidates: list[Dict[str, Any]],
        constraints: Dict[str, Any],
        *,
        uid: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        allow_stub_fallback: bool = False,
        trace_id: str | None = None,
        tier: str | None = None,
        tenant_id: str | None = None,
    ) -> LLMResult | None:
        t0 = time.perf_counter()
        provider = str(provider or self.provider or "").lower()
        model = model or self.model
        try:
            brief_candidates = [{"sku": c.get("sku"), "name": c.get("name"), "price_cents": c.get("price_cents")} for c in candidates]
            prompt_obj = {
                "instruction": "Rerank the candidates in order. Return JSON {\"ranked_skus\": [<sku>], \"rationale\": \"...\" }.",
                "candidates": brief_candidates,
                "constraints": constraints,
            }
            system_msg = "You are a deterministic reranker. Only reorder provided SKUs; do not invent SKUs. Return a single JSON object."
            resp_text = None
            if provider in ("openai", "openai_chat", "api", "anthropic"):
                resp_text = self._call_api_provider(
                    prompt_obj,
                    system=system_msg,
                    uid=uid,
                    provider_override=provider,
                    model_override=model,
                    tenant_id=tenant_id,
                    tier=tier,
                )
            elif provider == "ollama":
                prompt = json.dumps(prompt_obj, ensure_ascii=False)
                resp_text = self._call_ollama_cli(model or self.model, prompt)
            if resp_text:
                start = resp_text.find("{")
                j = json.loads(resp_text[start:] if start != -1 else resp_text)
                ranked_skus = j.get("ranked_skus") or j.get("ranked") or []
                sku_map = {c.get("sku"): c for c in candidates}
                ranked = [sku_map[s] for s in ranked_skus if s in sku_map]
                if ranked:
                    prompt_tokens = max(1, len(str(prompt_obj)) // 4)
                    completion_tokens = max(1, sum(len(str(x.get("name") or "")) for x in ranked) // 4)
                    dt = time.perf_counter() - t0
                    try:
                        if provider == "ollama":
                            _record_routing_event(
                                provider=provider,
                                model=model,
                                status="success",
                                retries=0,
                                backoff_ms=0,
                                tier=tier,
                                tenant_id=tenant_id,
                            )
                        log_trace_event(
                            trace_id=trace_id,
                            event_type="feedback_loop",
                            source_type="llm_router",
                            source_id=provider or "unknown",
                            target_type=None,
                            target_id=None,
                            payload={
                                "kind": "llm_rerank_attempt",
                                "provider": provider,
                                "model": model,
                                "status": "success",
                                "latency_ms": int(dt * 1000),
                            },
                        )
                    except Exception:
                        pass
                    return LLMResult(
                        output={"ranked": ranked, "rationale": j.get("rationale", f"{provider} rerank")},
                        tokens_prompt=prompt_tokens,
                        tokens_completion=completion_tokens,
                        duration_seconds=dt,
                    )
        except Exception as exc:
            try:
                if provider == "ollama":
                    _record_routing_event(
                        provider=provider,
                        model=model,
                        status="failed",
                        retries=0,
                        backoff_ms=0,
                        tier=tier,
                        tenant_id=tenant_id,
                    )
                log_trace_event(
                    trace_id=trace_id,
                    event_type="feedback_loop",
                    source_type="llm_router",
                    source_id=provider or "unknown",
                    target_type=None,
                    target_id=None,
                    payload={
                        "kind": "llm_rerank_attempt",
                        "provider": provider,
                        "model": model,
                        "status": "failed",
                        "error": str(exc),
                    },
                )
            except Exception:
                pass
            if not allow_stub_fallback:
                return None
        if not allow_stub_fallback:
            return None
        return None

    def _call_api_provider(
        self,
        prompt_obj: Dict[str, Any],
        system: str | None = None,
        uid: str | None = None,
        provider_override: str | None = None,
        model_override: str | None = None,
        tenant_id: str | None = None,
        tier: str | None = None,
    ) -> str | None:
        """Call an external API-backed LLM provider (OpenAI-like) with retries and basic cost/rate safeguards.

        Returns text response or None on failure. This is intentionally conservative.
        """
        provider = str(provider_override or self.provider or "openai").lower()
        if provider == "anthropic":
            return self._call_anthropic_provider(prompt_obj, system=system, uid=uid, model_override=model_override, tenant_id=tenant_id, tier=tier)
        api_key = get_secret("OPENAI_API_KEY") or self.api_key or get_secret("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if not api_key:
            return None
        base = get_secret("OPENAI_API_BASE", "https://api.openai.com/v1") or os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        url = f"{base.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        # Construct a deterministic prompt
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": json.dumps(prompt_obj, ensure_ascii=False)})
        payload = {
            "model": model_override or self.model or os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 512,
        }
        # Estimate tokens for a conservative pre-check
        try:
            est = estimate_tokens(json.dumps(prompt_obj, ensure_ascii=False), response_tokens=payload.get("max_tokens", 512))
        except Exception:
            est = None
        # If a uid is provided, perform a budget check before performing the network call
        try:
            if uid and est is not None:
                tb = TokenBudget(get_redis())
                ok, _reason, _remain = tb.check_budget(uid, tier="guest", estimated_tokens=est)
                if not ok:
                    return None
        except Exception:
            # If budget check fails unexpectedly, be conservative and abort the call
            return None
        backoffs = [0.5, 1.0, 2.0]
        retries = 0
        backoff_ms_total = 0
        for wait in backoffs:
            try:
                with httpx.Client(timeout=20.0) as client:
                    r = client.post(url, json=payload, headers=headers)
                    if r.status_code == 429:
                        # Rate limited — wait and retry
                        retries += 1
                        backoff_ms_total += int(wait * 1000)
                        time.sleep(wait)
                        continue
                    r.raise_for_status()
                    data = r.json()
                    # Attempt to extract assistant content
                    choices = data.get("choices") or []
                    if choices:
                        msg = choices[0].get("message") or choices[0]
                        out_text = (msg.get("content") if isinstance(msg, dict) else str(msg)) or None
                        # Record usage after success when possible
                        try:
                            if uid:
                                usage = data.get("usage") or {}
                                prompt_t = int(usage.get("prompt_tokens") or est or 0)
                                completion_t = int(usage.get("completion_tokens") or 0)
                                used = prompt_t + completion_t
                                try:
                                    tb = TokenBudget(get_redis())
                                    tb.record_usage(uid, tokens=used, cost=0.0)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        _record_routing_event(
                            provider=provider,
                            model=(payload.get("model") or self.model),
                            status="success",
                            retries=retries,
                            backoff_ms=backoff_ms_total,
                            tier=tier,
                            tenant_id=tenant_id,
                        )
                        return out_text
                    # Fallback: return top-level text (and attempt to record usage)
                    out_text = str(data.get("text") or data.get("response") or "")
                    try:
                        if uid:
                            usage = data.get("usage") or {}
                            prompt_t = int(usage.get("prompt_tokens") or est or 0)
                            completion_t = int(usage.get("completion_tokens") or 0)
                            used = prompt_t + completion_t
                            try:
                                tb = TokenBudget(get_redis())
                                tb.record_usage(uid, tokens=used, cost=0.0)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    _record_routing_event(
                        provider=provider,
                        model=(payload.get("model") or self.model),
                        status="success",
                        retries=retries,
                        backoff_ms=backoff_ms_total,
                        tier=tier,
                        tenant_id=tenant_id,
                    )
                    return out_text
            except Exception:
                retries += 1
                backoff_ms_total += int(wait * 1000)
                time.sleep(wait)
                continue
        _record_routing_event(
            provider=provider,
            model=(payload.get("model") or self.model),
            status="failed",
            retries=retries,
            backoff_ms=backoff_ms_total,
            tier=tier,
            tenant_id=tenant_id,
        )
        return None

    def _call_anthropic_provider(
        self,
        prompt_obj: Dict[str, Any],
        *,
        system: str | None = None,
        uid: str | None = None,
        model_override: str | None = None,
        tenant_id: str | None = None,
        tier: str | None = None,
    ) -> str | None:
        api_key = (
            get_secret("ANTHROPIC_API_KEY")
            or get_secret("LLM_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("LLM_API_KEY")
        )
        if not api_key:
            return None
        base = get_secret("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1") or os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1")
        url = f"{base.rstrip('/')}/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
            "content-type": "application/json",
        }
        user_content = json.dumps(prompt_obj, ensure_ascii=False)
        payload = {
            "model": model_override or os.getenv("ANTHROPIC_MODEL") or self.model or "claude-3-5-sonnet-latest",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": user_content}],
        }
        if system:
            payload["system"] = system
        try:
            est = estimate_tokens(user_content, response_tokens=payload.get("max_tokens", 512))
        except Exception:
            est = None
        try:
            if uid and est is not None:
                tb = TokenBudget(get_redis())
                ok, _reason, _remain = tb.check_budget(uid, tier="guest", estimated_tokens=est)
                if not ok:
                    return None
        except Exception:
            return None
        backoffs = [0.5, 1.0, 2.0]
        retries = 0
        backoff_ms_total = 0
        for wait in backoffs:
            try:
                with httpx.Client(timeout=20.0) as client:
                    r = client.post(url, json=payload, headers=headers)
                    if r.status_code == 429:
                        retries += 1
                        backoff_ms_total += int(wait * 1000)
                        time.sleep(wait)
                        continue
                    r.raise_for_status()
                    data = r.json()
                    text_out = ""
                    for item in (data.get("content") or []):
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_out += str(item.get("text") or "")
                    if uid:
                        try:
                            usage = data.get("usage") or {}
                            prompt_t = int(usage.get("input_tokens") or est or 0)
                            completion_t = int(usage.get("output_tokens") or 0)
                            tb = TokenBudget(get_redis())
                            tb.record_usage(uid, tokens=(prompt_t + completion_t), cost=0.0)
                        except Exception:
                            pass
                    _record_routing_event(
                        provider="anthropic",
                        model=str(payload.get("model") or ""),
                        status="success",
                        retries=retries,
                        backoff_ms=backoff_ms_total,
                        tier=tier,
                        tenant_id=tenant_id,
                    )
                    return text_out or None
            except Exception:
                retries += 1
                backoff_ms_total += int(wait * 1000)
                time.sleep(wait)
                continue
        _record_routing_event(
            provider="anthropic",
            model=str(payload.get("model") or ""),
            status="failed",
            retries=retries,
            backoff_ms=backoff_ms_total,
            tier=tier,
            tenant_id=tenant_id,
        )
        return None


class LLMOrchestrator:
    def __init__(self):
        s = get_settings()
        self.client = LLMProviderClient(s.llm_provider, s.llm_model, s.openai_api_key)
        self.budget = TokenBudget(get_redis())
        self.supply_chain = SupplyChainMonitor()
        try:
            self.tenant_config = TenantConfigStore(cache_ttl=5)
        except Exception:
            self.tenant_config = None

    def _routing_policy_for_tenant(self, tenant_id: str | None) -> Dict[str, Any]:
        policy: Dict[str, Any] = {}
        try:
            if self.tenant_config is not None:
                base = self.tenant_config.get_override("llm_routing_policy", tenant_id=None)
                if isinstance(base, dict):
                    policy.update(base)
                if tenant_id:
                    ov = self.tenant_config.get_override("llm_routing_policy", tenant_id=str(tenant_id))
                    if isinstance(ov, dict):
                        policy.update(ov)
        except Exception:
            pass
        return policy

    def rerank_with_budget(self, uid: str, candidates: list[Dict[str, Any]], constraints: Dict[str, Any]) -> list[Dict[str, Any]]:
        # Enforce a simple daily budget per user
        est_tokens = estimate_tokens(str(constraints), response_tokens=500)
        ok, _reason, _remain = self.budget.check_budget(uid, tier="guest", estimated_tokens=est_tokens)
        if not ok:
            return candidates
        provider = self.client.provider or "unknown"
        try:
            self.supply_chain.check_endpoint_integrity(provider)
        except Exception:
            pass
        res = self.client.rerank(candidates, constraints)
        used = res.tokens_prompt + res.tokens_completion
        self.budget.record_usage(uid, tokens=used, cost=0.0)
        try:
            record_llm_usage(self.client.model or "unknown", "standard", "rerank_with_budget", used, res.duration_seconds)
        except Exception:
            pass
        try:
            log_agent_security_event(
                interaction_type=AgentInteractionType.llm_api_call,
                source=uid,
                destination=provider,
                threat_category=None,
                severity="info",
                confidence=0.2,
                details={
                    "model": self.client.model,
                    "tokens_prompt": res.tokens_prompt,
                    "tokens_completion": res.tokens_completion,
                    "duration_seconds": res.duration_seconds,
                },
                requires_escalation=False,
            )
            self.supply_chain.detect_response_anomaly(provider, res.output or {})
        except Exception:
            pass
        return res.output.get("ranked") or candidates

    def _select_tier(self, confidence: float | None) -> str:
        try:
            if confidence is None:
                return os.getenv("LLM_DEFAULT_TIER", "standard")
            t_high = float(os.getenv("LLM_TIER_THRESHOLD_HIGH", "0.8"))
            t_mid = float(os.getenv("LLM_TIER_THRESHOLD_MID", "0.5"))
            if confidence >= t_high:
                return "premium"
            if confidence >= t_mid:
                return "standard"
            return "cheap"
        except Exception:
            return "standard"

    def rerank_tiered(
        self,
        uid: str,
        candidates: list[Dict[str, Any]],
        constraints: Dict[str, Any],
        confidence: float | None = None,
        tenant_id: str | None = None,
    ) -> list[Dict[str, Any]]:
        tier = self._select_tier(confidence)
        tenant_id = tenant_id or (constraints.get("tenant_id") if isinstance(constraints, dict) else None)
        routing_policy = self._routing_policy_for_tenant(str(tenant_id) if tenant_id else None)
        est_tokens = estimate_tokens(str(constraints), response_tokens=500)
        ok, _reason, _remain = self.budget.check_budget(uid, tier=tier, estimated_tokens=est_tokens)
        if not ok:
            try:
                record_llm_fallback("budget_check", "rules", "budget_denied")
            except Exception:
                pass
            return candidates
        # Choose model/provider per tier
        model_map = {
            "cheap": os.getenv("LLM_MODEL_TIER_CHEAP", "gpt-4o-mini"),
            "standard": os.getenv("LLM_MODEL_TIER_STANDARD", os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o")),
            "premium": os.getenv("LLM_MODEL_TIER_PREMIUM", "gpt-4.1")
        }
        provider_map = {
            "cheap": os.getenv("LLM_PROVIDER_TIER_CHEAP", self.client.provider or "openai"),
            "standard": os.getenv("LLM_PROVIDER_TIER_STANDARD", self.client.provider or "openai"),
            "premium": os.getenv("LLM_PROVIDER_TIER_PREMIUM", self.client.provider or "openai"),
        }
        try:
            pm = routing_policy.get("providers") if isinstance(routing_policy.get("providers"), dict) else {}
            mm = routing_policy.get("models") if isinstance(routing_policy.get("models"), dict) else {}
            if tier in pm and isinstance(pm.get(tier), str):
                provider_map[tier] = pm.get(tier)
            if tier in mm and isinstance(mm.get(tier), dict):
                md = mm.get(tier) or {}
                # optional default model override by tier
                if isinstance(md.get("default"), str):
                    model_map[tier] = md.get("default")
        except Exception:
            pass
        fallback_defaults = {
            "cheap": "ollama,openai",
            "standard": "openai,anthropic,ollama",
            "premium": "anthropic,openai,ollama",
        }
        fallback_env = os.getenv(f"LLM_PROVIDER_FALLBACK_{tier.upper()}", fallback_defaults.get(tier, "openai,ollama"))
        try:
            fb = routing_policy.get("fallback") if isinstance(routing_policy.get("fallback"), dict) else {}
            if tier in fb and isinstance(fb.get(tier), list) and fb.get(tier):
                fallback_env = ",".join([str(x) for x in fb.get(tier) if x])
        except Exception:
            pass
        provider_chain = [p.strip().lower() for p in str(fallback_env or "").split(",") if p.strip()]
        primary_provider = str(provider_map.get(tier, self.client.provider or "openai")).lower()
        if primary_provider and primary_provider not in provider_chain:
            provider_chain.insert(0, primary_provider)
        prev_provider, prev_model = self.client.provider, self.client.model
        try:
            # Integrity checks
            res = None
            for prov in provider_chain or [primary_provider]:
                model = model_map.get(tier, prev_model)
                if prov == "anthropic":
                    model = os.getenv(f"LLM_MODEL_{tier.upper()}_ANTHROPIC", os.getenv("ANTHROPIC_MODEL", model))
                elif prov == "ollama":
                    model = os.getenv(f"LLM_MODEL_{tier.upper()}_OLLAMA", os.getenv("OLLAMA_BIG_MODEL", model))
                else:
                    model = os.getenv(f"LLM_MODEL_{tier.upper()}_OPENAI", model)
                try:
                    mm = routing_policy.get("models") if isinstance(routing_policy.get("models"), dict) else {}
                    mt = mm.get(tier) if isinstance(mm.get(tier), dict) else {}
                    if isinstance(mt.get(prov), str):
                        model = mt.get(prov)
                except Exception:
                    pass
                try:
                    self.supply_chain.check_endpoint_integrity(prov)
                except Exception:
                    pass
                try:
                    log_trace_event(
                        trace_id=None,
                        event_type="feedback_loop",
                        source_type="llm_router",
                        source_id=prov,
                        target_type=None,
                        target_id=None,
                        payload={"kind": "tiered_attempt", "tier": tier, "provider": prov, "model": model},
                    )
                except Exception:
                    pass
                res = self.client.rerank_once(
                    candidates,
                    constraints,
                    uid=uid,
                    provider=prov,
                    model=model,
                    allow_stub_fallback=False,
                    trace_id=None,
                    tier=tier,
                    tenant_id=str(tenant_id) if tenant_id else None,
                )
                if res is not None:
                    self.client.provider, self.client.model = prov, model
                    break
            if res is None:
                self.client.provider = primary_provider
                self.client.model = model_map.get(tier, prev_model)
                res = self.client.rerank(candidates, constraints, uid=uid, trace_id=None)
            used = res.tokens_prompt + res.tokens_completion
            self.budget.record_usage(uid, tokens=used, cost=0.0)
            try:
                record_llm_usage(self.client.model or "unknown", tier, "rerank_tiered", used, res.duration_seconds)
            except Exception:
                pass
            try:
                log_agent_security_event(
                    interaction_type=AgentInteractionType.llm_api_call,
                    source=uid,
                    destination=self.client.provider,
                    threat_category=None,
                    severity="info",
                    confidence=float(confidence or 0.0),
                    details={
                        "tier": tier,
                        "model": self.client.model,
                        "tokens_prompt": res.tokens_prompt,
                        "tokens_completion": res.tokens_completion,
                        "duration_seconds": res.duration_seconds,
                    },
                    requires_escalation=False,
                )
                self.supply_chain.detect_response_anomaly(self.client.provider, res.output or {})
            except Exception:
                pass
            return res.output.get("ranked") or candidates
        finally:
            # Restore original client configuration
            self.client.provider, self.client.model = prev_provider, prev_model

    def _extract_json(self, text: str) -> Dict[str, Any] | None:
        if not text:
            return None
        try:
            start = text.find("{")
            if start == -1:
                return None
            frag = text[start:]
            return json.loads(frag)
        except Exception:
            try:
                return json.loads(text)
            except Exception:
                return None

    def interleaving_decide_tool(self, uid: str | None, prompt_obj: Dict[str, Any], system: str | None = None) -> Dict[str, Any] | None:
        """Decide the next tool to call for interleaving loops.

        Returns a dict with keys like: next_tool/tool, arguments, stop, confidence, reason.
        """
        # Allow dedicated model/provider overrides for interleaving
        prev_provider, prev_model = self.client.provider, self.client.model
        provider = os.getenv("INTERLEAVING_LLM_PROVIDER", prev_provider or "openai")
        model = os.getenv("INTERLEAVING_LLM_MODEL", prev_model or os.getenv("LLM_MODEL", "gpt-4o-mini"))
        self.client.provider, self.client.model = provider, model
        try:
            chain_raw = os.getenv("INTERLEAVING_LLM_PROVIDER_CHAIN", str(provider or "openai,ollama"))
            chain = [p.strip().lower() for p in chain_raw.split(",") if p.strip()]
            if not chain:
                chain = [str(provider or "openai").lower()]
            for prov in chain:
                out_text = None
                if prov in ("openai", "openai_chat", "anthropic", "api"):
                    out_text = self.client._call_api_provider(
                        prompt_obj,
                        system=system,
                        uid=uid,
                        provider_override=prov,
                        model_override=model,
                    )
                elif prov == "ollama":
                    prompt = json.dumps(prompt_obj, ensure_ascii=False)
                    out_text = self.client._call_ollama_cli(model, prompt)
                parsed = self._extract_json(out_text) if out_text else None
                if parsed is not None:
                    try:
                        log_trace_event(
                            trace_id=None,
                            event_type="feedback_loop",
                            source_type="llm_router",
                            source_id=prov,
                            target_type=None,
                            target_id=None,
                            payload={"kind": "interleaving_decision", "status": "success", "provider": prov, "model": model},
                        )
                    except Exception:
                        pass
                    return parsed
            return None
        finally:
            self.client.provider, self.client.model = prev_provider, prev_model
