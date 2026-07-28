"""Tenant-scoped UoM and template/variant identity registry."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session


def register_uom(
    *,
    tenant_id: str,
    category: str,
    code: str,
    factor_to_base: Decimal,
    is_base: bool = False,
) -> dict[str, str]:
    tenant = str(tenant_id or "").strip()
    category_name = str(category or "").strip().lower()
    unit_code = str(code or "").strip().upper()
    factor = Decimal(factor_to_base)
    if not tenant or not category_name or not unit_code or factor <= 0:
        raise ValueError("valid_uom_scope_required")
    if is_base and factor != Decimal("1"):
        raise ValueError("base_uom_factor_must_equal_one")
    category_id = hashlib.sha256(f"{tenant}|uom-category|{category_name}".encode()).hexdigest()
    unit_id = hashlib.sha256(f"{tenant}|uom-unit|{unit_code}".encode()).hexdigest()
    with db_session() as db:
        if not db.execute(text("SELECT 1 FROM uom_category WHERE id=:id"), {"id": category_id}).fetchone():
            db.execute(
                text("INSERT INTO uom_category (id,tenant_id,name) VALUES (:id,:tenant,:name)"),
                {"id": category_id, "tenant": tenant, "name": category_name},
            )
        existing = db.execute(
            text("SELECT factor_to_base,category_id FROM uom_unit WHERE id=:id"),
            {"id": unit_id},
        ).fetchone()
        if existing and (Decimal(str(existing[0])) != factor or str(existing[1]) != category_id):
            raise ValueError("uom_definition_is_immutable")
        if not existing:
            db.execute(
                text(
                    """
                    INSERT INTO uom_unit
                    (id,tenant_id,category_id,code,factor_to_base,is_base)
                    VALUES (:id,:tenant,:category,:code,:factor,:base)
                    """
                ),
                {
                    "id": unit_id, "tenant": tenant, "category": category_id,
                    "code": unit_code, "factor": str(factor), "base": bool(is_base),
                },
            )
        db.commit()
    return {"category_id": category_id, "unit_id": unit_id}


def register_variant(
    *,
    tenant_id: str,
    template_id: str,
    variant_id: str,
    sku: str,
    base_uom_code: str,
    attributes: dict[str, Any] | None = None,
) -> str:
    tenant = str(tenant_id or "").strip()
    template = str(template_id or "").strip()
    variant = str(variant_id or "").strip()
    normalized_sku = str(sku or "").strip()
    uom = str(base_uom_code or "").strip().upper()
    if not all((tenant, template, variant, normalized_sku, uom)):
        raise ValueError("variant_identity_scope_required")
    record_id = hashlib.sha256(f"{tenant}|variant|{variant}".encode()).hexdigest()
    with db_session() as db:
        if not db.execute(
            text("SELECT 1 FROM uom_unit WHERE tenant_id=:tenant AND code=:code"),
            {"tenant": tenant, "code": uom},
        ).fetchone():
            raise ValueError("variant_base_uom_not_registered")
        existing = db.execute(
            text(
                """
                SELECT template_id,sku,base_uom_code FROM product_variant_identity
                WHERE tenant_id=:tenant AND variant_id=:variant
                """
            ),
            {"tenant": tenant, "variant": variant},
        ).fetchone()
        identity = (template, normalized_sku, uom)
        if existing and tuple(map(str, existing)) != identity:
            raise ValueError("variant_identity_is_immutable")
        if not existing:
            db.execute(
                text(
                    """
                    INSERT INTO product_variant_identity
                    (id,tenant_id,template_id,variant_id,sku,base_uom_code,attributes_json,active)
                    VALUES (:id,:tenant,:template,:variant,:sku,:uom,:attributes,1)
                    """
                ),
                {
                    "id": record_id, "tenant": tenant, "template": template,
                    "variant": variant, "sku": normalized_sku, "uom": uom,
                    "attributes": json.dumps(attributes or {}, sort_keys=True),
                },
            )
            db.commit()
    return record_id


def convert_uom(
    *, tenant_id: str, value: Decimal, from_code: str, to_code: str
) -> Decimal:
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT code,category_id,factor_to_base FROM uom_unit
                WHERE tenant_id=:tenant AND code IN (:source,:target)
                """
            ),
            {
                "tenant": str(tenant_id or "").strip(),
                "source": str(from_code or "").strip().upper(),
                "target": str(to_code or "").strip().upper(),
            },
        ).fetchall()
    units = {str(row[0]): (str(row[1]), Decimal(str(row[2]))) for row in rows}
    source, target = str(from_code).upper(), str(to_code).upper()
    if source not in units or target not in units:
        raise ValueError("uom_not_registered")
    if units[source][0] != units[target][0]:
        raise ValueError("uom_category_mismatch")
    return Decimal(value) * units[source][1] / units[target][1]
