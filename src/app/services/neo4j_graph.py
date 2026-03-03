from __future__ import annotations

import os
from typing import Any, Dict


_DRIVER = None


def _enabled() -> bool:
    return str(os.getenv("FRAUD_GRAPH_NEO4J_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _get_driver():
    global _DRIVER
    if _DRIVER is not None:
        return _DRIVER
    if not _enabled():
        return None
    uri = str(os.getenv("NEO4J_URI", "") or "").strip()
    user = str(os.getenv("NEO4J_USER", "") or "").strip()
    password = str(os.getenv("NEO4J_PASSWORD", "") or "").strip()
    if not (uri and user and password):
        return None
    try:
        from neo4j import GraphDatabase  # type: ignore

        _DRIVER = GraphDatabase.driver(uri, auth=(user, password))
        return _DRIVER
    except Exception:
        _DRIVER = None
        return None


def shipping_address_cluster_signal(
    *,
    shipping_address_hash: str | None,
    account_id: str | None = None,
    device_fingerprint: str | None = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "enabled": _enabled(),
        "source": "neo4j" if _enabled() else "disabled",
        "cluster_size": 0,
        "device_count": 0,
        "ring_risk": 0.0,
        "ring_hit": False,
    }
    if not _enabled() or not shipping_address_hash:
        return out

    driver = _get_driver()
    if driver is None:
        out["source"] = "neo4j_unavailable"
        return out
    try:
        q = """
        MATCH (a:Address {hash: $address_hash})<-[:USES_ADDRESS]-(u:User)
        OPTIONAL MATCH (u)-[:USES_DEVICE]->(d:Device)
        RETURN count(DISTINCT u) AS cluster_size, count(DISTINCT d) AS device_count
        """
        with driver.session() as sess:
            row = sess.run(
                q,
                address_hash=str(shipping_address_hash),
                account_id=str(account_id or ""),
                device_fingerprint=str(device_fingerprint or ""),
            ).single()
        cluster_size = int((row.get("cluster_size") if row else 0) or 0)
        device_count = int((row.get("device_count") if row else 0) or 0)
        ring_risk = min(1.0, (cluster_size / 6.0) + (device_count / 10.0))
        out.update(
            {
                "cluster_size": cluster_size,
                "device_count": device_count,
                "ring_risk": round(float(ring_risk), 4),
                "ring_hit": bool(cluster_size >= 4 or ring_risk >= 0.65),
            }
        )
    except Exception:
        out["source"] = "neo4j_error"
    return out


def upsert_account_device_ip_event(
    *,
    account_id: str | None,
    device_fingerprint: str | None,
    source_ip: str | None,
    shipping_address_hash: str | None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"enabled": _enabled(), "written": False, "source": "neo4j" if _enabled() else "disabled"}
    if not _enabled() or not account_id:
        return out
    driver = _get_driver()
    if driver is None:
        out["source"] = "neo4j_unavailable"
        return out
    try:
        q = """
        MERGE (u:User {id: $account_id})
        WITH u
        FOREACH (_ IN CASE WHEN $device_fingerprint <> '' THEN [1] ELSE [] END |
          MERGE (d:Device {fp: $device_fingerprint})
          MERGE (u)-[:USES_DEVICE]->(d)
        )
        FOREACH (_ IN CASE WHEN $source_ip <> '' THEN [1] ELSE [] END |
          MERGE (ip:IP {addr: $source_ip})
          MERGE (u)-[:USES_IP]->(ip)
        )
        FOREACH (_ IN CASE WHEN $shipping_address_hash <> '' THEN [1] ELSE [] END |
          MERGE (a:Address {hash: $shipping_address_hash})
          MERGE (u)-[:USES_ADDRESS]->(a)
        )
        """
        with driver.session() as sess:
            sess.run(
                q,
                account_id=str(account_id or ""),
                device_fingerprint=str(device_fingerprint or ""),
                source_ip=str(source_ip or ""),
                shipping_address_hash=str(shipping_address_hash or ""),
            ).consume()
        out["written"] = True
    except Exception:
        out["source"] = "neo4j_error"
    return out


def account_device_ip_ring_signal(
    *,
    account_id: str | None,
    device_fingerprint: str | None,
    source_ip: str | None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "enabled": _enabled(),
        "source": "neo4j" if _enabled() else "disabled",
        "linked_accounts": 0,
        "shared_devices": 0,
        "shared_ips": 0,
        "ring_risk": 0.0,
        "ring_hit": False,
    }
    if not _enabled() or (not account_id and not device_fingerprint and not source_ip):
        return out
    driver = _get_driver()
    if driver is None:
        out["source"] = "neo4j_unavailable"
        return out
    try:
        q = """
        OPTIONAL MATCH (u:User {id: $account_id})-[:USES_DEVICE]->(d:Device)
        OPTIONAL MATCH (d)<-[:USES_DEVICE]-(u2:User)
        WITH collect(DISTINCT u2) AS dev_users

        OPTIONAL MATCH (u3:User {id: $account_id})-[:USES_IP]->(ip:IP)
        OPTIONAL MATCH (ip)<-[:USES_IP]-(u4:User)
        WITH dev_users, collect(DISTINCT u4) AS ip_users,
             size(dev_users) AS shared_devices_users, size(collect(DISTINCT u4)) AS shared_ips_users

        RETURN
            shared_devices_users AS shared_devices,
            shared_ips_users AS shared_ips,
            size(apoc.coll.toSet(dev_users + ip_users)) AS linked_accounts
        """
        # fallback query without apoc if unavailable
        q_simple = """
        OPTIONAL MATCH (u:User {id: $account_id})-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(u2:User)
        WITH collect(DISTINCT u2.id) AS dev_ids
        OPTIONAL MATCH (u3:User {id: $account_id})-[:USES_IP]->(ip:IP)<-[:USES_IP]-(u4:User)
        WITH dev_ids, collect(DISTINCT u4.id) AS ip_ids
        RETURN size(dev_ids) AS shared_devices, size(ip_ids) AS shared_ips, size(dev_ids) + size(ip_ids) AS linked_accounts
        """
        with driver.session() as sess:
            try:
                row = sess.run(q, account_id=str(account_id or "")).single()
            except Exception:
                row = sess.run(q_simple, account_id=str(account_id or "")).single()
        shared_devices = int((row.get("shared_devices") if row else 0) or 0)
        shared_ips = int((row.get("shared_ips") if row else 0) or 0)
        linked_accounts = int((row.get("linked_accounts") if row else 0) or 0)
        ring_risk = min(1.0, (linked_accounts / 8.0) + (shared_devices / 6.0) + (shared_ips / 8.0))
        out.update(
            {
                "linked_accounts": linked_accounts,
                "shared_devices": shared_devices,
                "shared_ips": shared_ips,
                "ring_risk": round(float(ring_risk), 4),
                "ring_hit": bool(linked_accounts >= 4 or ring_risk >= 0.7),
            }
        )
    except Exception:
        out["source"] = "neo4j_error"
    return out

