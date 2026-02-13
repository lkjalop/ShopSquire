from src.app.connectors.email.gmail import normalize_message as normalize_gmail
from src.app.connectors.email.m365 import normalize_message as normalize_m365


def test_normalize_gmail_minimal_shape():
    msg = {
        "id": "m1",
        "threadId": "t1",
        "payload": {
            "headers": [
                {"name": "From", "value": "Vendor <billing@supplier.com>"},
                {"name": "Reply-To", "value": "accounts@supplier.com"},
                {"name": "Subject", "value": "Invoice overdue"},
                {"name": "Message-Id", "value": "<abc@xyz>"},
                {"name": "Authentication-Results", "value": "dmarc=pass"},
            ],
            "mimeType": "text/plain",
            "body": {"data": "SGVsbG8gd29ybGQ="},  # "Hello world" (base64url compatible)
        },
        "internalDate": "1700000000000",
    }
    out = normalize_gmail(msg=msg, tenant_id="t1")
    assert out["provider"] == "gmail"
    assert out["from_addr"]
    assert out["reply_to"]
    assert out["message_id"]
    assert isinstance(out.get("attachments"), list)


def test_normalize_m365_minimal_shape():
    msg = {
        "id": "mid",
        "internetMessageId": "<m@x>",
        "subject": "Hello",
        "conversationId": "c1",
        "from": {"emailAddress": {"name": "Vendor", "address": "billing@supplier.com"}},
        "replyTo": [{"emailAddress": {"address": "accounts@supplier.com"}}],
        "bodyPreview": "Pay invoice",
    }
    out = normalize_m365(msg=msg, attachments=[{"name": "invoice.zip", "content_type": "application/zip", "size_bytes": 1}], tenant_id="t1")
    assert out["provider"] == "m365"
    assert "supplier.com" in out["from_addr"]
    assert out["reply_to"]
    assert out["message_id"]

