from __future__ import annotations

from typing import Any, Dict, List
import re


class CVSupplyChainMonitor:
    """Monitor uploads for supply chain attack indicators."""

    def analyze_upload(self, image_bytes: bytes, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        signals: List[Dict[str, Any]] = []
        if self._has_embedded_payload(image_bytes):
            signals.append({"type": "embedded_payload", "severity": "critical"})
        if self._is_polyglot(image_bytes):
            signals.append({"type": "polyglot_file", "severity": "critical"})
        if self._is_oversized(image_bytes):
            signals.append({"type": "potential_dos", "severity": "high"})
        md_hits = self._metadata_prompt_injection_hits(metadata or {})
        if md_hits:
            signals.append({"type": "adversarial_metadata_prompt", "severity": "high", "hits": md_hits[:5]})
        return {
            "signals": signals,
            "safe": len(signals) == 0,
            "recommendation": "block" if signals else "allow",
        }

    def _has_embedded_payload(self, data: bytes) -> bool:
        exe_signatures = [b"MZ", b"\x7fELF", b"#!/", b"<?php", b"<script"]
        return any(sig in data for sig in exe_signatures)

    def _is_polyglot(self, data: bytes) -> bool:
        # crude detection: multiple file signatures present
        signatures = [b"\xff\xd8\xff", b"\x89PNG", b"%PDF", b"GIF89a"]
        hits = sum(1 for sig in signatures if sig in data[:512])
        return hits > 1

    def _is_oversized(self, data: bytes) -> bool:
        return len(data or b"") > 10 * 1024 * 1024

    def _metadata_prompt_injection_hits(self, metadata: Dict[str, Any]) -> List[str]:
        if not isinstance(metadata, dict):
            return []
        pat = re.compile(r"(?i)(ignore\s+previous|override\s+system|developer\s+mode|jailbreak|drop\s+table|<script)")
        hits: List[str] = []
        for k, v in metadata.items():
            sv = str(v or "")
            if pat.search(sv):
                hits.append(str(k))
        return hits
