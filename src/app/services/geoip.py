from __future__ import annotations

import os
import time
import json
import ipaddress
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple, Dict, Any

from src.app.observability.metrics import (
    record_geoip_lookup,
    record_geoip_cache_hit,
    record_geo_asn_risk,
)


@dataclass
class GeoResult:
    asn: Optional[int]
    asn_org: Optional[str]
    country: Optional[str]
    is_hosting: bool
    is_vpn: bool
    risk: float
    matched_override: bool


def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_overrides():
    return _load_json(os.path.join("config", "security", "geoip_overrides.json")).get("overrides", [])


def _load_offline_heuristics() -> Dict[str, Any]:
    data = _load_json(os.path.join("config", "security", "geoip_offline_heuristics.json"))
    return data if isinstance(data, dict) else {}


def _load_asn_risk_profiles() -> Dict[str, Any]:
    data = _load_json(os.path.join("config", "security", "asn_risk_profiles.json"))
    return data if isinstance(data, dict) else {}


def _load_country_risk_profiles() -> Dict[str, Any]:
    data = _load_json(os.path.join("config", "security", "geo_country_risk_profiles.json"))
    return data if isinstance(data, dict) else {}


def _load_bad_asn() -> set[int]:
    data = _load_json(os.path.join("config", "security", "bad_asn.json"))
    vals = data.get("bad_asn", []) if isinstance(data, dict) else []
    out = set()
    for v in vals:
        try:
            out.add(int(v))
        except Exception:
            continue
    return out


class _TTLCache:
    def __init__(self, ttl_seconds: int = 86400, maxsize: int = 50000):
        self.ttl = ttl_seconds
        self.maxsize = maxsize
        self._store: Dict[str, tuple[float, Dict[str, Any]]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        val = self._store.get(key)
        if not val:
            return None
        ts, data = val
        if now - ts > self.ttl:
            try:
                del self._store[key]
            except Exception:
                pass
            return None
        return data

    def set(self, key: str, value: Dict[str, Any]):
        if len(self._store) >= self.maxsize:
            try:
                # FIFO style eviction
                old_key = next(iter(self._store.keys()))
                del self._store[old_key]
            except Exception:
                self._store.clear()
        self._store[key] = (time.time(), value)


_cache = _TTLCache()


def _mmdb_lookup(ip: str) -> Optional[Dict[str, Any]]:
    db_path = os.getenv("MAXMIND_DB_PATH")
    if not db_path:
        return None
    try:
        import geoip2.database  # type: ignore

        with geoip2.database.Reader(db_path) as reader:
            asn_info = None
            try:
                asn = reader.asn(ip)
                asn_info = {"asn": int(getattr(asn, "autonomous_system_number", 0) or 0), "asn_org": getattr(asn, "autonomous_system_organization", None)}
            except Exception:
                asn_info = None
            cc = None
            try:
                city = reader.city(ip)
                cc = getattr(getattr(city, "country", None), "iso_code", None)
            except Exception:
                cc = None
            ans = {"asn": None, "asn_org": None, "country": cc}
            if asn_info:
                ans.update(asn_info)
            return ans
    except Exception:
        return None


def _ip2location_lookup(ip: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("IP2LOCATION_API_KEY")
    if not api_key:
        return None
    try:
        import httpx

        url = f"https://api.ip2location.io/?key={api_key}&ip={ip}&format=json"
        r = httpx.get(url, timeout=1.5)
        if r.status_code != 200:
            return None
        data = r.json()
        return {
            "asn": int(data.get("asn") or 0) or None,
            "asn_org": data.get("as"),
            "country": (data.get("country_code") or data.get("country_code2")),
        }
    except Exception:
        return None


def _ip_api_lookup(ip: str) -> Optional[Dict[str, Any]]:
    """Free ip-api.com lookup (45 req/min, no key needed). HTTP only."""
    if str(os.getenv("GEOIP_DISABLE_IP_API", "")).strip().lower() in ("1", "true"):
        return None
    try:
        import httpx

        # ip-api.com free tier: HTTP only, 45 req/min
        url = f"http://ip-api.com/json/{ip}?fields=status,countryCode,isp,org,as,hosting,proxy,query"
        r = httpx.get(url, timeout=2.0)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("status") != "success":
            return None
        as_str = data.get("as") or ""
        asn_num = None
        if as_str:
            # Format: "AS15169 Google LLC"
            parts = as_str.split(None, 1)
            if parts and parts[0].upper().startswith("AS"):
                try:
                    asn_num = int(parts[0][2:])
                except (ValueError, IndexError):
                    pass
        return {
            "asn": asn_num,
            "asn_org": data.get("isp") or data.get("org"),
            "country": data.get("countryCode"),
            "is_hosting": bool(data.get("hosting")),
            "is_vpn": bool(data.get("proxy")),
        }
    except Exception:
        return None


def _override_match(ip: str) -> Optional[Dict[str, Any]]:
    try:
        ip_obj = ipaddress.ip_address(ip)
    except Exception:
        return None
    for row in _load_overrides() or []:
        try:
            cidr = row.get("cidr")
            if not cidr:
                continue
            if ip_obj in ipaddress.ip_network(cidr, strict=False):
                return {
                    "asn": int(row.get("asn") or 0) or None,
                    "asn_org": row.get("org"),
                    "country": row.get("country"),
                    "is_vpn": bool(row.get("is_vpn")),
                    "is_hosting": bool(row.get("is_hosting", True)),
                    "risk": float(row.get("risk", 0.8)),
                    "matched_override": True,
                }
        except Exception:
            continue
    return None


def _offline_heuristic_lookup(ip: str) -> Optional[Dict[str, Any]]:
    try:
        ip_obj = ipaddress.ip_address(ip)
    except Exception:
        return None

    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
        return {
            "asn": None,
            "asn_org": "private_network",
            "country": "ZZ",
            "is_hosting": False,
            "is_vpn": False,
            "risk": 0.0,
            "matched_override": False,
            "offline_heuristic": "private_or_loopback",
        }
    if any(
        ip_obj in ipaddress.ip_network(cidr)
        for cidr in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
    ):
        return {
            "asn": None,
            "asn_org": "TEST-NET",
            "country": "ZZ",
            "is_hosting": False,
            "is_vpn": False,
            "risk": 0.35,
            "matched_override": False,
            "offline_heuristic": "documentation_range",
        }

    heur = _load_offline_heuristics()
    exact = heur.get("exact_ips") if isinstance(heur.get("exact_ips"), dict) else {}
    row = exact.get(ip) if isinstance(exact, dict) else None
    if isinstance(row, dict):
        out = {
            "asn": int(row.get("asn") or 0) or None,
            "asn_org": row.get("org"),
            "country": row.get("country"),
            "is_hosting": bool(row.get("is_hosting")),
            "is_vpn": bool(row.get("is_vpn")),
            "risk": float(row.get("risk", 0.45)),
            "matched_override": False,
            "offline_heuristic": "exact_ip",
        }
        if row.get("tags") is not None:
            out["tags"] = list(row.get("tags") or [])[:8]
        return out

    cidr_rows = heur.get("cidr_overrides") if isinstance(heur.get("cidr_overrides"), list) else []
    for entry in cidr_rows:
        if not isinstance(entry, dict):
            continue
        try:
            if ip_obj in ipaddress.ip_network(str(entry.get("cidr") or ""), strict=False):
                out = {
                    "asn": int(entry.get("asn") or 0) or None,
                    "asn_org": entry.get("org"),
                    "country": entry.get("country"),
                    "is_hosting": bool(entry.get("is_hosting")),
                    "is_vpn": bool(entry.get("is_vpn")),
                    "risk": float(entry.get("risk", 0.75)),
                    "matched_override": False,
                    "offline_heuristic": "cidr_match",
                }
                if entry.get("tags") is not None:
                    out["tags"] = list(entry.get("tags") or [])[:8]
                return out
        except Exception:
            continue
    return None


def _risk_from_asn(asn: Optional[int], org: Optional[str], country: Optional[str], base: float) -> float:
    bad = _load_bad_asn()
    r = base
    try:
        if asn and asn in bad:
            r = max(r, 0.8)
        # Cloud/VPN heuristics by org string
        org_l = (org or "").lower()
        if any(k in org_l for k in ("aws", "amazon", "google", "microsoft", "azure", "cloudflare", "ovh", "digitalocean", "contabo", "linode", "vultr", "m247", "hetzner")):
            r = max(r, 0.75)
    except Exception:
        pass
    try:
        profiles = _load_asn_risk_profiles()
        row = (profiles.get("profiles") or {}).get(str(int(asn))) if asn and isinstance((profiles.get("profiles") or {}), dict) else None
        if isinstance(row, dict):
            r = max(r, float(row.get("risk_floor", r)))
    except Exception:
        pass
    try:
        c_profiles = _load_country_risk_profiles()
        row = (c_profiles.get("countries") or {}).get(str(country or "").upper()) if isinstance((c_profiles.get("countries") or {}), dict) else None
        if isinstance(row, dict):
            r = max(r, float(row.get("risk_floor", r)))
    except Exception:
        pass
    # Bound 0..1
    return max(0.0, min(1.0, float(r)))


def enrich_ip(ip: Optional[str]) -> Dict[str, Any]:
    if not ip:
        return {}
    record_geoip_lookup()

    # Evaluate CIDR overrides before cache so local policy changes apply
    # immediately even when the IP was previously cached from provider data.
    override = _override_match(ip)
    if override:
        result = override
    else:
        cached = _cache.get(ip)
        if cached:
            record_geoip_cache_hit()
            return cached
        # Provider chain: MaxMind (local) -> offline heuristics -> IP2Location (API) -> ip-api.com (free) -> defaults
        provider_data = _mmdb_lookup(ip) or _offline_heuristic_lookup(ip) or _ip2location_lookup(ip) or _ip_api_lookup(ip) or {}
        asn = provider_data.get("asn")
        org = provider_data.get("asn_org")
        cc = provider_data.get("country") or os.getenv("GEOIP_COUNTRY_DEFAULT")
        result = {
            "asn": asn,
            "asn_org": org,
            "country": cc,
            "is_hosting": bool(provider_data.get("is_hosting")),
            "is_vpn": bool(provider_data.get("is_vpn")),
            "matched_override": False,
        }
        if provider_data.get("offline_heuristic") is not None:
            result["offline_heuristic"] = provider_data.get("offline_heuristic")
        if provider_data.get("tags") is not None:
            result["tags"] = list(provider_data.get("tags") or [])[:8]

    # Risk computation and hosting/vpn heuristics
    base_risk = float(result.get("risk", 0.2))
    r = _risk_from_asn(result.get("asn"), result.get("asn_org"), result.get("country"), base_risk)
    result["risk"] = r
    # Hosting/VPN signals retained from override, or inferred from org
    org_l = (result.get("asn_org") or "").lower()
    if not result.get("is_hosting"):
        result["is_hosting"] = any(k in org_l for k in ("cloud", "hosting", "aws", "google", "azure", "ovh", "digitalocean", "hetzner", "linode", "vultr", "m247"))
    if not result.get("is_vpn"):
        result["is_vpn"] = any(k in org_l for k in ("vpn", "proxy", "m247", "nord", "expressvpn", "tor"))

    try:
        profiles = _load_asn_risk_profiles()
        row = (profiles.get("profiles") or {}).get(str(int(result.get("asn")))) if result.get("asn") and isinstance((profiles.get("profiles") or {}), dict) else None
        if isinstance(row, dict):
            result["asn_profile"] = {
                "label": row.get("label"),
                "category": row.get("category"),
                "risk_floor": row.get("risk_floor"),
                "tags": list(row.get("tags") or [])[:8],
            }
            result["is_hosting"] = bool(result.get("is_hosting") or row.get("is_hosting"))
            result["is_vpn"] = bool(result.get("is_vpn") or row.get("is_vpn"))
    except Exception:
        pass
    try:
        c_profiles = _load_country_risk_profiles()
        crow = (c_profiles.get("countries") or {}).get(str(result.get("country") or "").upper()) if isinstance((c_profiles.get("countries") or {}), dict) else None
        if isinstance(crow, dict):
            result["country_profile"] = {
                "label": crow.get("label"),
                "risk_floor": crow.get("risk_floor"),
                "tags": list(crow.get("tags") or [])[:8],
            }
    except Exception:
        pass

    # Emit Prom metrics for dashboards
    try:
        risk_band = "high" if r >= 0.8 else ("med" if r >= 0.5 else "low")
        record_geo_asn_risk(str(result.get("asn") or "0"), result.get("asn_org") or "unknown", result.get("country") or "XX", risk_band)
    except Exception:
        pass

    _cache.set(ip, result)
    return result

def resolve_asn_country(ip: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    enriched = enrich_ip(ip)
    return enriched.get("asn"), enriched.get("country")


def lookup(ip: Optional[str]) -> Optional[GeoResult]:
    """Backward-compatible GeoIP contract used by fraud/recommend codepaths.

    Prefer ``enrich_ip`` for new code. This adapter preserves the historical
    object-shaped return expected by callers.
    """
    enriched = enrich_ip(ip)
    if not enriched:
        return None
    try:
        asn_raw = enriched.get("asn")
        asn = int(asn_raw) if asn_raw is not None else None
    except (TypeError, ValueError):
        asn = None
    try:
        risk = float(enriched.get("risk", 0.0) or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    return GeoResult(
        asn=asn,
        asn_org=str(enriched.get("asn_org")) if enriched.get("asn_org") else None,
        country=str(enriched.get("country")).upper() if enriched.get("country") else None,
        is_hosting=bool(enriched.get("is_hosting")),
        is_vpn=bool(enriched.get("is_vpn")),
        risk=max(0.0, min(1.0, risk)),
        matched_override=bool(enriched.get("matched_override")),
    )

