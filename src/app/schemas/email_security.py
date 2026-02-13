from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class EmailAttachment(BaseModel):
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
    tenant_id: Optional[str] = Field(default=None, description="Optional tenant scope; can also be provided via X-Tenant-Id header.")
    message_id: Optional[str] = Field(default=None, description="Stable message id (used for dedupe).")
    from_addr: str
    reply_to: Optional[str] = None
    subject: Optional[str] = ""
    body: Optional[str] = ""
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
    decision_id: Optional[str] = None
    decision_trace_id: Optional[str] = None
