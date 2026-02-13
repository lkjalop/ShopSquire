from fastapi import APIRouter, Depends, HTTPException
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from fastapi.responses import HTMLResponse
from typing import List

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])


@router.post("/{ticket_id}/approve")
def approve_ticket(ticket_id: str, role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER, ROLE_MERCHANT]))):
    try:
        from src.app.services.ticketing import TicketingAgent
        ta = TicketingAgent()
        ok = ta.approve_ticket(ticket_id)
        if not ok:
            raise HTTPException(status_code=404, detail="ticket not found or could not be approved")
        return {"status": "approved", "ticket_id": ticket_id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="approve failed")


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str, role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER, ROLE_MERCHANT]))):
    try:
        from src.app.services.ticketing import TicketingAgent
        ta = TicketingAgent()
        t = ta.get_ticket(ticket_id)
        if not t:
            raise HTTPException(status_code=404, detail="ticket not found")
        return {"ticket": t.__dict__}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="get ticket failed")


@router.get("/")
def list_tickets(status: str | None = None, role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER, ROLE_MERCHANT]))):
    try:
        from src.app.services.ticketing import TicketingAgent
        ta = TicketingAgent()
        ts = ta.list_tickets(status=status)
        return {"tickets": [t.__dict__ for t in ts]}
    except Exception:
        raise HTTPException(status_code=500, detail="list tickets failed")


@router.get("/ui", response_class=HTMLResponse)
def tickets_ui(role: str = Depends(require_role([ROLE_DEVELOPER, ROLE_OWNER, ROLE_MERCHANT]))):
    try:
        from src.app.services.ticketing import TicketingAgent
        ta = TicketingAgent()
        ts = ta.list_tickets(status=None)
        rows = "\n".join([f"<tr><td>{t.id}</td><td>{t.title}</td><td>{t.severity}</td><td>{t.status}</td></tr>" for t in ts])
        html = f"<html><head><title>Tickets</title></head><body><h1>Tickets</h1><table border=1><tr><th>ID</th><th>Title</th><th>Severity</th><th>Status</th></tr>{rows}</table></body></html>"
        return HTMLResponse(content=html)
    except Exception:
        raise HTTPException(status_code=500, detail="ui failed")
