"""Simple plugin registry for agents and tools.

Loadable from config files to support modular deployments.
"""
from __future__ import annotations

from typing import Callable, Dict
import json
import os


_AGENTS: Dict[str, Callable] = {}
_TOOLS: Dict[str, Callable] = {}


def register_agent(name: str, factory: Callable) -> None:
    _AGENTS[name] = factory


def register_tool(name: str, impl: Callable) -> None:
    _TOOLS[name] = impl


def get_agent(name: str) -> Callable | None:
    return _AGENTS.get(name)


def get_tool(name: str) -> Callable | None:
    return _TOOLS.get(name)


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
    for coll, target in (("agents", _AGENTS), ("tools", _TOOLS)):
        items = data.get(coll) or {}
        if not isinstance(items, dict):
            continue
        for name, ref in items.items():
            if not isinstance(ref, str) or ":" not in ref:
                continue
            mod_name, func_name = ref.split(":", 1)
            try:
                mod = __import__(mod_name, fromlist=[func_name])
                fn = getattr(mod, func_name)
                target[name] = fn
            except Exception:
                continue
