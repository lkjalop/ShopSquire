from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Dict
from sqlalchemy import text

from src.app.models.db import db_session


class ShippingService:
    async def create_return_label(self, case_id: str) -> Dict:
        label_id = str(uuid.uuid4())
        tracking = f"RR{uuid.uuid4().hex[:10].upper()}"
        label_url = f"https://example.com/labels/{label_id}.pdf"
        expires = (datetime.utcnow() + timedelta(days=14)).isoformat()
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO return_labels (id, case_id, carrier, tracking_number, label_url, status, expires_at)
                    VALUES (:id, :case_id, :carrier, :tracking, :url, 'generated', :expires)
                    """
                ),
                {
                    "id": label_id,
                    "case_id": case_id,
                    "carrier": "FedEx Ground",
                    "tracking": tracking,
                    "url": label_url,
                    "expires": expires,
                },
            )
            db.commit()
        return {"id": label_id, "carrier": "FedEx Ground", "tracking_number": tracking, "label_url": label_url, "expires_at": expires}
