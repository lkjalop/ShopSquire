from fastapi.testclient import TestClient
from src.app.main import create_app
from tests.utils import default_headers
from src.app.services.ticketing import TicketingAgent


def test_tickets_list_and_approve():
    app = create_app()
    client = TestClient(app, headers=default_headers())

    ta = TicketingAgent()
    t = ta.create_ticket(title="API Test", description="test", severity="medium", approval_required=True)
    assert t is not None

    # list tickets
    r = client.get("/api/v1/tickets")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("tickets"), list)
    assert any(x.get("id") == t.id for x in body.get("tickets", []))

    # approve via API
    r2 = client.post(f"/api/v1/tickets/{t.id}/approve")
    assert r2.status_code == 200
    resp = r2.json()
    assert resp.get("status") == "approved"

    # get ticket shows approved status
    r3 = client.get(f"/api/v1/tickets/{t.id}")
    assert r3.status_code == 200
    ticket = r3.json().get("ticket")
    assert ticket and ticket.get("status") == "approved"
