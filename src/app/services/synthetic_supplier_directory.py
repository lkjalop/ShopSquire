"""Fictional contact adapter. Never resolves arbitrary outbound recipients."""


def recipient_for(supplier_ref):
    contacts = {"fictional-distributor": "quotes@fictional-distributor.invalid"}
    if supplier_ref not in contacts:
        raise ValueError("fictional_supplier_not_enrolled")
    return contacts[supplier_ref]
