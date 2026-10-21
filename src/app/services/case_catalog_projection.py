"""Project an owned case without losing its contract context at call sites."""
from src.app.services.accepted_catalog_projection import project_accepted_catalog


def project_case_catalog(db, *, case, uid, **options):
    return project_accepted_catalog(db,case_id=case.case_id,uid=uid,tenant_id=case.tenant_id,
        desired_outcome=case.retained_purpose or 'Buyer accepted requirements',**options)
