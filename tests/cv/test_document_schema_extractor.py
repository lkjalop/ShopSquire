from src.app.cv.document_schema_extractor import extract_document_schema


def test_extract_invoice_fields():
    text = "Invoice # INV-12345 PO Number PO-8899 USD 1,200.50 Date 2026-02-01"
    out = extract_document_schema(text)
    assert out.get("doc_type") == "invoice"
    assert (out.get("invoice") or {}).get("invoice_number") == "INV-12345"
    assert (out.get("invoice") or {}).get("po_number") == "PO-8899"
    assert float((out.get("confidence") or {}).get("overall") or 0.0) > 0.0
    assert isinstance(out.get("field_provenance"), list)
    assert any(str(p.get("field") or "").startswith("invoice.") for p in (out.get("field_provenance") or []))
    assert out.get("has_structured_fields") is True


def test_extract_bol_fields():
    text = "Bill of Lading No BOL-7788 carrier: DHL date 01/02/2026"
    out = extract_document_schema(text)
    assert out.get("doc_type") == "bol"
    assert (out.get("bol") or {}).get("bol_number") == "BOL-7788"
    assert isinstance((out.get("bol") or {}).get("parties"), list)
