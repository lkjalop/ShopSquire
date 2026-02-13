from __future__ import annotations

import os
from typing import Any, Dict

from sqlalchemy import create_engine, text as sql_text


def get_pg_engine():
    url = os.getenv("DATABASE_URL", "postgresql://localhost/shopsquire")
    return create_engine(url, pool_pre_ping=True)


def get_neo4j():
    try:
        from neo4j import GraphDatabase
    except Exception:
        raise RuntimeError("neo4j driver not installed: pip install neo4j")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "test")
    return GraphDatabase.driver(uri, auth=(user, pwd))


def upsert(tx, cypher: str, params: Dict[str, Any]):
    tx.run(cypher, **params)


def run_etl(limit: int = 500):
    eng = get_pg_engine()
    driver = get_neo4j()

    with eng.connect() as conn, driver.session() as session:
        # Customers
        customers = conn.execute(sql_text("SELECT id, email FROM customers LIMIT :limit"), {"limit": limit}).fetchall()
        for c in customers:
            session.write_transaction(
                upsert,
                "MERGE (n:Customer {id: $id}) SET n.email = $email",
                {"id": c[0], "email": c[1]},
            )

        # Orders
        orders = conn.execute(sql_text("SELECT id, customer_id, status, total_cents, created_at FROM orders LIMIT :limit"), {"limit": limit}).fetchall()
        for o in orders:
            session.write_transaction(
                upsert,
                "MERGE (o:Order {id: $id}) SET o.status=$status, o.total_cents=$total, o.created_at=$created;"
                "MATCH (c:Customer {id: $cid}) MERGE (c)-[:PLACED]->(o)",
                {"id": o[0], "cid": o[1], "status": o[2], "total": o[3], "created": str(o[4])},
            )

        # Decision logs
        decisions = conn.execute(sql_text("SELECT id, agent_name, system_from, input_data FROM decision_logs LIMIT :limit"), {"limit": limit}).fetchall()
        for d in decisions:
            session.write_transaction(
                upsert,
                "MERGE (dl:DecisionLog {id: $id}) SET dl.agent_name=$agent, dl.created_at=$created, dl.input_data=$input",
                {"id": d[0], "agent": d[1], "created": str(d[2]), "input": d[3]},
            )

        # Security events
        sec = conn.execute(sql_text("SELECT id, severity, event_time, path FROM security_events LIMIT :limit"), {"limit": limit}).fetchall()
        for s in sec:
            session.write_transaction(
                upsert,
                "MERGE (se:SecurityEvent {id: $id}) SET se.severity=$severity, se.created_at=$created, se.path=$path",
                {"id": s[0], "severity": s[1], "created": str(s[2]), "path": s[3]},
            )

        # Link decisions to orders if input_data contains order_id
        dec_orders = conn.execute(sql_text("SELECT id, input_data FROM decision_logs WHERE input_data LIKE '%order_id%' LIMIT :limit"), {"limit": limit}).fetchall()
        for d in dec_orders:
            import json

            try:
                data = json.loads(d[1])
                oid = data.get("order_id") or data.get("input", {}).get("order_id")
            except Exception:
                oid = None
            if oid:
                session.write_transaction(
                    upsert,
                    "MATCH (dl:DecisionLog {id: $did}), (o:Order {id: $oid}) MERGE (o)-[:HAS_DECISION]->(dl)",
                    {"did": d[0], "oid": oid},
                )

    driver.close()


if __name__ == "__main__":
    run_etl()
