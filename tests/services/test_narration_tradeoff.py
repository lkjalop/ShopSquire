"""Profile-driven product narration: dims come from the StoreProfile, not hardcoded specs.

Proves (a) electronics output is BYTE-IDENTICAL to the old hardcoded _spec_summary_for_llm,
(b) a non-electronics vertical narrates its OWN tradeoffs from its slot, (c) the GPU model→VRAM
variant fallback works, and (d) an absent slot degrades to 'specs unavailable' (never invents
electronics fields). Isolated via profile_slot monkeypatch — no real profile/DB needed.
"""
from __future__ import annotations

import src.app.services.narration_tradeoff as nt
import src.app.platform.store_profile as sp

_ELEC = [
    {"label": "GPU", "variants": [{"key": "gpu_model"}, {"key": "gpu_vram_gb", "unit": "GB VRAM"}]},
    {"label": "Display", "variants": [{"key": "refresh_hz", "unit": "Hz"}]},
    {"label": "RAM", "variants": [{"key": "ram_gb", "unit": "GB"}]},
    {"label": "SSD", "variants": [{"key": "storage_gb", "unit": "GB"}]},
    {"label": "CPU", "variants": [{"key": "cpu_model"}]},
]


def _slot(dims):
    return lambda slot, **k: dims if slot == "narration_spec_dimensions" else None


def test_electronics_output_byte_equivalent(monkeypatch):
    monkeypatch.setattr(sp, "profile_slot", _slot(_ELEC))
    r = {"name": "MSI Katana", "price_cents": 149900,
         "specs": {"gpu_model": "RTX 4070", "refresh_hz": 144, "ram_gb": 16, "storage_gb": 1024, "cpu_model": "i7-13620H"}}
    assert nt.spec_summary_line(r, 0) == (
        "[1] MSI Katana ($1,499) — GPU: RTX 4070 | Display: 144Hz | RAM: 16GB | SSD: 1024GB | CPU: i7-13620H"
    )


def test_gpu_variant_falls_back_to_vram(monkeypatch):
    monkeypatch.setattr(sp, "profile_slot", _slot(_ELEC))
    r = {"name": "X", "price_cents": 100000, "specs": {"gpu_vram_gb": 8, "ram_gb": 16}}
    line = nt.spec_summary_line(r, 1)
    assert line.startswith("[2] X ($1,000) — ")
    assert "GPU: 8GB VRAM" in line and "RAM: 16GB" in line


def test_non_electronics_vertical_uses_its_own_dims(monkeypatch):
    pharm = [
        {"label": "Active", "variants": [{"key": "active_ingredient"}]},
        {"label": "Strength", "variants": [{"key": "strength_mg", "unit": "mg"}]},
    ]
    monkeypatch.setattr(sp, "profile_slot", _slot(pharm))
    r = {"name": "Ibuprofen", "price_cents": 599, "specs": {"active_ingredient": "Ibuprofen", "strength_mg": 200}}
    assert nt.spec_summary_line(r, 0) == "[1] Ibuprofen ($5) — Active: Ibuprofen | Strength: 200mg"


def test_absent_slot_degrades_to_specs_unavailable(monkeypatch):
    monkeypatch.setattr(sp, "profile_slot", lambda slot, **k: None)
    r = {"name": "Y", "price_cents": 0, "specs": {"gpu_model": "RTX 4070"}}  # has electronics spec but no slot
    assert nt.spec_summary_line(r, 0) == "[1] Y () — specs unavailable"
