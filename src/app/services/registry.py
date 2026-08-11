"""Simple plugin registry for agents and tools.

Loadable from config files to support modular deployments.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List
import hashlib
import json


_AGENTS: Dict[str, Callable] = {}
_TOOLS: Dict[str, Callable] = {}
_TOOL_META: Dict[str, Dict[str, Any]] = {}


def register_agent(name: str, factory: Callable) -> None:
    _AGENTS[name] = factory


def register_tool(name: str, impl: Callable | None = None, **metadata):
    """Register a tool implementation and optional metadata.

    Supports decorator style:
      @register_tool("catalog.search", description="...")
      def fn(...): ...
    """

    def _do_register(fn: Callable):
        _TOOLS[name] = fn
        meta = _TOOL_META.get(name, {}).copy()
        meta.update(metadata or {})
        meta.setdefault("name", name)
        _TOOL_META[name] = meta
        return fn

    if impl is None:
        return _do_register
    _do_register(impl)
    return impl


def register_tool_metadata(name: str, **metadata) -> None:
    meta = _TOOL_META.get(name, {}).copy()
    meta.update(metadata or {})
    meta.setdefault("name", name)
    _TOOL_META[name] = meta


def get_agent(name: str) -> Callable | None:
    return _AGENTS.get(name)


def get_tool(name: str) -> Callable | None:
    return _TOOLS.get(name)


def get_tool_metadata(name: str) -> Dict[str, Any]:
    return dict(_TOOL_META.get(name) or {})


def get_tool_contract_fingerprint(name: str) -> str:
    """Stable identity for the reviewed tool contract, independent of implementation memory address."""
    meta = get_tool_metadata(name)
    contract = {
        "name": str(name or ""),
        "description": str(meta.get("description") or ""),
        "risk": str(meta.get("risk") or "unknown"),
        "agent_types": sorted(str(item) for item in list(meta.get("agent_types") or [])),
        "input_schema": meta.get("input_schema") or {},
        "output_schema": meta.get("output_schema") or {},
        "server_id": str(meta.get("server_id") or "local"),
        "contract_version": str(meta.get("contract_version") or "1"),
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def list_tools() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    names = sorted(set(list(_TOOL_META.keys()) + list(_TOOLS.keys())))
    for name in names:
        meta = dict(_TOOL_META.get(name) or {})
        meta.setdefault("name", name)
        meta.setdefault("registered", name in _TOOLS)
        out.append(meta)
    return out


def get_tool_allowlist_for_agent(agent_type: str | None) -> List[str]:
    a = str(agent_type or "").strip().lower()
    if not a:
        return []
    out: List[str] = []
    for tool in list_tools():
        ats = tool.get("agent_types")
        if isinstance(ats, list) and a in [str(x).strip().lower() for x in ats]:
            out.append(str(tool.get("name")))
    return sorted(list(dict.fromkeys([t for t in out if t])))


def ensure_default_tool_metadata() -> None:
    defaults: Dict[str, Dict[str, Any]] = {
        "catalog.search": {"description": "Search product catalog by query keywords.", "risk": "low", "agent_types": ["orchestrator", "recommendations"]},
        "inventory.check": {"description": "Check real-time inventory by SKU.", "risk": "low", "agent_types": ["inventory", "orchestrator"]},
        "shipping.quote": {"description": "Estimate shipping cost and ETA.", "risk": "medium", "agent_types": ["orchestrator"]},
        "cv_scan": {"description": "Computer vision fraud/quality scan.", "risk": "medium", "agent_types": ["cv", "orchestrator"]},
        "fraud_scoring": {"description": "Fraud model scoring.", "risk": "high", "agent_types": ["fraud_scorer", "orchestrator"]},
        "inventory_check": {"description": "Inventory checks for ranked items.", "risk": "low", "agent_types": ["inventory", "orchestrator"]},
        "retrieve_context": {"description": "Retrieve contextual evidence.", "risk": "low", "agent_types": ["orchestrator"]},
        "check_policy": {"description": "Evaluate policy constraints.", "risk": "medium", "agent_types": ["orchestrator"]},
        "get_recommendations": {"description": "Fetch recommendation candidates.", "risk": "low", "agent_types": ["orchestrator", "recommendations"]},
    }
    for name, meta in defaults.items():
        if name not in _TOOL_META:
            register_tool_metadata(name, **meta)


def load_from_config(path: str = "config/plugins.yml") -> None:
    """Load registry entries from a YAML/JSON config (best-effort).

    Expected shape:
    {
      "agents": { "AgentName": "module:factory" },
      "tools": { "tool.name": "module:function" }
    }
    """
    try:
        txt = open(path, "r", encoding="utf-8").read()
    except Exception:
        return
    data = None
    try:
        import yaml
        data = yaml.safe_load(txt)
    except Exception:
        try:
            data = json.loads(txt)
        except Exception:
            data = None
    if not isinstance(data, dict):
        return
    ensure_default_tool_metadata()
    for coll, target in (("agents", _AGENTS), ("tools", _TOOLS)):
        items = data.get(coll) or {}
        if not isinstance(items, dict):
            continue
        for name, ref in items.items():
            meta: Dict[str, Any] = {}
            ref_value = ref
            if isinstance(ref, dict):
                ref_value = ref.get("ref")
                meta = {k: v for k, v in ref.items() if k != "ref"}
            if not isinstance(ref_value, str) or ":" not in ref_value:
                if coll == "tools" and meta:
                    register_tool_metadata(name, **meta)
                continue
            mod_name, func_name = ref_value.split(":", 1)
            try:
                mod = __import__(mod_name, fromlist=[func_name])
                fn = getattr(mod, func_name)
                target[name] = fn
                if coll == "tools":
                    register_tool_metadata(name, **meta)
            except Exception:
                continue


# Keep metadata available even when no explicit loader has run yet.
ensure_default_tool_metadata()
