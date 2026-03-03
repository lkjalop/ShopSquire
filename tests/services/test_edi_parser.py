from src.app.services.edi_parser import parse_edi_document


def test_parse_x12_850_purchase_order():
    raw = (
        "ISA*00*          *00*          *ZZ*SENDER*ZZ*RECV*240101*1200*U*00401*000000001*0*T*:~"
        "GS*PO*SENDER*RECV*20240101*1200*1*X*004010~"
        "ST*850*0001~BEG*00*SA*PO12345**20240101~N1*ST*Main WH*92*WHS1~"
        "PO1*1*5*EA*120.00**VP*SKU-100~SE*6*0001~GE*1*1~IEA*1*000000001~"
    )
    out = parse_edi_document(raw)
    assert out.get("standard") == "x12"
    assert out.get("transaction_set") == "850"
    assert out.get("doc_type") == "purchase_order"
    assert out.get("po_number") == "PO12345"
    assert (out.get("items") or [])[0].get("sku") == "SKU-100"


def test_parse_edifact_invoice():
    raw = (
        "UNB+UNOC:3+SENDER+RECV+240101:1200+1'"
        "UNH+1+INVOIC:D:96A:UN'"
        "BGM+380+INV-7788+9'"
        "LIN+1++SKU-9:SA'"
        "QTY+47:3'"
        "PRI+AAA:55.5'"
        "UNT+6+1'"
    )
    out = parse_edi_document(raw)
    assert out.get("standard") == "edifact"
    assert out.get("doc_type") == "invoice"
    assert out.get("document_number") == "INV-7788"
    assert (out.get("items") or [])[0].get("sku") == "SKU-9"
