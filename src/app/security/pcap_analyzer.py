from __future__ import annotations

import base64
import io
import re
from typing import Any, Dict, List


_DNS_NAME_RE = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", re.IGNORECASE)
_TUNNEL_LABEL_RE = re.compile(r"^[a-z0-9+/=_-]{18,}$", re.IGNORECASE)


def _decode_b64(raw: str | None) -> bytes:
    s = str(raw or "").strip()
    if not s:
        return b""
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    pad = "=" * ((4 - len(s) % 4) % 4)
    try:
        return base64.b64decode((s + pad).encode("utf-8"), validate=False)
    except Exception:
        return b""


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: Dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    import math

    n = float(len(s))
    out = 0.0
    for c in freq.values():
        p = float(c) / n
        out -= p * math.log2(p)
    return float(out)


def _extract_dns_candidates(blob: bytes) -> List[str]:
    # Fast fallback when packet parser deps are unavailable.
    txt = blob.decode("latin-1", errors="ignore")
    vals = [m.group(0).lower() for m in _DNS_NAME_RE.finditer(txt)]
    seen = set()
    out: List[str] = []
    for d in vals:
        if d in seen:
            continue
        seen.add(d)
        out.append(d)
        if len(out) >= 2000:
            break
    return out


def analyze_pcap_payload(
    *,
    pcap_b64: str | None = None,
    pcap_bytes: bytes | None = None,
    max_packets: int = 12000,
) -> Dict[str, Any]:
    """Best-effort PCAP analysis with DNS-tunnel oriented features."""
    blob = pcap_bytes if isinstance(pcap_bytes, (bytes, bytearray)) else _decode_b64(pcap_b64)
    if not blob:
        return {"ok": False, "error": "empty_pcap"}

    domains: List[str] = []
    parsed_with = "fallback_regex"
    # Try scapy when available for proper packet decoding.
    try:
        from scapy.all import rdpcap  # type: ignore
        from scapy.layers.dns import DNSQR  # type: ignore

        pkts = rdpcap(io.BytesIO(blob), count=max(1, int(max_packets)))
        for p in pkts:
            try:
                if p.haslayer(DNSQR):
                    qname = str(p[DNSQR].qname or "").rstrip(".").lower()
                    if qname:
                        domains.append(qname)
            except Exception:
                continue
        parsed_with = "scapy"
    except Exception:
        domains = _extract_dns_candidates(blob)

    if not domains:
        return {"ok": True, "parser": parsed_with, "dns_queries": 0, "suspicious": False, "signals": {}}

    uniq = sorted(set(domains))
    long_labels = 0
    high_entropy_labels = 0
    tunnel_like = 0
    for d in uniq:
        labels = d.split(".")
        if not labels:
            continue
        first = labels[0]
        if len(first) >= 24:
            long_labels += 1
        if _shannon_entropy(first) >= 4.0:
            high_entropy_labels += 1
        if _TUNNEL_LABEL_RE.match(first):
            tunnel_like += 1

    n = max(1, len(uniq))
    suspicious = (tunnel_like / n) >= 0.08 or (high_entropy_labels / n) >= 0.18
    score = min(
        1.0,
        (0.45 * (tunnel_like / n))
        + (0.35 * (high_entropy_labels / n))
        + (0.20 * (long_labels / n)),
    )
    signals = {
        "dns_query_count": len(domains),
        "dns_unique_domains": len(uniq),
        "dns_tunnel_like_ratio": round(float(tunnel_like) / float(n), 4),
        "dns_high_entropy_ratio": round(float(high_entropy_labels) / float(n), 4),
        "dns_long_label_ratio": round(float(long_labels) / float(n), 4),
        "pcap_dns_tunnel_suspected": bool(suspicious),
        "pcap_dns_tunnel_score": round(float(score), 4),
    }
    return {
        "ok": True,
        "parser": parsed_with,
        "suspicious": bool(suspicious),
        "score": round(float(score), 4),
        "risk_band": ("high" if score >= 0.75 else "medium" if score >= 0.4 else "low"),
        "signals": signals,
        "top_domains": uniq[:40],
    }


def correlate_network_findings(
    *,
    trace_id: str | None,
    tenant_id: str | None,
    analyzer_output: Dict[str, Any] | None,
    source: str = "pcap_ingest",
) -> Dict[str, Any]:
    out = analyzer_output if isinstance(analyzer_output, dict) else {}
    sig = out.get("signals") if isinstance(out.get("signals"), dict) else {}
    score = float(out.get("score") or sig.get("pcap_dns_tunnel_score") or 0.0)
    suspicious = bool(out.get("suspicious") or sig.get("pcap_dns_tunnel_suspected"))
    unique_domains = int(sig.get("dns_unique_domains") or 0)
    risk_band = "high" if (suspicious and score >= 0.65) else ("medium" if suspicious or score >= 0.4 else "low")
    correlated = {
        "trace_id": str(trace_id or ""),
        "tenant_id": str(tenant_id or "") or None,
        "source": source,
        "network_correlated_detection": bool(suspicious or score >= 0.4),
        "risk_band": risk_band,
        "score": round(score, 4),
        "dns_unique_domains": unique_domains,
        "suspicious_domains": list(out.get("top_domains") or [])[:10],
        "signals": sig,
    }
    return correlated
