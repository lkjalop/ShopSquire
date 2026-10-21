"""Immutable synthetic opening/sale/return/reservation observations.

These are fixture records, not executed orders or authority to change stock.
Changing a fixture requires a new scenario identity. No product-specific rules.
"""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import inspect, text


def ensure_table(db):
    db.execute(
        text("""CREATE TABLE IF NOT EXISTS synthetic_shop_history (
        tenant_id VARCHAR(128) NOT NULL, sku VARCHAR(255) NOT NULL,
        scenario_id VARCHAR(128) NOT NULL, fixture_digest VARCHAR(64) NOT NULL,
        events_json TEXT NOT NULL, recorded_at VARCHAR(64) NOT NULL,
        PRIMARY KEY (tenant_id, sku, scenario_id))""")
    )


def _project(events):
    locations = {}
    for event in events:
        row = locations.setdefault(event["location_id"], dict(on_hand=0, reserved=0))
        quantity = event["quantity"]
        if type(quantity) is not int or quantity <= 0:
            raise ValueError("invalid_history_quantity")
        kind = event["kind"]
        if kind in ("opening", "return"):
            row["on_hand"] += quantity
        elif kind == "sale":
            row["on_hand"] -= quantity
        elif kind == "reservation":
            row["reserved"] += quantity
        else:
            raise ValueError("unsupported_history_event")
        if not 0 <= row["reserved"] <= row["on_hand"]:
            raise ValueError("impossible_inventory_history")
    return [
        dict(location_id=key, **row, available=row["on_hand"] - row["reserved"])
        for key, row in sorted(locations.items())
    ]


def _events(fixture):
    events = []
    seen = set()
    for location in fixture["locations"]:
        if not location["id"] or location["id"] in seen:
            raise ValueError("ambiguous_history_location")
        seen.add(location["id"])
        for field, kind in [
            ("opening", "opening"),
            ("sold", "sale"),
            ("returned", "return"),
            ("reserved", "reservation"),
        ]:
            quantity = location[field]
            if type(quantity) is not int or quantity < 0:
                raise ValueError("invalid_history_quantity")
            if quantity:
                events.append(
                    dict(
                        sequence=len(events) + 1,
                        location_id=location["id"],
                        kind=kind,
                        quantity=quantity,
                        observed_at=fixture["effective_from"],
                        source="simulation:" + fixture["id"],
                    )
                )
    _project(events)
    return events


def record_fixture_history(db, *, tenant_id, sku, fixture):
    if not tenant_id.startswith("synthetic-") or fixture.get("simulation_only") is not True:
        raise ValueError("synthetic_history_required")
    if not sku or not fixture.get("id"):
        raise ValueError("history_identity_required")
    events = _events(fixture)
    serialized = json.dumps(events, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    ensure_table(db)
    params = dict(
        tenant=tenant_id,
        sku=sku,
        scenario=fixture["id"],
        digest=digest,
        events=serialized,
        recorded=datetime.now(timezone.utc).isoformat(),
    )
    db.execute(
        text("""INSERT INTO synthetic_shop_history
        (tenant_id,sku,scenario_id,fixture_digest,events_json,recorded_at)
        VALUES (:tenant,:sku,:scenario,:digest,:events,:recorded)
        ON CONFLICT (tenant_id,sku,scenario_id) DO NOTHING"""),
        params,
    )
    actual = db.execute(
        text("""SELECT fixture_digest FROM synthetic_shop_history
        WHERE tenant_id=:tenant AND sku=:sku AND scenario_id=:scenario"""),
        params,
    ).scalar_one()
    if actual != digest:
        raise ValueError("history_conflict_requires_new_scenario")


def replay_history(db, *, tenant_id, sku, scenario_id):
    row = None
    if inspect(db.connection()).has_table("synthetic_shop_history"):
        row = db.execute(
            text("""SELECT events_json,fixture_digest,recorded_at FROM synthetic_shop_history
        WHERE tenant_id=:tenant AND sku=:sku AND scenario_id=:scenario"""),
            dict(tenant=tenant_id, sku=sku, scenario=scenario_id),
        ).first()
    events = json.loads(row[0]) if row else []
    return dict(
        tenant_id=tenant_id,
        sku=sku,
        scenario_id=scenario_id,
        events=events,
        locations=_project(events),
        fixture_digest=row[1] if row else None,
        recorded_at=row[2] if row else None,
        simulation_only=True,
        commerce_authority="none",
    )


def reconcile_inventory(db, *, tenant_id, sku, scenario_id):
    """Compare immutable fixture opening history plus effects with canonical stock.

    Read-only diagnosis: drift never grants authority to rewrite stock. Effects and
    current balances are read in one SQL statement to avoid mixed-time totals.
    """
    baseline = replay_history(db, tenant_id=tenant_id, sku=sku, scenario_id=scenario_id)
    if not baseline['fixture_digest']:
        raise ValueError('inventory_baseline_required')
    rows = db.execute(text('''WITH raw_effects AS (
        SELECT r.location_id, e.on_hand_delta AS oh, e.reserved_delta AS rv
        FROM inventory_effect_event e JOIN inventory_reservation r
          ON r.tenant_id=e.tenant_id AND r.reservation_id=e.reservation_id
        WHERE r.tenant_id=:tenant AND r.sku=:sku
        UNION ALL
        SELECT destination_location,quantity,0 FROM inventory_stock_movement
          WHERE tenant_id=:tenant AND sku=:sku
        UNION ALL
        SELECT source_location,-quantity,0 FROM inventory_stock_movement
          WHERE tenant_id=:tenant AND sku=:sku AND kind='transfer'
      ), effects AS (
        SELECT location_id,SUM(oh) AS oh,SUM(rv) AS rv,COUNT(*) AS effect_count
        FROM raw_effects GROUP BY location_id
      ), locations AS (
        SELECT location_id FROM inventory_level WHERE tenant_id=:tenant AND sku=:sku
        UNION SELECT location_id FROM effects
      )
      SELECT l.location_id,s.on_hand,s.reserved,s.available,
             COALESCE(e.oh,0) AS oh,COALESCE(e.rv,0) AS rv,COALESCE(e.effect_count,0) AS effect_count
      FROM locations l LEFT JOIN effects e ON e.location_id=l.location_id
      LEFT JOIN inventory_level s ON s.location_id=l.location_id AND s.tenant_id=:tenant AND s.sku=:sku
      ORDER BY l.location_id'''), {'tenant':tenant_id,'sku':sku}).mappings().all()
    openings = {row['location_id']:row for row in baseline['locations']}
    balances = {row['location_id']:row for row in rows}
    locations = []
    for location in sorted(set(openings) | set(balances)):
        opening, balance = openings.get(location), balances.get(location)
        expected = None
        if opening:
            oh = opening['on_hand'] + (balance['oh'] if balance else 0)
            rv = opening['reserved'] + (balance['rv'] if balance else 0)
            expected = dict(on_hand=oh, reserved=rv, available=oh-rv)
        actual = {k:balance[k] for k in ('on_hand','reserved','available')} if balance and balance['on_hand'] is not None else None
        consistent = expected is not None and actual == expected and 0 <= expected['reserved'] <= expected['on_hand']
        locations.append(dict(location_id=location, expected=expected, actual=actual,
                              effect_count=balance['effect_count'] if balance else 0, consistent=consistent))
    return dict(tenant_id=tenant_id, sku=sku, scenario_id=scenario_id, locations=locations,
                consistent=all(row['consistent'] for row in locations), simulation_only=True,
                commerce_authority='none', baseline_digest=baseline['fixture_digest'])
