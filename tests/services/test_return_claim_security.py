import base64
import io
import json
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from starlette.requests import Request

from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
from src.app.routers.returns import create_return_claim
from src.app.services.return_claims import (
    AzureBlobEvidenceObjectStore,
    LocalEvidenceObjectStore,
    OrderVerification,
    assess_return_claim_abuse,
    create_claim,
    get_claim,
    load_encrypted_artifact,
    purge_expired_return_evidence,
    queue_evidence_job,
    set_evidence_legal_hold,
    store_encrypted_artifacts,
    transition_claim,
    verify_owned_order,
)
from src.app.tasks.return_evidence_tasks import _process_return_evidence
from tests.security.synthetic_samples import synthetic_xlsm_bytes


SCHEMA = """
CREATE TABLE orders (id TEXT PRIMARY KEY, tenant_id TEXT, customer_id TEXT, draft_order_id TEXT, created_at TEXT);
CREATE TABLE draft_orders (id TEXT PRIMARY KEY, tenant_id TEXT, line_items TEXT);
CREATE TABLE return_claim (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, claimant_id TEXT NOT NULL,
 order_id TEXT, sku TEXT NOT NULL, status TEXT NOT NULL, status_version INTEGER NOT NULL,
 description_sanitized TEXT, order_verification_status TEXT NOT NULL, trace_id TEXT NOT NULL,
 abuse_status TEXT NOT NULL DEFAULT 'allowed', abuse_reasons_json TEXT NOT NULL DEFAULT '[]',
 idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE return_claim_event (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, claim_id TEXT NOT NULL,
 sequence INTEGER NOT NULL, event_type TEXT NOT NULL, from_status TEXT, to_status TEXT NOT NULL,
 actor_type TEXT NOT NULL, actor_id TEXT NOT NULL, evidence_ref TEXT, metadata_json TEXT NOT NULL,
 effective_at TEXT NOT NULL, observed_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
 UNIQUE(tenant_id, claim_id, sequence));
CREATE TABLE return_evidence_object (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, claim_id TEXT NOT NULL,
 object_key TEXT NOT NULL, sha256 TEXT NOT NULL, media_type TEXT, original_name_sanitized TEXT NOT NULL,
 size_bytes INTEGER NOT NULL, cipher TEXT NOT NULL, encryption_key_id TEXT NOT NULL,
 retention_until TEXT NOT NULL, legal_hold BOOLEAN NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE return_evidence_observation (id TEXT PRIMARY KEY, tenant_id TEXT, claim_id TEXT,
 evidence_id TEXT, observation_type TEXT, sanitized_json TEXT, confidence REAL, authority TEXT,
 observed_at TEXT, expires_at TEXT, created_at TEXT);
CREATE TABLE return_evidence_job (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, claim_id TEXT NOT NULL,
 status TEXT NOT NULL, security_status TEXT NOT NULL, visual_status TEXT NOT NULL, attempts INTEGER NOT NULL,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, last_error TEXT, UNIQUE(tenant_id, claim_id));
CREATE TABLE return_evidence_access_audit (id TEXT PRIMARY KEY, tenant_id TEXT, claim_id TEXT,
 evidence_id TEXT, action TEXT, actor_id TEXT, purpose TEXT, metadata_json TEXT, created_at TEXT);
"""


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                conn.execute(text(statement))
    with Session(engine) as session:
        yield session


def _seed_order(db, *, tenant="tenant-a", claimant="buyer-a", order="order-a", sku="SKU-1"):
    db.execute(text("INSERT INTO draft_orders VALUES (:id,:tenant,:items)"), {
        "id": f"draft-{order}", "tenant": tenant, "items": json.dumps([{"sku": sku}]),
    })
    db.execute(text("INSERT INTO orders VALUES (:id,:tenant,:buyer,:draft,:created)"), {
        "id": order, "tenant": tenant, "buyer": claimant, "draft": f"draft-{order}",
        "created": "2026-08-04T00:00:00Z",
    })
    db.commit()


def test_order_verification_is_tenant_and_claimant_scoped(db):
    _seed_order(db)
    assert verify_owned_order(
        db, tenant_id="tenant-a", claimant_id="buyer-a", sku="SKU-1", order_id="order-a"
    ).status == "found"
    # A foreign buyer and tenant receive the same non-disclosing result.
    assert verify_owned_order(
        db, tenant_id="tenant-a", claimant_id="buyer-b", sku="SKU-1", order_id="order-a"
    ).status == "not_found"
    assert verify_owned_order(
        db, tenant_id="tenant-b", claimant_id="buyer-a", sku="SKU-1", order_id="order-a"
    ).status == "not_found"


def test_order_source_failure_is_not_reported_as_not_found(db):
    db.execute(text("DROP TABLE orders"))
    result = verify_owned_order(db, tenant_id="tenant-a", claimant_id="buyer-a", sku="SKU-1")
    assert result.status == "source_unavailable"


def test_raw_evidence_is_encrypted_tenant_scoped_and_audited(db, tmp_path, monkeypatch):
    key = bytes(range(32))
    monkeypatch.setenv("RETURN_EVIDENCE_KEYS", f"v1:{base64.urlsafe_b64encode(key).decode()}")
    monkeypatch.setenv("RETURN_EVIDENCE_ACTIVE_KEY_ID", "v1")
    store = LocalEvidenceObjectStore(tmp_path)
    claim = create_claim(
        db, tenant_id="tenant-a", claimant_id="buyer-a", sku="SKU-1", description="screen failed",
        order_verification=OrderVerification("not_found"),
    )
    raw = b"synthetic receipt order-a; do not store me in plaintext"
    evidence = store_encrypted_artifacts(
        db, tenant_id="tenant-a", claim_id=claim["claim_id"],
        files=[{"filename": "../../receipt.jpg", "content_type": "image/jpeg", "bytes": raw}],
        actor_id="buyer-a", store=store,
    )[0]
    row = db.execute(text("SELECT object_key,original_name_sanitized FROM return_evidence_object")).fetchone()
    stored_bytes = (tmp_path / row[0]).read_bytes()
    assert raw not in stored_bytes
    assert stored_bytes.startswith(b"SQRE2")
    assert row[1] == "receipt.jpg"
    assert load_encrypted_artifact(
        db, tenant_id="tenant-a", claim_id=claim["claim_id"], evidence_id=evidence["evidence_id"],
        actor_id="worker", purpose="test_analysis", store=store,
    ) == raw
    # Activating a new wrapping key does not strand evidence written by the old
    # version while the declared rotation keyring retains both versions.
    key_v2 = bytes(reversed(range(32)))
    monkeypatch.setenv(
        "RETURN_EVIDENCE_KEYS",
        f"v1:{base64.urlsafe_b64encode(key).decode()},v2:{key_v2.hex()}",
    )
    monkeypatch.setenv("RETURN_EVIDENCE_ACTIVE_KEY_ID", "v2")
    assert load_encrypted_artifact(
        db, tenant_id="tenant-a", claim_id=claim["claim_id"], evidence_id=evidence["evidence_id"],
        actor_id="worker", purpose="rotation_read_test", store=store,
    ) == raw
    with pytest.raises(LookupError):
        load_encrypted_artifact(
            db, tenant_id="tenant-b", claim_id=claim["claim_id"], evidence_id=evidence["evidence_id"],
            actor_id="worker", purpose="test_analysis", store=store,
        )
    actions = [row[0] for row in db.execute(text("SELECT action FROM return_evidence_access_audit"))]
    assert actions == ["encrypted_evidence_stored", "read", "read"]


def test_legal_hold_prevents_retention_deletion(db, tmp_path, monkeypatch):
    monkeypatch.setenv("RETURN_EVIDENCE_KEYS", f"v1:{bytes(range(32)).hex()}")
    store = LocalEvidenceObjectStore(tmp_path)
    claim = create_claim(
        db, tenant_id="tenant-a", claimant_id="buyer-a", sku="SKU-1", description="broken",
        order_verification=OrderVerification("found", order_id="order-a"),
    )
    evidence = store_encrypted_artifacts(
        db, tenant_id="tenant-a", claim_id=claim["claim_id"],
        files=[{"filename": "proof.jpg", "content_type": "image/jpeg", "bytes": b"proof"}],
        actor_id="buyer-a", store=store,
    )[0]
    db.execute(text("UPDATE return_evidence_object SET retention_until='2020-01-01T00:00:00+00:00'"))
    set_evidence_legal_hold(
        db, tenant_id="tenant-a", claim_id=claim["claim_id"], evidence_id=evidence["evidence_id"],
        enabled=True, actor_id="legal-1", purpose="active_dispute",
    )
    assert purge_expired_return_evidence(
        db, actor_id="retention-worker", purpose="scheduled_retention", store=store,
        now=datetime.now(timezone.utc),
    ) == 0
    set_evidence_legal_hold(
        db, tenant_id="tenant-a", claim_id=claim["claim_id"], evidence_id=evidence["evidence_id"],
        enabled=False, actor_id="legal-1", purpose="dispute_resolved",
    )
    assert purge_expired_return_evidence(
        db, actor_id="retention-worker", purpose="scheduled_retention", store=store,
        now=datetime.now(timezone.utc) + timedelta(days=1),
    ) == 1


def test_lifecycle_is_append_only_and_rejects_illegal_jumps(db):
    claim = create_claim(
        db, tenant_id="tenant-a", claimant_id="buyer-a", sku="SKU-1", description="broken",
        order_verification=OrderVerification("found", order_id="order-a"),
    )
    queue_evidence_job(db, tenant_id="tenant-a", claim_id=claim["claim_id"])
    changed = transition_claim(
        db, tenant_id="tenant-a", claim_id=claim["claim_id"], to_status="under_review",
        actor_type="system", actor_id="worker",
    )
    assert changed["version"] == 2
    with pytest.raises(ValueError, match="illegal_return_claim_transition"):
        transition_claim(
            db, tenant_id="tenant-a", claim_id=claim["claim_id"], to_status="refunded",
            actor_type="operator", actor_id="operator-a",
        )
    view = get_claim(db, tenant_id="tenant-a", claim_id=claim["claim_id"], claimant_id="buyer-a")
    assert view["status"] == "under_review"
    assert [event["to_status"] for event in view["timeline"]] == ["evidence_pending", "under_review"]
    with pytest.raises(LookupError):
        get_claim(db, tenant_id="tenant-a", claim_id=claim["claim_id"], claimant_id="buyer-b")


def test_duplicate_evidence_and_velocity_require_review_without_claiming_fraud(db):
    first = create_claim(
        db, tenant_id="tenant-a", claimant_id="buyer-a", sku="SKU-1", description="broken",
        order_verification=OrderVerification("found", order_id="order-a"),
    )
    digest = "a" * 64
    db.execute(text(
        "INSERT INTO return_evidence_object VALUES "
        "('e1','tenant-a',:claim,'object-key',:digest,'image/png','proof.png',10,"
        "'AES-256-GCM','v1','2099-01-01T00:00:00Z',0,'2026-08-04T00:00:00Z')"
    ), {"claim": first["claim_id"], "digest": digest})
    result = assess_return_claim_abuse(
        db, tenant_id="tenant-a", claimant_id="buyer-a", order_id="order-a",
        evidence_digests=[digest],
    )
    assert result.status == "review_required"
    assert result.reasons == ("duplicate_evidence_review",)


def test_hard_claim_velocity_limit_is_typed(db, monkeypatch):
    monkeypatch.setenv("RETURN_CLAIM_HARD_LIMIT_24H", "2")
    for index in range(2):
        create_claim(
            db, tenant_id="tenant-a", claimant_id="buyer-a", sku=f"SKU-{index}",
            description="broken", order_verification=OrderVerification("not_found"),
        )
    with pytest.raises(PermissionError, match="return_claim_velocity_limit_exceeded"):
        assess_return_claim_abuse(
            db, tenant_id="tenant-a", claimant_id="buyer-a", order_id=None,
            evidence_digests=[],
        )


def test_azure_blob_adapter_uses_private_workload_identity_client(monkeypatch):
    data: dict[str, bytes] = {}

    class Download:
        def __init__(self, value):
            self.value = value

        def readall(self):
            return self.value

    class Blob:
        def __init__(self, key):
            self.key = key

        def upload_blob(self, content, *, overwrite):
            assert overwrite is False
            if self.key in data:
                raise FileExistsError(self.key)
            data[self.key] = content

        def download_blob(self):
            return Download(data[self.key])

        def delete_blob(self, *, delete_snapshots):
            assert delete_snapshots == "include"
            data.pop(self.key)

    class Container:
        def get_blob_client(self, key):
            return Blob(key)

    monkeypatch.setattr("src.app.providers.azure.get_blob_container", lambda *_args: Container())
    store = AzureBlobEvidenceObjectStore(
        account_url="https://private.blob.core.windows.net", container="return-evidence"
    )
    store.put_if_absent("tenant/claim/evidence.aesgcm", b"ciphertext")
    assert store.read("tenant/claim/evidence.aesgcm") == b"ciphertext"
    store.delete("tenant/claim/evidence.aesgcm")
    assert data == {}


def test_authenticated_intake_is_fast_encrypted_and_idempotent(db, tmp_path, monkeypatch):
    _seed_order(db)
    secret = "return-endpoint-secret"
    now = int(time.time())
    access_token = jwt.encode(
        {
            "sub": "buyer-a", "typ": "access", "iat": now, "exp": now + 300,
            "iss": "shopsquire", "aud": "shopsquire-api",
        },
        secret,
        algorithm="HS256",
    )
    monkeypatch.setenv("JWT_SIGNING_KEY", secret)
    monkeypatch.setenv("BUYER_TENANT_BINDINGS_JSON", '{"buyer-a":["tenant-a"]}')
    monkeypatch.setenv("RETURN_EVIDENCE_KEYS", f"v1:{bytes(range(32)).hex()}")
    monkeypatch.setenv("RETURN_EVIDENCE_OBJECT_ROOT", str(tmp_path))

    @contextmanager
    def _session():
        yield db

    monkeypatch.setattr("src.app.routers.returns.db_session", _session)
    monkeypatch.setattr(
        "src.app.tasks.return_evidence_tasks.process_return_evidence.delay",
        lambda *_args, **_kwargs: None,
    )
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/returns/claims",
        "headers": [
            (b"authorization", f"Bearer {access_token}".encode()),
            (b"idempotency-key", b"return-idem-0001"),
        ],
    })
    body = {
        "sku": "SKU-1",
        "order_id": "order-a",
        "description": "screen failed after boot",
        "images": [{
            "filename": "receipt.png",
            "content_type": "image/png",
            "b64": base64.b64encode(b"synthetic return evidence").decode(),
        }],
    }
    tenant_token = set_active_tenant_id("tenant-a")
    try:
        started = time.perf_counter()
        first = create_return_claim(body, request)
        assert time.perf_counter() - started < 1.0
        replay = create_return_claim(body, request)
    finally:
        reset_active_tenant_id(tenant_token)

    first_payload = json.loads(first.body)
    replay_payload = json.loads(replay.body)
    assert first.status_code == 202
    assert first_payload["status"] == "evidence_pending"
    assert first_payload["order_verification"]["status"] == "found"
    assert replay_payload["idempotent_replay"] is True
    assert replay_payload["claim_id"] == first_payload["claim_id"]
    assert db.execute(text("SELECT COUNT(*) FROM return_claim")).scalar_one() == 1
    assert db.execute(text("SELECT COUNT(*) FROM return_evidence_object")).scalar_one() == 1
    stored = next(tmp_path.rglob("*.aesgcm")).read_bytes()
    assert b"synthetic return evidence" not in stored


def test_hostile_pdf_archive_office_and_csv_are_quarantined_by_return_lifecycle(
    db, tmp_path, monkeypatch,
):
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("nested.zip", b"not-a-real-archive")
    files = [
        {
            "filename": "supplier_quote_indirect_injection.pdf",
            "content_type": "application/pdf",
            "bytes": (
                b"%PDF-1.7\n/Catalog /OpenAction << /S /JavaScript "
                b"/JS (inert-test-marker) >> /Launch /EmbeddedFile\n%%EOF"
            ),
        },
        {
            "filename": "nested_archive_depth4.zip",
            "content_type": "application/zip",
            "bytes": nested.getvalue(),
        },
        {
            "filename": "supplier_pricelist_formula_injection.csv",
            "content_type": "text/csv",
            "bytes": b"sku,price,note\nSKU-1,100,=HYPERLINK(\"https://example.invalid\",\"review\")\n",
        },
        {
            "filename": "repair-provider.docm",
            "content_type": "application/vnd.ms-word.document.macroEnabled.12",
            "bytes": synthetic_xlsm_bytes(),
        },
    ]
    monkeypatch.setenv("RETURN_EVIDENCE_KEYS", f"v1:{bytes(range(32)).hex()}")
    monkeypatch.setenv("RETURN_EVIDENCE_OBJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("RETURN_EVIDENCE_STORAGE_PROVIDER", "local")
    claim = create_claim(
        db, tenant_id="tenant-a", claimant_id="buyer-a", sku="SKU-1", description="repair request",
        order_verification=OrderVerification("found", order_id="order-a"),
    )
    store_encrypted_artifacts(
        db, tenant_id="tenant-a", claim_id=claim["claim_id"], files=files,
        actor_id="buyer-a",
    )
    job_id = queue_evidence_job(db, tenant_id="tenant-a", claim_id=claim["claim_id"])
    db.commit()

    @contextmanager
    def _session():
        yield db

    monkeypatch.setattr("src.app.tasks.return_evidence_tasks.db_session", _session)
    result = _process_return_evidence(tenant_id="tenant-a", job_id=job_id)
    assert result["status"] == "quarantined"
    job = db.execute(text(
        "SELECT status,security_status FROM return_evidence_job WHERE id=:job"
    ), {"job": job_id}).fetchone()
    assert tuple(job) == ("quarantined", "quarantined")
    claim_status = db.execute(text(
        "SELECT status FROM return_claim WHERE id=:claim"
    ), {"claim": claim["claim_id"]}).scalar_one()
    assert claim_status == "evidence_pending"
    observations = [json.loads(row[0]) for row in db.execute(text(
        "SELECT sanitized_json FROM return_evidence_observation "
        "WHERE claim_id=:claim AND observation_type='security_verdict'"
    ), {"claim": claim["claim_id"]})]
    reasons = {reason for item in observations for reason in item.get("reasons", [])}
    assert "pdf_active_content" in reasons
    assert "spreadsheet_formula_neutralized" in reasons
    assert "office_macro_content" in reasons
    assert any(reason.startswith("archive:") for reason in reasons)
