from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttachmentInput(StrictModel):
    name: Optional[str] = None
    content_type: Optional[str] = None
    content_b64: Optional[str] = None


class ResumeRole(StrictModel):
    title: str
    canonical_title: Optional[str] = None
    company: Optional[str] = None
    canonical_company: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    duration_months: int = 0
    snippet: Optional[str] = None


class ResumeEducation(StrictModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    snippet: Optional[str] = None


class ResumeSkill(StrictModel):
    raw: str
    canonical: str
    confidence: float = 1.0
    snippet: Optional[str] = None


class ResumeSchema(StrictModel):
    candidate_id: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    summary: Optional[str] = None
    years_experience: float = 0.0
    roles: List[ResumeRole] = Field(default_factory=list)
    skills: List[ResumeSkill] = Field(default_factory=list)
    education: List[ResumeEducation] = Field(default_factory=list)
    raw_text_hash: Optional[str] = None
    extraction_meta: Dict[str, Any] = Field(default_factory=dict)


class ParseResumeRequest(StrictModel):
    candidate_id: Optional[str] = None
    text: Optional[str] = None
    attachments: List[AttachmentInput] = Field(default_factory=list)
    source: Optional[str] = None


class ParseResumeResponse(StrictModel):
    resume: ResumeSchema
    citations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    pipeline: Dict[str, Any] = Field(default_factory=dict)


class JobRequirement(StrictModel):
    job_id: Optional[str] = None
    title: str
    location: Optional[str] = None
    remote_ok: bool = True
    min_years_experience: float = 0.0
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


class FeatureContribution(StrictModel):
    feature: str
    value: float
    weight: float
    contribution: float
    rationale: str
    citation: Optional[str] = None


class TriageThresholds(StrictModel):
    shortlist: float
    review: float
    reject: float = 0.0


class TriageOutcome(StrictModel):
    candidate_id: Optional[str] = None
    job_id: Optional[str] = None
    score: float
    decision: Literal["shortlist", "review", "reject"]
    route: Literal["allow", "review", "escalate", "block"] = "review"
    provisional: bool = False
    borderline: bool = False
    mode: Literal["standard", "blind", "hard_fairness"] = "standard"
    latency_path: Literal["fast", "slow", "batch"] = "fast"
    score_thresholds: TriageThresholds
    feature_contributions: List[FeatureContribution] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    fairness: Dict[str, Any] = Field(default_factory=dict)
    model_route: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None


class TriageRequest(StrictModel):
    job: JobRequirement
    resume: Optional[ResumeSchema] = None
    parse: Optional[ParseResumeRequest] = None
    mode: Literal["standard", "blind", "hard_fairness"] = "standard"
    latency_path: Literal["auto", "fast", "slow", "batch"] = "auto"
    use_semantic_cache: bool = True
    recruiter_context: Dict[str, Any] = Field(default_factory=dict)
    proxy_attributes: Dict[str, str] = Field(default_factory=dict)


class RankedCandidate(StrictModel):
    candidate_id: Optional[str] = None
    score: float
    decision: str
    rank: int
    route: str
    reasons: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    proxy_attributes: Dict[str, str] = Field(default_factory=dict)


class RankingRequest(StrictModel):
    job: JobRequirement
    candidates: List[TriageRequest]
    top_k: int = 10
    mode: Literal["standard", "blind", "hard_fairness"] = "standard"
    latency_path: Literal["auto", "fast", "slow", "batch"] = "auto"


class FairnessGroupMetric(StrictModel):
    proxy: str
    group: str
    positive_rate: float
    count: int


class FairnessAudit(StrictModel):
    proxy: str
    demographic_parity_diff: Optional[float] = None
    groups: List[FairnessGroupMetric] = Field(default_factory=list)
    n: int = 0


class RankingResponse(StrictModel):
    job_id: Optional[str] = None
    ranked: List[RankedCandidate] = Field(default_factory=list)
    fairness: List[FairnessAudit] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BatchScoreRequest(StrictModel):
    job: JobRequirement
    candidates: List[TriageRequest]
    batch_id: Optional[str] = None
    quantized_profile: str = "cpu-q4-nightly"
    mode: Literal["standard", "blind", "hard_fairness"] = "standard"


class BatchScoreResponse(StrictModel):
    batch_id: str
    processed: int
    shortlisted: int
    review: int
    rejected: int
    ranked: List[RankedCandidate] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FeedbackRecord(StrictModel):
    candidate_id: str
    job_id: str
    recruiter_decision: Literal["shortlist", "review", "reject"]
    model_decision: Optional[str] = None
    model_score: Optional[float] = None
    rationale: Optional[str] = None
    trace_id: Optional[str] = None
    proxy_attributes: Dict[str, str] = Field(default_factory=dict)


class FeedbackSummary(StrictModel):
    total: int
    acceptance_rate: float
    avg_model_score_shortlisted: float
    avg_model_score_rejected: float
    calibration_gap: float
    by_decision: Dict[str, int] = Field(default_factory=dict)

