from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Dict, List, Optional


class EmailAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., description="Attachment filename.")
    content_type: Optional[str] = None
    size_bytes: Optional[int] = Field(default=None, ge=0)
    content_b64: Optional[str] = Field(default=None, description="Optional base64 attachment bytes for in-endpoint parsing.")
    sha256: Optional[str] = Field(default=None, description="Optional attachment hash for IOC matching.")
    extracted_text: Optional[str] = Field(default=None, description="Optional OCR/text extracted from the attachment.")
    template_hash: Optional[str] = Field(default=None, description="Optional document template hash for drift checks.")
    logo_hash: Optional[str] = Field(default=None, description="Optional logo perceptual hash from the document.")
    layout_hash: Optional[str] = Field(default=None, description="Optional layout hash from document structure analysis.")
    edited_regions: Optional[int] = Field(default=None, ge=0, description="Optional count of suspicious edited regions.")
    compression_artifact_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # Lightweight PDF forensics / embedded indicators (optional)
    pdf_producer: Optional[str] = None
    pdf_creator: Optional[str] = None
    embedded_files_count: Optional[int] = Field(default=None, ge=0)
    pdf_objstm_count: Optional[int] = Field(default=None, ge=0)
    pdf_xrefstm_present: Optional[bool] = None
    # Parsed payment fields and derived fingerprint (optional)
    bank_fields: Optional[Dict[str, Any]] = None
    extracted_bank_fingerprint: Optional[str] = None


class EmailEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: Optional[str] = Field(default=None, description="Optional tenant scope; can also be provided via X-Tenant-Id header.")
    message_id: Optional[str] = Field(default=None, description="Stable message id (used for dedupe).")
    from_addr: str
    reply_to: Optional[str] = None
    subject: Optional[str] = ""
    body: Optional[str] = ""
    headers: Optional[Dict[str, Any]] = Field(default=None, description="Optional raw message headers map.")
    received_headers: List[str] = Field(default_factory=list, description="Optional explicit Received header chain entries.")
    x_originating_ip: Optional[str] = Field(default=None, description="Optional X-Originating-IP value.")
    x_mailer: Optional[str] = Field(default=None, description="Optional X-Mailer fingerprint string.")
    attachments: List[EmailAttachment] = Field(default_factory=list)
    dmarc_fail: bool = Field(default=False, description="If caller already validated DMARC/SPF/DKIM and determined fail.")
    spf_result: Optional[str] = Field(default=None, description="Authentication-Results SPF verdict (pass/fail/softfail/neutral).")
    dkim_result: Optional[str] = Field(default=None, description="Authentication-Results DKIM verdict (pass/fail/neutral).")
    dmarc_result: Optional[str] = Field(default=None, description="DMARC alignment verdict (pass/fail/quarantine/reject).")
    dmarc_policy: Optional[str] = Field(default=None, description="DMARC policy from sender domain (none/quarantine/reject).")
    external_sender: Optional[bool] = Field(default=None, description="Whether message originated from outside org boundary.")
    vendor_domain: Optional[str] = Field(default=None, description="Expected vendor domain when evaluating supplier mail.")
    bank_fingerprint: Optional[str] = Field(default=None, description="Known vendor bank fingerprint/tokenized reference.")
    proposed_bank_fingerprint: Optional[str] = Field(default=None, description="Requested replacement bank fingerprint.")
    reply_chain_id: Optional[str] = Field(default=None, description="Current reply-chain id/message thread id.")
    prior_reply_chain_id: Optional[str] = Field(default=None, description="Previously observed trusted reply-chain id.")
    oob_verified: Optional[bool] = Field(default=False, description="Out-of-band verification completed for payment/bank change requests.")


class EmailEvaluateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: str
    verdict_action: Optional[str] = None
    route: Optional[str] = None
    escalation: Optional[str] = None
    reasons: List[str]
    tags: List[str]
    indicators: List[Dict[str, Any]]
    iocs: List[Dict[str, Any]]
    evidence_snapshot: Dict[str, Any]
    risk_band: Optional[str] = None
    playbook: Optional[Dict[str, Any]] = None
    policy_gate: Optional[Dict[str, Any]] = None
    llm_controls: Optional[Dict[str, Any]] = None
    llm_assist: Optional[Dict[str, Any]] = None
    enrichment: Optional[Dict[str, Any]] = None
    detonation: Optional[Dict[str, Any]] = None
    siem_handoff: Optional[Dict[str, Any]] = None
    fuzzy_signals: Optional[Dict[str, Any]] = None
    trust_case: Optional[Dict[str, Any]] = None
    access_policy: Optional[Dict[str, Any]] = None
    policy_actions: Optional[List[str]] = None
    ml_gate: Optional[Dict[str, Any]] = None
    ml_gate_shadow: Optional[Dict[str, Any]] = None
    threat_correlation: Optional[Dict[str, Any]] = None
    latency: Optional[Dict[str, Any]] = None
    sender_trust: Optional[Dict[str, Any]] = None
    applied_thresholds: Optional[Dict[str, Any]] = None
    bec_kill_chain: Optional[Dict[str, Any]] = None
    bec_kill_chain_stage: Optional[str] = None
    decision_id: Optional[str] = None
    decision_trace_id: Optional[str] = None
    dns_auth: Optional[Dict[str, Any]] = None
    playbook_run: Optional[Dict[str, Any]] = None
    semantic_bec_score: Optional[float] = None
    coverage_limits: Optional[Dict[str, Any]] = None
    explainability_card: Optional[Dict[str, Any]] = None
