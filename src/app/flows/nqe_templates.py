from __future__ import annotations

import json
import os
import hashlib
from typing import Any, Dict, List, Optional


# Category-specific template bank files auto-loaded alongside the main file
_CATEGORY_BANK_FILES = [
    "nqe_templates_clothing.json",
    "nqe_templates_kitchen.json",
    "nqe_templates_furniture.json",
    "nqe_templates_tv.json",
    "nqe_templates_phone.json",
]


class TemplateStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("NQE_TEMPLATES_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "config", "nqe_templates.json"))
        self._cache: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
        except Exception:
            self._cache = {"default": {"templates": []}}
        # Auto-load category-specific template banks from same directory
        config_dir = os.path.dirname(self.path)
        for fname in _CATEGORY_BANK_FILES:
            fpath = os.path.join(config_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    bank = json.load(f)
                self._cache.update(bank)
            except FileNotFoundError:
                pass
            except Exception:
                pass

    def _normalize_group(self, group: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(group, dict):
            return {"version": "v1", "default_variant": "control", "variants": {"control": {"templates": []}}}
        # Backward-compat legacy format: {templates: [...]}
        if "templates" in group and "variants" not in group:
            return {
                "version": str(group.get("version") or "v1"),
                "default_variant": "control",
                "variants": {"control": {"templates": list(group.get("templates") or [])}},
            }
        variants = group.get("variants")
        if not isinstance(variants, dict):
            variants = {"control": {"templates": list(group.get("templates") or [])}}
        return {
            "version": str(group.get("version") or "v1"),
            "default_variant": str(group.get("default_variant") or "control"),
            "variants": variants,
        }

    def _select_variant(
        self,
        group: Dict[str, Any],
        *,
        variant: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> str:
        variants = group.get("variants") or {}
        allowed = [str(k) for k in variants.keys()]
        if not allowed:
            return "control"
        if variant and variant in allowed:
            return variant
        env_var = str(os.environ.get("NQE_TEMPLATE_VARIANT", "") or "").strip()
        if env_var and env_var in allowed:
            return env_var
        # Deterministic path for explicit AB governance.
        if str(os.environ.get("NQE_TEMPLATE_VARIANT_MODE", "hash")).strip().lower() == "hash" and trace_id and len(allowed) > 1:
            h = hashlib.sha1(str(trace_id).encode("utf-8")).hexdigest()
            idx = int(h[:8], 16) % len(allowed)
            return allowed[idx]
        default_variant = str(group.get("default_variant") or "control")
        if default_variant in allowed:
            return default_variant
        return allowed[0]

    def get_templates(
        self,
        intent: str,
        product_category: str,
        tenant_id: str | None = None,
        *,
        variant: str | None = None,
        version: str | None = None,
        trace_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        key = tenant_id or "default"
        group_raw = self._cache.get(key) or self._cache.get("default") or {}
        # If the matched group has no templates for this category, try the
        # category-specific bank (e.g. "clothing", "kitchen", "tv")
        if product_category and product_category != "general":
            cat_group = self._cache.get(product_category)
            if cat_group:
                # Prefer category bank when default has no category-matched templates
                group_raw = cat_group
        group = self._normalize_group(group_raw)
        if version and str(version) != str(group.get("version")):
            fallback = self._normalize_group(self._cache.get("default") or {})
            group = fallback
        selected_variant = self._select_variant(group, variant=variant, trace_id=trace_id)
        variants = group.get("variants") or {}
        v_cfg = variants.get(selected_variant) or {}
        items = v_cfg.get("templates") or []
        # Simple filter: match by intent/category if present, else return all
        out = []
        for t in items:
            ti = (t.get("intent") or intent or "").lower()
            pc = (t.get("product_category") or product_category or "").lower()
            if (not t.get("intent") or ti == (intent or "").lower()) and (not t.get("product_category") or pc == (product_category or "").lower()):
                # Ensure required keys
                item = {
                    "id": t.get("id"),
                    "text": t.get("text"),
                    "goal": t.get("goal", "clarify_details"),
                    "evidence_needed": t.get("evidence_needed", ["none"]),
                    "stop_condition": t.get("stop_condition"),
                    "source": t.get("source", "template"),
                    "variant": selected_variant,
                    "version": group.get("version", "v1"),
                }
                out.append(item)
        return out
