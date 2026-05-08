"""
Graph ETL — builds fraud ring graph in Neo4j from PostgreSQL session data
plus seeds deterministic demo rings for local/dev environments.

Usage:
  python scripts/etl_graph.py                  # live ETL from Postgres + demo seed
  python scripts/etl_graph.py --demo-only       # demo seed only (no Postgres needed)
  python scripts/etl_graph.py --limit 1000      # increase row cap

Neo4j must be running:
  docker compose --profile neo4j up -d
  # then wait ~30s for Neo4j to initialise, then run this script.

Environment variables:
  NEO4J_URI        default bolt://localhost:7687
  NEO4J_USER       default neo4j
  NEO4J_PASSWORD   default neo4j-change-me
  DATABASE_URL     default postgresql://localhost/shopsquire
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ── Neo4j helpers ────────────────────────────────────────────────────────────

def get_neo4j_driver():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("ERROR: neo4j driver not installed — run: pip install neo4j", file=sys.stderr)
        sys.exit(1)
    uri  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER",     "neo4j")
    pwd  = os.getenv("NEO4J_PASSWORD", "neo4j-change-me")
    drv  = GraphDatabase.driver(uri, auth=(user, pwd))
    drv.verify_connectivity()
    return drv


def _tx(tx, cypher: str, **params: Any) -> None:
    tx.run(cypher, **params)


def upsert_account(session, account_id: str, email: str = "",
                   account_age_days: int = 365, chargeback_rate: float = 0.0) -> None:
    session.execute_write(
        _tx,
        """
        MERGE (a:Account {id: $id})
        SET a.email           = $email,
            a.account_age_days = $age,
            a.chargeback_rate  = $cbr,
            a.updated_at       = $now
        """,
        id=account_id, email=email, age=account_age_days,
        cbr=chargeback_rate, now=datetime.now(timezone.utc).isoformat(),
    )


def upsert_device(session, device_fp: str) -> None:
    session.execute_write(
        _tx,
        "MERGE (d:Device {id: $id}) SET d.updated_at = $now",
        id=device_fp, now=datetime.now(timezone.utc).isoformat(),
    )


def upsert_ip(session, ip: str) -> None:
    session.execute_write(
        _tx,
        "MERGE (i:IPAddress {id: $id}) SET i.updated_at = $now",
        id=ip, now=datetime.now(timezone.utc).isoformat(),
    )


def upsert_address(session, addr_hash: str, city: str = "", country: str = "") -> None:
    session.execute_write(
        _tx,
        """
        MERGE (a:Address {id: $id})
        SET a.city = $city, a.country = $country, a.updated_at = $now
        """,
        id=addr_hash, city=city, country=country,
        now=datetime.now(timezone.utc).isoformat(),
    )


def link(session, from_id: str, from_label: str, to_id: str, to_label: str,
         rel_type: str, weight: float = 1.0) -> None:
    cypher = f"""
        MATCH (a:{from_label} {{id: $fid}}), (b:{to_label} {{id: $tid}})
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r.weight = $w, r.first_seen = $now
        ON MATCH  SET r.weight = $w, r.last_seen  = $now
    """
    session.execute_write(_tx, cypher, fid=from_id, tid=to_id, w=weight,
                          now=datetime.now(timezone.utc).isoformat())


def create_indexes(session) -> None:
    for label, prop in [
        ("Account",   "id"),
        ("Device",    "id"),
        ("IPAddress", "id"),
        ("Address",   "id"),
    ]:
        session.execute_write(
            _tx,
            f"CREATE INDEX {label.lower()}_{prop}_idx IF NOT EXISTS FOR (n:{label}) ON (n.{prop})",
        )
    print("  indexes ensured")


# ── Demo seed data ────────────────────────────────────────────────────────────

def _demo_rings() -> List[Dict[str, Any]]:
    """
    Three synthetic fraud rings with distinct patterns:
      ring_A — classic return fraud: 8 accounts, shared device + address
      ring_B — synthetic identity: 5 new accounts, shared IP block, high velocity
      ring_C — account takeover: 3 accounts, shared device, high chargeback rate
    """
    now = datetime.now(timezone.utc)

    rings = []

    # ── Ring A: return fraud ring ────────────────────────────────────────────
    ring_a_device  = "fp_device_ring_a_001"
    ring_a_ip      = "203.0.113.10"
    ring_a_addr    = "addr_hash_ring_a_warehouse_001"
    ring_a_members = [
        {"id": f"acc_ring_a_{i:03d}", "email": f"ring_a_{i}@tempmail.io",
         "age": 12 + i, "cbr": 0.35 + i * 0.02}
        for i in range(1, 9)    # 8 accounts
    ]
    rings.append({
        "name": "ring_A",
        "label": "Return Fraud Ring",
        "members": ring_a_members,
        "shared_device": ring_a_device,
        "shared_ip": ring_a_ip,
        "shared_address": ring_a_addr,
        "city": "Sydney",
        "country": "AU",
    })

    # ── Ring B: synthetic identity ──────────────────────────────────────────
    ring_b_device  = "fp_device_ring_b_001"
    ring_b_ip      = "198.51.100.77"
    ring_b_addr    = "addr_hash_ring_b_dropship_001"
    ring_b_members = [
        {"id": f"acc_ring_b_{i:03d}", "email": f"synth_{uuid.uuid4().hex[:8]}@fastmail.net",
         "age": 3 + i, "cbr": 0.10 + i * 0.05}
        for i in range(1, 6)    # 5 new accounts
    ]
    rings.append({
        "name": "ring_B",
        "label": "Synthetic Identity Ring",
        "members": ring_b_members,
        "shared_device": ring_b_device,
        "shared_ip": ring_b_ip,
        "shared_address": ring_b_addr,
        "city": "Melbourne",
        "country": "AU",
    })

    # ── Ring C: account takeover ────────────────────────────────────────────
    ring_c_device  = "fp_device_ring_c_001"
    ring_c_ip      = "192.0.2.55"
    ring_c_addr    = "addr_hash_ring_c_reshipping_001"
    ring_c_members = [
        {"id": f"acc_ring_c_{i:03d}", "email": f"hijacked_acct_{i}@gmail.com",
         "age": 500 + i * 30, "cbr": 0.55 + i * 0.08}
        for i in range(1, 4)    # 3 hijacked accounts
    ]
    rings.append({
        "name": "ring_C",
        "label": "Account Takeover Ring",
        "members": ring_c_members,
        "shared_device": ring_c_device,
        "shared_ip": ring_c_ip,
        "shared_address": ring_c_addr,
        "city": "Brisbane",
        "country": "AU",
    })

    return rings


def seed_demo_rings(session) -> None:
    print("  seeding demo fraud rings...")
    for ring in _demo_rings():
        upsert_device(session, ring["shared_device"])
        upsert_ip(session, ring["shared_ip"])
        upsert_address(session, ring["shared_address"],
                       city=ring["city"], country=ring["country"])

        for m in ring["members"]:
            upsert_account(session, m["id"], email=m["email"],
                           account_age_days=m["age"], chargeback_rate=m["cbr"])
            link(session, m["id"], "Account", ring["shared_device"], "Device",
                 "USES_DEVICE", weight=1.0)
            link(session, m["id"], "Account", ring["shared_ip"],     "IPAddress",
                 "USES_IP",     weight=1.0)
            link(session, m["id"], "Account", ring["shared_address"], "Address",
                 "USES_ADDRESS", weight=1.0)

        print(f"    {ring['name']} ({ring['label']}): "
              f"{len(ring['members'])} accounts, device={ring['shared_device'][-12:]}, "
              f"ip={ring['shared_ip']}")
    print("  demo rings seeded")


# ── Live ETL from PostgreSQL ─────────────────────────────────────────────────

def get_pg_engine():
    from sqlalchemy import create_engine
    url = os.getenv("DATABASE_URL", "postgresql://localhost/shopsquire")
    return create_engine(url, pool_pre_ping=True)


def run_live_etl(session, limit: int = 500) -> None:
    from sqlalchemy import text as sql_text
    try:
        eng = get_pg_engine()
    except Exception as exc:
        print(f"  WARNING: cannot connect to Postgres ({exc}) — skipping live ETL", file=sys.stderr)
        return

    print(f"  running live ETL (limit={limit})...")
    try:
        with eng.connect() as conn:
            # ── Accounts from customers table ────────────────────────────────
            rows = conn.execute(sql_text(
                "SELECT id, email FROM customers LIMIT :lim"
            ), {"lim": limit}).fetchall()
            for r in rows:
                upsert_account(session, str(r[0]), email=str(r[1] or ""))
            print(f"    customers: {len(rows)}")

            # ── Orders — link to accounts ────────────────────────────────────
            rows = conn.execute(sql_text(
                "SELECT id, customer_id, status, total_cents, created_at FROM orders LIMIT :lim"
            ), {"lim": limit}).fetchall()
            for r in rows:
                session.execute_write(
                    _tx,
                    """
                    MERGE (o:Order {id: $id})
                    SET o.status=$status, o.total_cents=$total, o.created_at=$created
                    WITH o
                    MATCH (a:Account {id: $cid})
                    MERGE (a)-[:PLACED]->(o)
                    """,
                    id=str(r[0]), cid=str(r[1] or ""),
                    status=str(r[2] or ""), total=int(r[3] or 0),
                    created=str(r[4] or ""),
                )
            print(f"    orders: {len(rows)}")

            # ── Fraud signals from security_events — build device/IP edges ──
            rows = conn.execute(sql_text(
                """
                SELECT payload->>'account_id'    AS acc,
                       payload->>'device_fp'     AS device,
                       payload->>'ip_address'    AS ip,
                       payload->>'shipping_hash' AS addr_hash
                FROM security_events
                WHERE payload IS NOT NULL
                  AND payload->>'account_id' IS NOT NULL
                LIMIT :lim
                """
            ), {"lim": limit}).fetchall()
            edges = 0
            for r in rows:
                acc = r[0]
                if not acc:
                    continue
                upsert_account(session, acc)
                if r[1]:
                    upsert_device(session, r[1])
                    link(session, acc, "Account", r[1], "Device",   "USES_DEVICE")
                    edges += 1
                if r[2]:
                    upsert_ip(session, r[2])
                    link(session, acc, "Account", r[2], "IPAddress", "USES_IP")
                    edges += 1
                if r[3]:
                    upsert_address(session, r[3])
                    link(session, acc, "Account", r[3], "Address",   "USES_ADDRESS")
                    edges += 1
            print(f"    security_events → fraud edges: {edges}")

    except Exception as exc:
        print(f"  WARNING: live ETL partial failure ({exc})", file=sys.stderr)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Populate Neo4j fraud ring graph")
    parser.add_argument("--demo-only", action="store_true",
                        help="Only seed demo rings, skip Postgres ETL")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max rows to pull from Postgres (default 500)")
    args = parser.parse_args()

    print("Connecting to Neo4j...")
    try:
        driver = get_neo4j_driver()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Is Neo4j running?  docker compose --profile neo4j up -d", file=sys.stderr)
        sys.exit(1)
    print("  connected")

    with driver.session() as session:
        create_indexes(session)

        if not args.demo_only:
            run_live_etl(session, limit=args.limit)

        seed_demo_rings(session)

    driver.close()
    print("\nDone. Verify in Neo4j browser: http://localhost:7474")
    print("  MATCH (a:Account)-[:USES_DEVICE]->(d:Device) RETURN a, d LIMIT 50")


if __name__ == "__main__":
    main()
