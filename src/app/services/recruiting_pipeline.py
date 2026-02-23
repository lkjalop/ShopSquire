from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.schemas.recruiting import (
    AttachmentInput,
    BatchScoreRequest,
    BatchScoreResponse,
    FairnessAudit,
    FairnessGroupMetric,
    FeatureContribution,
    FeedbackRecord,
    FeedbackSummary,
    JobRequirement,
    ParseResumeRequest,
    ParseResumeResponse,
    RankedCandidate,
    RankingRequest,
    RankingResponse,
    ResumeEducation,
    ResumeRole,
    ResumeSchema,
    ResumeSkill,
    TriageOutcome,
    TriageRequest,
    TriageThresholds,
)
from src.app.security.email_attachment_parser import hydrate_attachments_from_bytes
from src.app.services.embeddings import SimpleEmbeddings
from src.app.services.semantic_cache import SemanticCache


_EMAIL_PAT = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PAT = re.compile(r"(?:\+\d{1,3}\s*)?(?:\(?\d{2,4}\)?[\s-]*)\d{3,4}[\s-]*\d{3,4}")
_DATE_RANGE_PAT = re.compile(
    r"(?P<start>(?:[A-Za-z]{3,9}\s+\d{4}|\d{4}))\s*(?:-|to)\s*(?P<end>(?:[A-Za-z]{3,9}\s+\d{4}|present|current|\d{4}))",
    re.IGNORECASE,
)
_YEAR_PAT = re.compile(r"\b(?:19|20)\d{2}\b")
_SPLIT_SKILLS_PAT = re.compile(r"[,/|;]+")
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_SECTION_HEADERS: Dict[str, tuple[str, ...]] = {
    "skills": ("skills", "technical skills", "tech stack", "core skills"),
    "experience": ("experience", "work experience", "employment", "professional experience"),
    "education": ("education", "qualifications", "certifications"),
    "summary": ("summary", "profile", "professional summary", "about"),
}
_TITLE_ONTOLOGY: Dict[str, tuple[str, ...]] = {
    "software_engineer": (
        "software engineer",
        "swe",
        "developer",
        "full stack developer",
        "backend engineer",
        "frontend engineer",
    ),
    "data_analyst": ("data analyst", "bi analyst", "business intelligence analyst", "analytics analyst"),
    "data_engineer": ("data engineer", "etl engineer", "analytics engineer"),
    "project_manager": ("project manager", "program manager", "delivery manager"),
    "cybersecurity_analyst": ("security analyst", "cybersecurity analyst", "soc analyst", "secops analyst"),
    "product_manager": ("product manager", "product owner"),
    "support_engineer": ("support engineer", "technical support", "service desk analyst"),
}
_SKILL_ONTOLOGY: Dict[str, tuple[str, ...]] = {
    "python": ("python", "py"),
    "sql": ("sql", "postgresql", "mysql", "tsql"),
    "excel": ("excel", "spreadsheets"),
    "power_bi": ("power bi", "powerbi"),
    "tableau": ("tableau",),
    "aws": ("aws", "amazon web services"),
    "azure": ("azure", "microsoft azure"),
    "gcp": ("gcp", "google cloud"),
    "docker": ("docker", "containers"),
    "kubernetes": ("kubernetes", "k8s"),
    "javascript": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "react": ("react", "reactjs"),
    "fastapi": ("fastapi",),
    "machine_learning": ("machine learning", "ml", "scikit-learn"),
    "ocr": ("ocr", "optical character recognition", "tesseract"),
    "incident_response": ("incident response", "ir", "soc triage"),
    "endpoint_security": ("endpoint security", "edr", "xdr"),
    "threat_hunting": ("threat hunting",),
}
_LEGAL_SUFFIX_PAT = re.compile(r"\b(pty|ltd|inc|llc|corp|corporation|gmbh|limited|co)\b\.?", re.IGNORECASE)
_DEGREE_PAT = re.compile(r"\b(bachelor|master|phd|b\.?sc|m\.?sc|mba|diploma|certificate)\b", re.IGNORECASE)
_CACHE = SemanticCache(redis_url=os.getenv("REDIS_URL"), default_ttl=int(os.getenv("RECRUITING_CACHE_TTL_SEC", "900")))


def _norm_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _hash16(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def _to_lines(text: str) -> List[str]:
    return [ln.strip() for ln in str(text or "").splitlines() if ln and ln.strip()]


def _section_key(line: str) -> Optional[str]:
    low = _norm_text(line).lower().rstrip(":")
    for key, aliases in _SECTION_HEADERS.items():
        if low in aliases:
            return key
    return None


def _split_sections(lines: List[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {"header": []}
    cur = "header"
    for ln in lines:
        key = _section_key(ln)
        if key:
            cur = key
            out.setdefault(cur, [])
            continue
        out.setdefault(cur, []).append(ln)
    return out


def _parse_month_year(token: str) -> Tuple[int, int]:
    t = _norm_text(token).lower()
    if t in ("present", "current", "now"):
        now = datetime.utcnow()
        return now.year, now.month
    m = re.match(r"^(?P<y>\d{4})$", t)
    if m:
        return int(m.group("y")), 1
    m2 = re.match(r"^(?P<m>[a-z]{3,9})\s+(?P<y>\d{4})$", t)
    if m2:
        mm = _MONTHS.get(m2.group("m"), 1)
        return int(m2.group("y")), int(mm)
    m3 = _YEAR_PAT.search(t)
    if m3:
        return int(m3.group(0)), 1
    return 0, 0


def _months_between(start: Tuple[int, int], end: Tuple[int, int]) -> int:
    sy, sm = start
    ey, em = end
    if sy <= 0 or ey <= 0:
        return 0
    return max(0, (ey - sy) * 12 + (em - sm) + 1)


def _canonical_company(name: str | None) -> str | None:
    if not name:
        return None
    v = _LEGAL_SUFFIX_PAT.sub("", str(name or "")).strip(" -_,.")
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def _canonical_from_ontology(
    value: str,
    ontology: Dict[str, tuple[str, ...]],
    emb: Optional[SimpleEmbeddings] = None,
) -> Tuple[str, float]:
    raw = _norm_text(value).lower()
    if not raw:
        return "", 0.0
    for canonical, aliases in ontology.items():
        for alias in aliases:
            aa = _norm_text(alias).lower()
            if raw == aa or raw in aa or aa in raw:
                return canonical, 1.0
    if not emb:
        return raw.replace(" ", "_"), 0.0
    q = emb.embed_text(raw)
    best_key = None
    best_sim = 0.0
    for canonical in ontology.keys():
        sim = emb.cosine(q, emb.embed_text(canonical.replace("_", " ")))
        if sim > best_sim:
            best_sim = sim
            best_key = canonical
    if best_key and best_sim >= float(os.getenv("RECRUITING_FUZZY_MATCH_THRESHOLD", "0.72")):
        return best_key, float(round(best_sim, 4))
    return raw.replace(" ", "_"), float(round(best_sim, 4))


def _extract_text_from_attachments(attachments: List[AttachmentInput]) -> Tuple[str, List[str], List[str]]:
    if not attachments:
        return "", [], []
    payload = {"attachments": [a.model_dump() for a in attachments]}
    hydrated = hydrate_attachments_from_bytes(payload)
    out: List[str] = []
    citations: List[str] = []
    warnings: List[str] = []
    for att in hydrated.get("attachments") or []:
        txt = _norm_text(str((att or {}).get("extracted_text") or ""))
        nm = str((att or {}).get("name") or "attachment")
        if txt:
            out.append(txt)
            citations.append(f"{nm}: {txt[:180]}")
        if (att or {}).get("parse_errors"):
            warnings.append(f"{nm}: {','.join([str(x) for x in (att.get('parse_errors') or [])])}")
    return "\n".join(out).strip(), citations[:24], warnings[:24]


def _split_title_company(text: str) -> Tuple[str, Optional[str]]:
    raw = _norm_text(text)
    if not raw:
        return "", None
    parts: List[str] = []
    for marker in (" | ", " @ ", " at ", " - ", ", "):
        if marker in raw:
            parts = [p.strip() for p in raw.split(marker) if _norm_text(p)]
            if len(parts) >= 2:
                break
    if len(parts) >= 2:
        return parts[0], parts[1]
    return raw, None

def _extract_roles(sections: Dict[str, List[str]], emb: SimpleEmbeddings) -> List[ResumeRole]:
    roles: List[ResumeRole] = []
    source = (sections.get("experience") or []) + (sections.get("header") or [])
    for ln in source:
        m = _DATE_RANGE_PAT.search(ln)
        if not m:
            continue
        prefix = _norm_text(ln[: m.start()])
        title_raw, company_raw = _split_title_company(prefix)
        start_t = _parse_month_year(m.group("start"))
        end_t = _parse_month_year(m.group("end"))
        months = _months_between(start_t, end_t)
        title_canon, _ = _canonical_from_ontology(title_raw, _TITLE_ONTOLOGY, emb=emb)
        roles.append(
            ResumeRole(
                title=title_raw or "unknown",
                canonical_title=title_canon or None,
                company=company_raw,
                canonical_company=_canonical_company(company_raw),
                start_date=_norm_text(m.group("start")),
                end_date=_norm_text(m.group("end")),
                duration_months=months,
                snippet=_norm_text(ln)[:220],
            )
        )
    dedup: Dict[str, ResumeRole] = {}
    for role in roles:
        key = "|".join(
            [
                _norm_text(role.title).lower(),
                _norm_text(role.company).lower(),
                _norm_text(role.start_date).lower(),
                _norm_text(role.end_date).lower(),
            ]
        )
        dedup.setdefault(key, role)
    return list(dedup.values())[:20]


def _extract_education(sections: Dict[str, List[str]]) -> List[ResumeEducation]:
    edu: List[ResumeEducation] = []
    for ln in sections.get("education") or []:
        if len(ln) < 5:
            continue
        degree = None
        dm = _DEGREE_PAT.search(ln)
        if dm:
            degree = dm.group(0)
        years = _YEAR_PAT.findall(ln)
        start_date = years[0] if len(years) >= 1 else None
        end_date = years[-1] if len(years) >= 2 else None
        institution = ln
        if "-" in ln:
            institution = _norm_text(ln.split("-", 1)[0])
        edu.append(
            ResumeEducation(
                institution=institution[:120],
                degree=degree,
                field_of_study=None,
                start_date=start_date,
                end_date=end_date,
                snippet=_norm_text(ln)[:220],
            )
        )
    return edu[:12]


def _extract_skills(sections: Dict[str, List[str]], full_text: str, emb: SimpleEmbeddings) -> List[ResumeSkill]:
    skills: Dict[str, ResumeSkill] = {}
    raw_lines = list(sections.get("skills") or [])
    if not raw_lines:
        for ln in _to_lines(full_text):
            if any(tok in ln.lower() for tok in ("skills", "stack", "technologies")):
                raw_lines.append(ln)
    candidates: List[str] = []
    for ln in raw_lines:
        for tok in _SPLIT_SKILLS_PAT.split(ln):
            t = _norm_text(tok)
            if len(t) >= 2:
                candidates.append(t)
    low_text = full_text.lower()
    for canonical, aliases in _SKILL_ONTOLOGY.items():
        for alias in aliases:
            if _norm_text(alias).lower() in low_text:
                candidates.append(alias)
    for raw in candidates:
        canonical, conf = _canonical_from_ontology(raw, _SKILL_ONTOLOGY, emb=emb)
        if not canonical:
            continue
        prev = skills.get(canonical)
        candidate = ResumeSkill(raw=raw, canonical=canonical, confidence=conf, snippet=raw[:120])
        if not prev or float(prev.confidence) < float(candidate.confidence):
            skills[canonical] = candidate
    return list(skills.values())[:60]


def parse_resume(req: ParseResumeRequest) -> ParseResumeResponse:
    emb = SimpleEmbeddings()
    body_text = str(req.text or "").replace("\r\n", "\n").strip()
    att_text, att_citations, att_warnings = _extract_text_from_attachments(req.attachments or [])
    full_text = "\n".join([x for x in [body_text, att_text] if str(x or "").strip()]).strip()
    lines = _to_lines(full_text)
    sections = _split_sections(lines)

    warnings: List[str] = []
    warnings.extend(att_warnings)
    if not full_text:
        warnings.append("empty_resume_text")

    full_name = None
    email = None
    phone = None
    location = None

    for ln in sections.get("header", [])[:12]:
        if not email:
            m = _EMAIL_PAT.search(ln)
            if m:
                email = m.group(0)
        if not phone:
            m = _PHONE_PAT.search(ln)
            if m:
                phone = _norm_text(m.group(0))
        if not full_name:
            if (
                not _EMAIL_PAT.search(ln)
                and not _PHONE_PAT.search(ln)
                and len(ln.split()) <= 6
                and not re.search(r"\d", ln)
            ):
                full_name = ln.strip()
        if not location:
            if "," in ln and not _EMAIL_PAT.search(ln) and len(ln) <= 80:
                location = ln.strip()

    summary = " ".join((sections.get("summary") or [])[:3]).strip() or None
    roles = _extract_roles(sections, emb=emb)
    education = _extract_education(sections)
    skills = _extract_skills(sections, full_text, emb=emb)

    total_months = sum(max(0, int(r.duration_months or 0)) for r in roles)
    years_experience = round(float(total_months) / 12.0, 2) if total_months > 0 else 0.0
    if years_experience <= 0:
        years = [int(y) for y in _YEAR_PAT.findall(full_text)]
        if years:
            years_experience = float(max(0, max(years) - min(years)))

    citations: List[str] = []
    citations.extend(att_citations)
    citations.extend([f"header: {x[:160]}" for x in sections.get("header", [])[:3]])
    if summary:
        citations.append(f"summary: {summary[:160]}")
    citations.extend([f"experience: {x.snippet}" for x in roles[:3] if x.snippet])
    citations.extend([f"skills: {x.raw}" for x in skills[:8]])

    resume = ResumeSchema(
        candidate_id=req.candidate_id,
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        summary=summary,
        years_experience=max(0.0, float(years_experience)),
        roles=roles,
        skills=skills,
        education=education,
        raw_text_hash=_hash16(full_text),
        extraction_meta={
            "source": req.source or "unknown",
            "deterministic": True,
            "layout_aware": True,
            "sections": sorted([k for k in sections.keys() if k]),
            "line_count": len(lines),
            "attachment_count": len(req.attachments or []),
        },
    )
    return ParseResumeResponse(
        resume=resume,
        citations=citations[:40],
        warnings=warnings[:20],
        pipeline={
            "stages": ["pdf_ocr_extract", "layout_split", "ontology_normalize", "schema_pack"],
            "parser": "deterministic-v1",
        },
    )


def _resume_to_text(resume: ResumeSchema) -> str:
    parts: List[str] = []
    if resume.summary:
        parts.append(resume.summary)
    parts.extend([r.title for r in resume.roles if r.title])
    parts.extend([r.company for r in resume.roles if r.company])
    parts.extend([s.raw for s in resume.skills if s.raw])
    return _norm_text(" ".join(parts))


def _job_to_text(job: JobRequirement) -> str:
    parts: List[str] = [job.title or ""]
    parts.extend(job.required_skills or [])
    parts.extend(job.preferred_skills or [])
    parts.extend(job.keywords or [])
    return _norm_text(" ".join(parts))


def _canonicalize_skills(values: Iterable[str], emb: SimpleEmbeddings) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for raw in values:
        canonical, conf = _canonical_from_ontology(raw, _SKILL_ONTOLOGY, emb=emb)
        if canonical:
            out[canonical] = max(float(out.get(canonical, 0.0)), float(conf))
    return out


def _apply_mode(resume: ResumeSchema, mode: str) -> Tuple[ResumeSchema, List[str]]:
    copy = resume.model_copy(deep=True)
    suppressed: List[str] = []
    if mode in ("blind", "hard_fairness"):
        if copy.full_name:
            copy.full_name = None
            suppressed.append("full_name")
        if copy.email:
            copy.email = None
            suppressed.append("email")
        if copy.phone:
            copy.phone = None
            suppressed.append("phone")
    if mode == "hard_fairness":
        if copy.location:
            copy.location = None
            suppressed.append("location")
        if copy.roles:
            for role in copy.roles:
                if role.company:
                    role.company = None
                    suppressed.append("company")
    copy.extraction_meta = dict(copy.extraction_meta or {})
    copy.extraction_meta["suppressed_fields"] = sorted(list(dict.fromkeys(suppressed)))
    copy.extraction_meta["mode"] = mode
    return copy, copy.extraction_meta["suppressed_fields"]


def _thresholds() -> TriageThresholds:
    shortlist = float(os.getenv("RECRUITING_SHORTLIST_THRESHOLD", "0.72"))
    review = float(os.getenv("RECRUITING_REVIEW_THRESHOLD", "0.45"))
    if review > shortlist:
        review = max(0.0, shortlist - 0.15)
    return TriageThresholds(shortlist=shortlist, review=review, reject=0.0)


def _feature_value(contribs: List[FeatureContribution], name: str) -> float:
    for item in contribs:
        if item.feature == name:
            return float(item.value)
    return 0.0

def _build_feature_contribs(
    job: JobRequirement,
    resume: ResumeSchema,
    emb: SimpleEmbeddings,
) -> Tuple[List[FeatureContribution], List[str]]:
    contribs: List[FeatureContribution] = []
    citations: List[str] = []

    res_skill_map = _canonicalize_skills([s.raw for s in resume.skills], emb=emb)
    req_skill_map = _canonicalize_skills(job.required_skills or [], emb=emb)
    pref_skill_map = _canonicalize_skills(job.preferred_skills or [], emb=emb)
    req_hit = len(set(req_skill_map.keys()) & set(res_skill_map.keys()))
    pref_hit = len(set(pref_skill_map.keys()) & set(res_skill_map.keys()))

    req_ratio = float(req_hit) / float(max(1, len(req_skill_map)))
    pref_ratio = float(pref_hit) / float(max(1, len(pref_skill_map))) if pref_skill_map else 1.0
    contribs.append(
        FeatureContribution(
            feature="required_skill_match",
            value=round(req_ratio, 4),
            weight=0.34,
            contribution=round(req_ratio * 0.34, 4),
            rationale=f"matched {req_hit}/{max(1, len(req_skill_map))} required skills",
            citation=f"skills: {', '.join(sorted(list(res_skill_map.keys()))[:8])}",
        )
    )
    contribs.append(
        FeatureContribution(
            feature="preferred_skill_match",
            value=round(pref_ratio, 4),
            weight=0.08,
            contribution=round(pref_ratio * 0.08, 4),
            rationale=f"matched {pref_hit}/{max(1, len(pref_skill_map))} preferred skills",
            citation=f"skills: {', '.join(sorted(list(res_skill_map.keys()))[:8])}",
        )
    )

    min_exp = max(0.0, float(job.min_years_experience or 0.0))
    exp_value = 1.0 if min_exp <= 0 else min(1.0, float(resume.years_experience or 0.0) / min_exp)
    contribs.append(
        FeatureContribution(
            feature="experience_years",
            value=round(exp_value, 4),
            weight=0.22,
            contribution=round(exp_value * 0.22, 4),
            rationale=f"{resume.years_experience:.2f} years vs {min_exp:.2f} required",
            citation=f"experience_years: {resume.years_experience}",
        )
    )

    job_title_canon, _ = _canonical_from_ontology(job.title or "", _TITLE_ONTOLOGY, emb=emb)
    title_match = 0.0
    top_role = None
    for role in resume.roles:
        top_role = role
        if job_title_canon and role.canonical_title == job_title_canon:
            title_match = 1.0
            break
        sim = emb.cosine(
            emb.embed_text((job.title or "").lower()),
            emb.embed_text((role.title or "").lower()),
        )
        title_match = max(title_match, float(sim))
    contribs.append(
        FeatureContribution(
            feature="title_alignment",
            value=round(title_match, 4),
            weight=0.16,
            contribution=round(title_match * 0.16, 4),
            rationale="role title alignment with target role",
            citation=(f"role: {top_role.title}" if top_role else None),
        )
    )

    loc = _norm_text(resume.location).lower()
    job_loc = _norm_text(job.location).lower()
    if not job_loc:
        loc_value = 1.0
    elif job.remote_ok:
        loc_value = 1.0 if not loc else (1.0 if job_loc in loc or loc in job_loc else 0.8)
    else:
        loc_value = 1.0 if loc and (job_loc in loc or loc in job_loc) else 0.0
    contribs.append(
        FeatureContribution(
            feature="location_alignment",
            value=round(loc_value, 4),
            weight=0.05,
            contribution=round(loc_value * 0.05, 4),
            rationale="location filter compatibility",
            citation=f"candidate_location: {resume.location}",
        )
    )

    job_text = _job_to_text(job)
    resume_text = _resume_to_text(resume)
    semantic = emb.cosine(emb.embed_text(job_text), emb.embed_text(resume_text))
    contribs.append(
        FeatureContribution(
            feature="semantic_similarity",
            value=round(float(semantic), 4),
            weight=0.15,
            contribution=round(float(semantic) * 0.15, 4),
            rationale="embedding similarity between resume and role context",
            citation=f"resume_hash: {resume.raw_text_hash}",
        )
    )

    for item in contribs:
        if item.citation:
            citations.append(item.citation)
    return contribs, citations[:24]


def _choose_latency_path(req: TriageRequest, resume: ResumeSchema) -> str:
    asked = str(req.latency_path or "auto")
    if asked in ("fast", "slow", "batch"):
        return asked
    if str(req.mode) == "hard_fairness":
        return "slow"
    if len(req.job.required_skills or []) >= 8:
        return "slow"
    if float(resume.years_experience or 0.0) <= 0.1:
        return "slow"
    return "fast"


def _cache_key(req: TriageRequest, resume: ResumeSchema, latency_path: str) -> str:
    payload = {
        "candidate_id": resume.candidate_id,
        "job_id": req.job.job_id,
        "job": req.job.model_dump(),
        "resume_hash": resume.raw_text_hash,
        "mode": req.mode,
        "latency_path": latency_path,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return f"recruiting:triage:{_hash16(raw)}"


def _ensure_feedback_table() -> None:
    with db_session() as db:
        db.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS recruiting_feedback (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    recruiter_decision TEXT NOT NULL,
                    model_decision TEXT,
                    model_score REAL,
                    rationale TEXT,
                    trace_id TEXT,
                    proxy_attributes_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.commit()


def _enqueue_manual_review_task(outcome: TriageOutcome) -> None:
    try:
        with db_session() as db:
            db.execute(
                sql_text(
                    """
                    CREATE TABLE IF NOT EXISTS human_review_tasks (
                        id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        decision_id TEXT,
                        ticket_id TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        reviewer_id TEXT,
                        rationale TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT
                    )
                    """
                )
            )
            task_id = str(uuid.uuid4())
            case_id = str(outcome.candidate_id or task_id)
            rationale = "; ".join(outcome.reasons[:4])
            db.execute(
                sql_text(
                    """
                    INSERT INTO human_review_tasks (id, case_id, decision_id, status, rationale, created_at)
                    VALUES (:id, :case_id, :decision_id, :status, :rationale, :created_at)
                    """
                ),
                {
                    "id": task_id,
                    "case_id": case_id,
                    "decision_id": outcome.trace_id,
                    "status": "pending",
                    "rationale": rationale[:800],
                    "created_at": datetime.utcnow().isoformat(),
                },
            )
            db.commit()
    except Exception:
        return


def triage_candidate(req: TriageRequest) -> TriageOutcome:
    emb = SimpleEmbeddings()
    resume = req.resume
    if resume is None:
        if req.parse is None:
            raise ValueError("triage_requires_resume_or_parse_request")
        parsed = parse_resume(req.parse)
        resume = parsed.resume
    resume, suppressed_fields = _apply_mode(resume, str(req.mode))

    thresholds = _thresholds()
    latency_path = _choose_latency_path(req, resume)
    cache_key = _cache_key(req, resume, latency_path)
    if req.use_semantic_cache and latency_path == "fast":
        cached = _CACHE.get(cache_key)
        if isinstance(cached, dict):
            out = TriageOutcome.model_validate(cached)
            out.metadata = dict(out.metadata or {})
            out.metadata["semantic_cache_hit"] = True
            return out

    contribs, citations = _build_feature_contribs(req.job, resume, emb=emb)
    score = max(0.0, min(1.0, sum(float(c.contribution) for c in contribs)))
    decision = "reject"
    if score >= float(thresholds.shortlist):
        decision = "shortlist"
    elif score >= float(thresholds.review):
        decision = "review"

    margin = float(os.getenv("RECRUITING_BORDERLINE_MARGIN", "0.05"))
    borderline = abs(score - float(thresholds.shortlist)) <= margin or abs(score - float(thresholds.review)) <= margin
    route = "allow" if decision == "shortlist" else ("review" if decision == "review" else "block")
    if borderline or str(req.mode) == "hard_fairness":
        route = "review"

    provisional = bool(latency_path == "fast" and borderline)
    model_route = {
        "model": (
            "local-quantized-recruiting-v1"
            if latency_path in ("fast", "batch")
            else "reasoning-mid-tier-interleaved-v1"
        ),
        "token_cap": int(os.getenv("RECRUITING_RESPONSE_TOKEN_CAP", "320")),
        "context_policy": "selective_context_injection",
    }
    reasons = [c.rationale for c in contribs[:6]]
    if suppressed_fields:
        reasons.append(f"fairness_mode_suppressed_fields={','.join(suppressed_fields)}")
    if borderline:
        reasons.append("borderline_score_requires_manual_review")

    outcome = TriageOutcome(
        candidate_id=resume.candidate_id,
        job_id=req.job.job_id,
        score=round(score, 4),
        decision=decision,  # type: ignore[arg-type]
        route=route,  # type: ignore[arg-type]
        provisional=provisional,
        borderline=borderline,
        mode=req.mode,
        latency_path=latency_path,  # type: ignore[arg-type]
        score_thresholds=thresholds,
        feature_contributions=contribs,
        citations=citations[:24],
        reasons=reasons[:12],
        fairness={
            "mode": req.mode,
            "suppressed_fields": suppressed_fields,
            "proxy_attributes": req.proxy_attributes or {},
            "monitor_only": True,
        },
        model_route=model_route,
        metadata={
            "semantic_cache_hit": False,
            "fast_path": latency_path == "fast",
            "job_required_skills_count": len(req.job.required_skills or []),
            "resume_skills_count": len(resume.skills or []),
        },
        trace_id=f"rec-{uuid.uuid4().hex[:20]}",
    )

    if req.use_semantic_cache and latency_path == "fast":
        _CACHE.set(cache_key, outcome.model_dump(), ex=int(os.getenv("RECRUITING_CACHE_TTL_SEC", "900")))

    if outcome.borderline or outcome.decision == "review":
        _enqueue_manual_review_task(outcome)
    return outcome

def _compute_fairness_audits(
    ranked: List[RankedCandidate],
    requests: List[TriageRequest],
) -> List[FairnessAudit]:
    by_proxy: Dict[str, Dict[str, List[int]]] = {}
    req_by_candidate: Dict[str, Dict[str, str]] = {}
    for req in requests:
        cid = str((req.resume.candidate_id if req.resume else None) or (req.parse.candidate_id if req.parse else "") or "")
        if cid:
            req_by_candidate[cid] = dict(req.proxy_attributes or {})
    for item in ranked:
        cid = str(item.candidate_id or "")
        attrs = req_by_candidate.get(cid) or dict(item.proxy_attributes or {})
        is_positive = 1 if str(item.decision) == "shortlist" else 0
        for proxy, group in attrs.items():
            p = _norm_text(proxy)
            g = _norm_text(group)
            if not p or not g:
                continue
            by_proxy.setdefault(p, {}).setdefault(g, []).append(is_positive)

    audits: List[FairnessAudit] = []
    for proxy, groups in by_proxy.items():
        group_rates: List[float] = []
        rows: List[FairnessGroupMetric] = []
        total = 0
        for group, labels in groups.items():
            n = len(labels)
            total += n
            rate = float(sum(labels)) / float(max(1, n))
            group_rates.append(rate)
            rows.append(FairnessGroupMetric(proxy=proxy, group=group, positive_rate=round(rate, 4), count=n))
        diff = None
        if len(group_rates) >= 2:
            diff = round(max(group_rates) - min(group_rates), 4)
        audits.append(
            FairnessAudit(
                proxy=proxy,
                demographic_parity_diff=diff,
                groups=sorted(rows, key=lambda r: r.group),
                n=total,
            )
        )
    return audits


def rank_candidates(req: RankingRequest) -> RankingResponse:
    scored: List[Tuple[RankedCandidate, float]] = []
    for candidate_req in req.candidates:
        merged = candidate_req.model_copy(deep=True)
        merged.job = req.job
        merged.mode = req.mode
        merged.latency_path = req.latency_path
        outcome = triage_candidate(merged)
        semantic = _feature_value(outcome.feature_contributions, "semantic_similarity")
        rerank_score = float(outcome.score) + (0.03 if outcome.decision == "shortlist" else 0.0) + 0.05 * semantic
        scored.append(
            (
                RankedCandidate(
                    candidate_id=outcome.candidate_id,
                    score=round(float(outcome.score), 4),
                    decision=outcome.decision,
                    rank=0,
                    route=outcome.route,
                    reasons=outcome.reasons[:8],
                    citations=outcome.citations[:8],
                    metadata={
                        "triage_trace_id": outcome.trace_id,
                        "latency_path": outcome.latency_path,
                        "rerank_score": round(float(rerank_score), 4),
                    },
                    proxy_attributes=candidate_req.proxy_attributes or {},
                ),
                rerank_score,
            )
        )

    scored.sort(key=lambda item: float(item[1]), reverse=True)
    top = scored[: max(1, int(req.top_k or 10))]
    ranked: List[RankedCandidate] = []
    for idx, (cand, _) in enumerate(top, start=1):
        cand.rank = idx
        ranked.append(cand)

    fairness = _compute_fairness_audits(ranked, req.candidates)
    return RankingResponse(
        job_id=req.job.job_id,
        ranked=ranked,
        fairness=fairness,
        metadata={
            "mode": req.mode,
            "latency_path": req.latency_path,
            "count": len(ranked),
            "realtime": req.latency_path != "batch",
        },
    )


def batch_score(req: BatchScoreRequest) -> BatchScoreResponse:
    ranking = rank_candidates(
        RankingRequest(
            job=req.job,
            candidates=req.candidates,
            top_k=max(1, len(req.candidates)),
            mode=req.mode,
            latency_path="batch",
        )
    )
    ranked = ranking.ranked
    shortlist = sum(1 for r in ranked if r.decision == "shortlist")
    review = sum(1 for r in ranked if r.decision == "review")
    rejected = sum(1 for r in ranked if r.decision == "reject")
    return BatchScoreResponse(
        batch_id=req.batch_id or f"batch-{uuid.uuid4().hex[:10]}",
        processed=len(req.candidates),
        shortlisted=shortlist,
        review=review,
        rejected=rejected,
        ranked=ranked,
        metadata={
            "quantized_profile": req.quantized_profile,
            "batch_window": "nightly",
            "latency_path": "batch",
            "generated_at": datetime.utcnow().isoformat(),
        },
    )


def record_feedback(record: FeedbackRecord) -> Dict[str, Any]:
    _ensure_feedback_table()
    rid = str(uuid.uuid4())
    with db_session() as db:
        db.execute(
            sql_text(
                """
                INSERT INTO recruiting_feedback (
                    id, candidate_id, job_id, recruiter_decision, model_decision,
                    model_score, rationale, trace_id, proxy_attributes_json, created_at
                ) VALUES (
                    :id, :candidate_id, :job_id, :recruiter_decision, :model_decision,
                    :model_score, :rationale, :trace_id, :proxy_attributes_json, :created_at
                )
                """
            ),
            {
                "id": rid,
                "candidate_id": record.candidate_id,
                "job_id": record.job_id,
                "recruiter_decision": record.recruiter_decision,
                "model_decision": record.model_decision,
                "model_score": record.model_score,
                "rationale": record.rationale,
                "trace_id": record.trace_id,
                "proxy_attributes_json": json.dumps(record.proxy_attributes or {}, ensure_ascii=False),
                "created_at": datetime.utcnow().isoformat(),
            },
        )
        db.commit()
    return {"id": rid, "stored": True}


def feedback_summary(job_id: Optional[str] = None) -> FeedbackSummary:
    _ensure_feedback_table()
    rows: List[Dict[str, Any]] = []
    with db_session() as db:
        if job_id:
            result = db.execute(
                sql_text(
                    """
                    SELECT recruiter_decision, model_score
                    FROM recruiting_feedback
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            )
        else:
            result = db.execute(sql_text("SELECT recruiter_decision, model_score FROM recruiting_feedback"))
        for row in (result.fetchall() or []):
            values = tuple(row)
            if len(values) >= 2:
                rows.append({"recruiter_decision": values[0], "model_score": values[1]})

    total = len(rows)
    by_decision: Dict[str, int] = {"shortlist": 0, "review": 0, "reject": 0}
    shortlist_scores: List[float] = []
    reject_scores: List[float] = []
    for row in rows:
        dec = str(row.get("recruiter_decision") or "")
        if dec not in by_decision:
            by_decision[dec] = 0
        by_decision[dec] += 1
        score = row.get("model_score")
        if score is None:
            continue
        try:
            val = float(score)
        except Exception:
            continue
        if dec == "shortlist":
            shortlist_scores.append(val)
        if dec == "reject":
            reject_scores.append(val)

    acceptance_rate = float(by_decision.get("shortlist", 0)) / float(max(1, total))
    avg_short = sum(shortlist_scores) / max(1, len(shortlist_scores))
    avg_rej = sum(reject_scores) / max(1, len(reject_scores))
    calibration_gap = abs(avg_short - avg_rej) if (shortlist_scores and reject_scores) else 0.0
    return FeedbackSummary(
        total=total,
        acceptance_rate=round(acceptance_rate, 4),
        avg_model_score_shortlisted=round(float(avg_short), 4),
        avg_model_score_rejected=round(float(avg_rej), 4),
        calibration_gap=round(float(calibration_gap), 4),
        by_decision=by_decision,
    )
