"""Workload requirements stage (W2, 2026-07-08) — extracted VERBATIM from suggest()
(recommend.py ~6964-7037: game/software requirements enrichment + generic-gaming defaults).

Why extracted: the platform detected games and computed requirement floors but the evidence
died inside constraint mutation — the buyer answer never carried the min-vs-recommended
comparison (GPT-5.5 + brain-on audits, both 2026-07-08: "detects games but loses the useful
comparison before final answer"). This stage returns a WORKLOAD CONTEXT object so downstream
stages (fit verdicts, narration preamble, guard evidence, response payload) can consume the
same facts that shaped retrieval. Constraint mutation is byte-for-byte the old behavior
(parity-tested); the context return is the new capability.

Agnostic core: all vocabulary comes from use_case_advisor (profile/KB-driven) — this module
owns sequencing, not flavour.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def apply_workload_requirements(
    query_effective: str,
    constraints: Dict[str, Any],
    *,
    gpu_pref_inferred: bool,
    record_failure: Callable[..., Any],
    trace_id: Any = None,
) -> Dict[str, Any]:
    """Mutates ``constraints`` exactly as the inline blocks did; returns the workload context:
    {games, software, game_reqs, sw_reqs, generic_gaming, floors} — floors is the merged
    requirement dict downstream fit verdicts compare against. Never raises."""
    ctx: Dict[str, Any] = {
        "games": [], "software": [], "game_reqs": {}, "sw_reqs": {},
        "generic_gaming": False, "floors": {},
    }
    # ── Game/Software Requirements Enrichment (verbatim from recommend.py:6964) ──
    try:
        from src.app.flows.nqe import detect_games_in_text, detect_software_in_text
        ctx["games"] = detect_games_in_text(query_effective)
        ctx["software"] = detect_software_in_text(query_effective)
        if ctx["games"]:
            from src.app.services.use_case_advisor import match_game_requirements
            _game_reqs = match_game_requirements(ctx["games"])
            ctx["game_reqs"] = _game_reqs or {}
            if _game_reqs.get("recommended_ram_gb"):
                constraints.setdefault("specs", [])
                constraints["specs"].append(f"ram_gb_min:{_game_reqs['recommended_ram_gb']}")
            if _game_reqs.get("gpu_needed"):
                constraints["must_have_gpu"] = True
                constraints["gpu_preference"] = "with_discrete"
            if _game_reqs.get("recommended_gpu_vram_gb"):
                constraints.setdefault("specs", [])
                constraints["specs"].append(f"gpu_vram_gb_min:{_game_reqs['recommended_gpu_vram_gb']}")
            if _game_reqs.get("min_refresh_hz", 60) > 60:
                constraints.setdefault("specs", [])
                constraints["specs"].append(f"refresh_hz_min:{_game_reqs['min_refresh_hz']}")
        if ctx["software"]:
            from src.app.services.use_case_advisor import match_software_requirements
            _sw_reqs = match_software_requirements(ctx["software"])
            ctx["sw_reqs"] = _sw_reqs or {}
            if _sw_reqs.get("recommended_ram_gb"):
                constraints.setdefault("specs", [])
                constraints["specs"].append(f"ram_gb_min:{_sw_reqs['recommended_ram_gb']}")
            if _sw_reqs.get("gpu_needed"):
                constraints["must_have_gpu"] = True
                constraints["gpu_preference"] = "with_discrete"
    except Exception as _e_game_sw:  # observability boundary
        record_failure("game_software_requirements_enrichment", _e_game_sw, trace_id=trace_id)

    # ── Generic-gaming defaults (verbatim from recommend.py:6996) ──
    try:
        q_low = str(query_effective or "").lower()
        uc_low = str(constraints.get("use_case") or "").lower()
        generic_gaming = (
            ("gaming" in q_low or uc_low in {"gaming", "gaming_casual", "gaming_competitive", "gaming_aaa_heavy", "gaming_light"})
            and not ctx["games"]
        )
        ctx["generic_gaming"] = bool(generic_gaming)
        if generic_gaming:
            constraints.setdefault("specs", [])
            existing_spec_keys = {str(s).split(":", 1)[0].strip().lower() for s in (constraints.get("specs") or [])}
            # Entry-level gaming starts at 8GB RAM (e.g. MSI Thin A15 $1799).
            # 16GB is preferred but using it as a hard floor excludes real gaming
            # laptops in the $1500-$1900 range.  Use 8GB as the minimum.
            if "ram_gb_min" not in existing_spec_keys:
                constraints["specs"].append("ram_gb_min:8")
            # storage_gb_min:512 filters out valid entry-level gaming picks — no storage floor.
            if "refresh_hz_min" not in existing_spec_keys:
                constraints["specs"].append("refresh_hz_min:60")
            if constraints.get("gpu_preference") != "without_discrete":
                constraints["gpu_preference"] = "with_discrete"
                _derived_must_have = bool(float(constraints.get("budget_max") or 0) >= 850) if constraints.get("budget_max") is not None else False
                constraints["must_have_gpu"] = _derived_must_have and not gpu_pref_inferred
            if not constraints.get("use_case"):
                constraints["use_case"] = "gaming"
            # OS segregation: gaming queries are Windows ecosystem (no discrete gaming GPUs on
            # Apple in this catalog) unless the buyer explicitly asked for Apple.
            _current_brands = [str(b).lower() for b in (constraints.get("brands") or [])]
            _request_brand_hint_low = str(constraints.get("_request_brand_hint") or "").lower()
            _inferred_brand_low = str(constraints.get("_inferred_image_brand") or "").lower()
            _any_apple_hint = (
                "apple" in _current_brands
                or "apple" in _request_brand_hint_low
                or "apple" in _inferred_brand_low
            )
            if not _any_apple_hint and not constraints.get("_image_os_hint"):
                constraints["_image_os_hint"] = "windows"
    except Exception as _e_generic_gaming:  # observability boundary
        record_failure("generic_gaming_defaults", _e_generic_gaming, trace_id=trace_id)

    # ── AI-workload floors from the use-case KB (audit: "fine tune a 7B model" was answered
    # with office laptops — the KB knows ai_ml needs 8GB VRAM / 32GB RAM but nothing carried
    # that into a comparable floor). Query-pattern fallback covers phrasings the use-case
    # keyword map misses (stable diffusion / fine-tune / 7b-70b).
    try:
        import re as _re
        _uc = str(constraints.get("use_case") or "").lower()
        _is_ai = _uc.startswith("ai_ml") or _uc in {"data_science", "machine_learning"} or bool(
            _re.search(r"fine[- ]?tun\w+|stable\s*diffusion|image\s*generation|train(?:ing)?\s+(?:a\s+)?(?:llm|model)|\b(?:7|13|70)b\b\s*(?:model|llm)?|run(?:ning)?\s+(?:local\s+)?llms?", str(query_effective or "").lower())
        )
        if _is_ai:
            import json as _json
            with open("config/use_case_kb.json", encoding="utf-8") as _f:
                _kb_req = ((_json.load(_f).get("use_cases") or {}).get("ai_ml_workstation") or {}).get("required_specs") or {}
            if _kb_req:
                ctx["sw_reqs"] = dict(ctx["sw_reqs"] or {})
                ctx["sw_reqs"].setdefault("min_ram_gb", _kb_req.get("ram_gb_min"))
                ctx["sw_reqs"].setdefault("min_gpu_vram_gb", _kb_req.get("gpu_vram_gb_min"))
                if str(_kb_req.get("gpu_tier") or "").startswith("discrete"):
                    ctx["sw_reqs"].setdefault("gpu_needed", True)
                ctx["ai_workload"] = True
    except Exception:
        pass

    # ── Merged requirement floors for downstream fit verdicts (NEW — the un-lost evidence) ──
    try:
        floors: Dict[str, Any] = {}
        for src in (ctx["game_reqs"], ctx["sw_reqs"]):
            if src.get("min_ram_gb"):
                floors["min_ram_gb"] = max(float(src["min_ram_gb"]), float(floors.get("min_ram_gb") or 0))
            if src.get("recommended_ram_gb"):
                floors["recommended_ram_gb"] = max(float(src["recommended_ram_gb"]), float(floors.get("recommended_ram_gb") or 0))
            if src.get("min_gpu_vram_gb"):
                floors["min_gpu_vram_gb"] = max(float(src["min_gpu_vram_gb"]), float(floors.get("min_gpu_vram_gb") or 0))
            if src.get("recommended_gpu_vram_gb"):
                floors["recommended_gpu_vram_gb"] = max(float(src["recommended_gpu_vram_gb"]), float(floors.get("recommended_gpu_vram_gb") or 0))
            if src.get("gpu_needed"):
                floors["gpu_needed"] = True
        ctx["floors"] = floors
    except Exception:
        ctx["floors"] = {}
    return ctx
