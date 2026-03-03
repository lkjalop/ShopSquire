from src.app.services.erp_edi import ERPEDIConnector


def test_erp_edi_connector_parse_document_x12():
    connector = ERPEDIConnector()
    out = connector.parse_document("ST*850*0001~BEG*00*SA*PO-9**20240101~SE*3*0001~")
    assert out.get("standard") == "x12"
    assert out.get("doc_type") == "purchase_order"
