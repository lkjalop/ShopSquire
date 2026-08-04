"""Tenant-scoped UoM and template/variant identity registry."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session


@dataclass(frozen=True)
class UomConversionResult:
    status: str
    value: Decimal | None
    from_code: str
    to_code: str
    authority_id: str | None = None
    source: str | None = None
    rounding_mode: str | None = None
    reason: str | None = None


_ROUNDING = {
    "ceiling": ROUND_CEILING,
    "floor": ROUND_FLOOR,
    "half_up": ROUND_HALF_UP,
    "toward_zero": ROUND_DOWN,
}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def register_uom_conversion(
    *,
    tenant_id: str,
    from_code: str,
    to_code: str,
    factor: Decimal,
    effective_from: str,
    source: str,
    source_record_id: str,
    approved_by: str,
    effective_to: str | None = None,
    rounding_mode: str = "exact",
    rounding_increment: Decimal | None = None,
) -> str:
    """Register an immutable, effective-dated conversion authority."""
    tenant = str(tenant_id or "").strip()
    source_code = str(from_code or "").strip().upper()
    target_code = str(to_code or "").strip().upper()
    conversion_factor = Decimal(factor)
    mode = str(rounding_mode or "").strip().lower()
    start = _utc(effective_from)
    end = _utc(effective_to) if effective_to else None
    if not all((tenant, source_code, target_code, source, source_record_id, approved_by)):
        raise ValueError("uom_conversion_authority_required")
    if source_code == target_code or conversion_factor <= 0:
        raise ValueError("uom_conversion_factor_invalid")
    if mode not in {"exact", "reject_fractional", *_ROUNDING}:
        raise ValueError("uom_rounding_mode_invalid")
    if end is not None and end <= start:
        raise ValueError("uom_conversion_effective_range_invalid")
    increment = Decimal(rounding_increment) if rounding_increment is not None else None
    if increment is not None and increment <= 0:
        raise ValueError("uom_rounding_increment_invalid")
    authority_id = hashlib.sha256(
        (
            f"{tenant}|{source_code}|{target_code}|{start.isoformat()}|"
            f"{source}|{source_record_id}|{conversion_factor}|{mode}|{increment}"
        ).encode()
    ).hexdigest()
    with db_session() as db:
        units = db.execute(
            text(
                """
                SELECT code, category_id FROM uom_unit
                WHERE tenant_id=:tenant AND code IN (:source_code,:target_code)
                """
            ),
            {
                "tenant": tenant,
                "source_code": source_code,
                "target_code": target_code,
            },
        ).fetchall()
        categories = {str(row[0]): str(row[1]) for row in units}
        if source_code not in categories or target_code not in categories:
            raise ValueError("uom_not_registered")
        if categories[source_code] != categories[target_code]:
            raise ValueError("uom_category_mismatch")
        overlap = db.execute(
            text(
                """
                SELECT 1 FROM uom_conversion_authority
                WHERE tenant_id=:tenant AND from_code=:source_code
                  AND to_code=:target_code AND status='approved'
                  AND effective_from < COALESCE(:effective_to, '9999-12-31T23:59:59+00:00')
                  AND (effective_to IS NULL OR effective_to > :effective_from)
                """
            ),
            {
                "tenant": tenant,
                "source_code": source_code,
                "target_code": target_code,
                "effective_from": start.isoformat(),
                "effective_to": end.isoformat() if end else None,
            },
        ).fetchone()
        if overlap:
            raise ValueError("uom_conversion_effective_range_overlaps")
        db.execute(
            text(
                """
                INSERT INTO uom_conversion_authority
                (id,tenant_id,from_code,to_code,factor,rounding_mode,
                 rounding_increment,effective_from,effective_to,source,
                 source_record_id,status,approved_by)
                VALUES
                (:id,:tenant,:source_code,:target_code,:factor,:rounding_mode,
                 :rounding_increment,:effective_from,:effective_to,:source,
                 :source_record_id,'approved',:approved_by)
                """
            ),
            {
                "id": authority_id,
                "tenant": tenant,
                "source_code": source_code,
                "target_code": target_code,
                "factor": str(conversion_factor),
                "rounding_mode": mode,
                "rounding_increment": str(increment) if increment is not None else None,
                "effective_from": start.isoformat(),
                "effective_to": end.isoformat() if end else None,
                "source": str(source),
                "source_record_id": str(source_record_id),
                "approved_by": str(approved_by),
            },
        )
        db.commit()
    return authority_id


def governed_convert_uom(
    *,
    tenant_id: str,
    value: Decimal,
    from_code: str,
    to_code: str,
    at_time: str,
) -> UomConversionResult:
    """Convert with an approved authority or return an explicit incomparable result."""
    tenant = str(tenant_id or "").strip()
    source_code = str(from_code or "").strip().upper()
    target_code = str(to_code or "").strip().upper()
    if source_code == target_code:
        return UomConversionResult(
            status="comparable",
            value=Decimal(value),
            from_code=source_code,
            to_code=target_code,
            reason="identity",
        )
    when = _utc(at_time).isoformat()
    with db_session() as db:
        categories = {
            str(row[0]): str(row[1])
            for row in db.execute(
                text(
                    """
                    SELECT code,category_id FROM uom_unit
                    WHERE tenant_id=:tenant AND code IN (:source_code,:target_code)
                    """
                ),
                {
                    "tenant": tenant,
                    "source_code": source_code,
                    "target_code": target_code,
                },
            ).fetchall()
        }
        if source_code not in categories or target_code not in categories:
            return UomConversionResult(
                "incomparable", None, source_code, target_code,
                reason="uom_not_registered",
            )
        if categories[source_code] != categories[target_code]:
            return UomConversionResult(
                "incomparable", None, source_code, target_code,
                reason="uom_category_mismatch",
            )
        row = db.execute(
            text(
                """
                SELECT id,factor,rounding_mode,rounding_increment,source
                FROM uom_conversion_authority
                WHERE tenant_id=:tenant AND from_code=:source_code
                  AND to_code=:target_code AND status='approved'
                  AND effective_from <= :at_time
                  AND (effective_to IS NULL OR effective_to > :at_time)
                ORDER BY effective_from DESC LIMIT 1
                """
            ),
            {
                "tenant": tenant,
                "source_code": source_code,
                "target_code": target_code,
                "at_time": when,
            },
        ).fetchone()
    if row is None:
        return UomConversionResult(
            "incomparable", None, source_code, target_code,
            reason="approved_effective_conversion_unavailable",
        )
    converted = Decimal(value) * Decimal(str(row[1]))
    mode = str(row[2])
    increment = Decimal(str(row[3])) if row[3] is not None else None
    if mode == "reject_fractional" and converted != converted.to_integral_value():
        return UomConversionResult(
            "incomparable", None, source_code, target_code,
            authority_id=str(row[0]), source=str(row[4]), rounding_mode=mode,
            reason="fractional_target_quantity_rejected",
        )
    if mode in _ROUNDING:
        quantum = increment or Decimal(1)
        converted = (
            converted / quantum
        ).quantize(Decimal(1), rounding=_ROUNDING[mode]) * quantum
    return UomConversionResult(
        "comparable",
        converted,
        source_code,
        target_code,
        authority_id=str(row[0]),
        source=str(row[4]),
        rounding_mode=mode,
    )


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
