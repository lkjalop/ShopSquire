from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from typing import Dict
import json
import uuid
import inspect

from src.app.models.event_log import ensure_event_log_table
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.cv_triage_basic import BasicCVTriage
from src.app.services.cv_provider import ManagedCVProvider

router = APIRouter(prefix="/api/v1/vision", tags=["vision"])


def _derive_query_from_analysis(analysis: Dict) -> str:
    if not isinstance(analysis, dict):
        return "product"
    damage_type = str(analysis.get("damage_type") or "").lower()
    component = str(analysis.get("component") or "").lower()
    if damage_type and damage_type != "unknown":
        return f"{damage_type} {component}".strip()
    if component:
        return component
    return "device"


@router.post("/triage")
async def triage(image: UploadFile = File(...), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Run lightweight CV triage from uploaded image and persist event metadata."""
    if image is None:
        raise HTTPException(status_code=400, detail="image_required")

    try:
        mime = image.content_type
        name = image.filename
    except Exception:
        mime = None
        name = None

    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty_image")

    labels = []
    extracted_text = ""
    provider_name = "none"
    try:
        provider = ManagedCVProvider()
        provider_name = provider.provider
        labels, extracted_text = await provider.get_labels_and_text(content)
    except Exception:
        labels, extracted_text = [], ""

    if not labels and name:
        labels = [name]

    triager = BasicCVTriage()
    triage_result = triager.analyze(labels, extracted_text or "")
    if inspect.isawaitable(triage_result):
        analysis = await triage_result
    else:
        analysis = triage_result

    resp = {
        "query": _derive_query_from_analysis(analysis),
        "label": analysis.get("damage_type") or "unknown",
        "mime": mime,
        "filename": name,
        "provider": provider_name,
        "labels": labels[:20],
        "extracted_text": (extracted_text or "")[:500],
        "analysis": analysis,
    }

    try:
        ensure_event_log_table()
        ev_id = str(uuid.uuid4())
        payload = json.dumps(resp, ensure_ascii=False)
        with db_session() as db:
            db.execute(
                "INSERT INTO event_log (id, type, payload, status) VALUES (:id, :type, :payload, 'pending')",
                {"id": ev_id, "type": "vision.triage", "payload": payload},
            )
            try:
                db.commit()
            except Exception:
                pass
        resp["event_id"] = ev_id
    except Exception:
        pass

    return resp
