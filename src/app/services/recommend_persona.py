"""Buyer persona detection + persona-calibrated LLM prompt context.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
CORE (vertical-agnostic):
  • detect_buyer_persona() / detect_buyer_persona_with_confidence() — the matching
    ALGORITHM (iterate patterns, score, return best).  Works for any vertical.
  • build_persona_prompt_context() — the DISPATCH mechanism (look up persona→prompt).

ADAPTER (product-type-specific, currently hardcoded electronics):
  • PERSONA_PATTERNS — the keywords are electronics/laptop-centric (ray tracing,
    CUDA, refresh rate, gaming titles). A pharmacy vertical would have different
    persona patterns (pharmacist, patient, caregiver, aged-care).
  • The prompt strings in build_persona_prompt_context() — every block references
    laptop specs (RAM, GPU VRAM, battery, display inches). Pharmacy/fashion would
    have entirely different emphasis guidance.

MIGRATION PATH (Phase 2):
  Add `persona_patterns` and `persona_prompt_templates` slots to StoreProfile.
  The CORE algorithm stays; the ADAPTER data moves to config/store_profiles/*.json.
  Transitional: inline electronics data retained as fallback when profile lacks slots.
"""
from __future__ import annotations

import re
from typing import Dict, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER DATA — Electronics-specific persona detection patterns.
# These should migrate to StoreProfile["persona_patterns"] in Phase 2.
# A pharmacy vertical would define: pharmacist, patient, caregiver, aged-care, etc.
# A fashion vertical would define: trend-follower, minimalist, plus-size, athleisure, etc.
# ═══════════════════════════════════════════════════════════════════════════════
PERSONA_PATTERNS: dict[str, list[str]] = {
    "student": [
        r"\buniversity\b", r"\bcollege\b", r"\bstudent\b", r"\bstudying\b",
        r"\bassignment\b", r"\blecture\b", r"\bsemester\b", r"\bcoursework\b",
        r"\bschool\b", r"\bclass\b", r"\bhomework\b", r"\bcampus\b",
    ],
    "high_schooler": [
        r"\bhigh\s?school\b", r"\byr\s?(?:7|8|9|10|11|12)\b", r"\byear\s?(?:7|8|9|10|11|12)\b",
        r"\bteen\b", r"\bHSC\b", r"\bVCE\b", r"\bATAR\b", r"\bgcse\b", r"\ba[\s-]?level\b",
        r"\bsecondary\s?school\b",
    ],
    "corporate": [
        r"\bcorporate\b", r"\boffice\b", r"\bwork\s?from\s?home\b", r"\bwfh\b",
        r"\bteams\b", r"\bzoom\b", r"\boutlook\b", r"\bexcel\b", r"\bpresentation\b",
        r"\bfor\s?work\b", r"\bwork\s?laptop\b", r"\bbusiness\b", r"\bprofessional\b",
    ],
    "job_hunter": [
        r"\bjob\s?hunt\b", r"\binterview\b", r"\bnew\s?job\b", r"\bcareer\s?change\b",
        r"\bjob\s?search\b", r"\bfreelance\b", r"\bstarting\s?a\s?new\s?job\b",
    ],
    "gamer": [
        r"\bgaming\b", r"\bfps\b", r"\bgame\b", r"\bvalorant\b", r"\bfortnite\b",
        r"\bcyberpunk\b", r"\bsteam\b", r"\belden\s?ring\b", r"\besports\b",
        r"\bray\s?trac\b", r"\bdlss\b", r"\brefresh\s?rate\b",
    ],
    "creative": [
        r"\bvideo\s?edit\b", r"\bcontent\s?creat\b", r"\byoutube\b", r"\bstreaming\b",
        r"\bpremiere\b", r"\bdavinci\b", r"\bphotoshop\b", r"\bblender\b",
        r"\bafter\s?effects\b", r"\bcolor\s?grad\b", r"\b4k\s?edit\b",
    ],
    "developer": [
        r"\bai\s?engineer\b", r"\bml\s?engineer\b", r"\bdata\s?scientist\b",
        r"\bpytorch\b", r"\btensorflow\b", r"\bcuda\b", r"\bdeep\s?learn\b",
        r"\bmachine\s?learn\b", r"\bai\s?train\b", r"\bllm\s?train\b",
        r"\bmodel\s?train\b", r"\bjupyter\b", r"\bnotebook\b",
    ],
    "engineer_student": [
        r"\bengineering\s?student\b", r"\bautocad\b", r"\bsolidworks\b",
        r"\bmatlab\b", r"\bfea\b", r"\bansys\b", r"\bmechanical\s?eng\b",
        r"\bcivil\s?eng\b", r"\belectrical\s?eng\b",
    ],
    "traveler": [
        r"\btravel\b", r"\bholiday\b", r"\bon\s?the\s?go\b", r"\bportable\b",
        r"\blightweight\b", r"\bbackpack\b", r"\bcommut\b", r"\bairport\b",
        r"\bdigital\s?nomad\b",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Persona detection algorithm (vertical-agnostic).
# Works against ANY set of patterns; the pattern dict is the adapter input.
# ═══════════════════════════════════════════════════════════════════════════════

def detect_buyer_persona(query: str | None) -> str | None:
    """Classify the buyer persona from query text. Returns the best-match persona or None."""
    q = str(query or "").lower()
    if not q:
        return None
    best, best_score = None, 0
    for persona, patterns in PERSONA_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, q, re.IGNORECASE))
        if score > best_score:
            best_score = score
            best = persona
    return best if best_score > 0 else None


def detect_buyer_persona_with_confidence(query: str | None) -> Tuple[str | None, float, Dict[str, int]]:
    q = str(query or "").lower()
    if not q:
        return None, 0.0, {}
    scores: Dict[str, int] = {}
    best: str | None = None
    best_score = 0
    for persona, patterns in PERSONA_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, q, re.IGNORECASE))
        if score > 0:
            scores[persona] = score
        if score > best_score:
            best_score = score
            best = persona
    if not best:
        return None, 0.0, scores
    conf = max(0.0, min(1.0, float(best_score) / 2.0))
    return best, conf, scores


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER DATA — Electronics-specific persona prompt templates.
# The DISPATCH mechanism (match persona → return string) is CORE.
# The CONTENT of each string is ADAPTER (laptop specs, GPU, battery, etc.).
# Phase 2: move templates to StoreProfile["persona_prompt_templates"].
# ═══════════════════════════════════════════════════════════════════════════════

def build_persona_prompt_context(
    use_case: str,
    buyer_persona: str,
    budget_bracket: str | None,
) -> str | None:
    """Return a persona-calibrated context block injected into the LLM prompt.

    Maps use_case + buyer_persona to: who the shopper is, which specs matter
    in plain English, and tone guidance.  Returns None for unknown personas.
    """
    uc = (use_case or "").lower().strip()
    bp = (buyer_persona or "").lower().strip()
    br = (budget_bracket or "").lower().strip()

    if bp == "high_schooler" or uc == "high_school":
        return (
            "Shopper: High school student (or a parent buying for them). Budget-conscious. Needs to survive a full school day.\n"
            "Emphasize: Battery life (8+ hours for school), how light and easy it is to carry, screen quality for reading and note-taking. A 2-in-1 or stylus support is a bonus.\n"
            "Tone: Simple and reassuring — no jargon. Say 'lasts all day on one charge' not '60Wh'. Say 'easy to carry to school' not '1.4kg'. Mention homework, notes, and streaming.\n"
            "Avoid: Gaming GPU specs, benchmark numbers, enterprise language."
        )

    if bp == "student" or uc == "university_general":
        return (
            "Shopper: University student. Balances lectures, research, socializing, and light media. Moderate budget.\n"
            "Emphasize: Portability + build quality (campus life is rough), battery for lecture days, enough RAM (16 GB) for browser tabs + note-taking + the occasional assignment crunch. A good keyboard matters.\n"
            "Tone: Relatable and encouraging — say 'handles 20 browser tabs and Zoom at the same time without breaking a sweat'. Mention real uni workflows (Google Docs, research PDFs, Netflix between classes).\n"
            "Avoid: Heavy workstation specs. Keep it practical and fun."
        )

    if uc in ("engineering_student", "computer_science_student") or bp == "engineer_student":
        return (
            "Shopper: Engineering / CS / architecture student. Runs simulation, CAD, or ML workloads that push hardware.\n"
            "Emphasize: RAM (32 GB strongly preferred — MATLAB, Docker, multiple VMs), dedicated GPU (even mid-range helps with CUDA / rendering), fast storage (SSD for large projects), build quality.\n"
            "Tone: Technically literate but outcome-focused — say 'compiles large projects 3× faster' not 'Intel i7-13700H at 4.9 GHz'. Reference real tools: MATLAB, SolidWorks, Docker, VS Code with containers.\n"
            "Avoid: Generic 'fast processor' language. These students know what CUDA cores do."
        )

    if uc == "data_science" or bp == "developer":
        return (
            "Shopper: Data scientist / AI-ML engineer. Trains models, runs Jupyter notebooks, maybe fine-tunes LLMs locally.\n"
            "Emphasize: GPU VRAM (12 GB+ for training), RAM (32-64 GB for large datasets), fast NVMe (dataset I/O), CUDA support (NVIDIA). A big display helps with notebooks.\n"
            "Tone: Peer-level technical — say '12 GB VRAM lets you fine-tune 7B-param models locally', 'enough RAM to keep your entire dataset in memory'. Reference PyTorch, HuggingFace, Jupyter.\n"
            "Avoid: Basic office specs. This shopper needs GPU horsepower."
        )

    if bp == "creative" or "content_creat" in uc or "video_edit" in uc:
        return (
            "Shopper: Content creator / video editor. Works in Premiere Pro, DaVinci Resolve, or After Effects. Color-accuracy matters.\n"
            "Emphasize: Color-accurate display (100% sRGB / DCI-P3), GPU for timeline preview (dedicated GPU strongly preferred), 32+ GB RAM (timeline scrubbing with effects), fast storage (proxy + export).\n"
            "Tone: Creative-pro — say 'scrubs 4K timelines without dropping frames', 'colors you can trust for client work'. Mention real workflows: color grading, multicam, After Effects compositions.\n"
            "Avoid: Gaming-focused language (refresh rate, FPS). These shoppers care about color, not frames."
        )

    if bp == "gamer" or "gaming" in uc:
        return (
            "Shopper: Gamer. Performance per dollar is king. Wants smooth frame rates in the titles they play.\n"
            "Emphasize: GPU tier (name the chip and what it means for their games — e.g. '4060 handles 1080p high settings at 80+ FPS in most titles'), high-refresh display (120+ Hz), thermal design (sustained performance, not throttling). RAM 16 GB is the sweet spot.\n"
            "Tone: Enthusiast but practical — say 'runs Cyberpunk at 60 FPS on High' not just 'RTX 4070'. Translate specs into FPS/resolution outcomes. Mention specific popular games if the query names them.\n"
            "Avoid: Battery life focus (gamers usually plug in). Avoid enterprise/office language."
        )

    if bp == "corporate" or uc in ("business_professional", "office_general", "office_executive"):
        return (
            "Shopper: Business professional / corporate user. Productivity, reliability, and security trump raw performance.\n"
            "Emphasize: Reliability and build quality (ThinkPad-tier), manageability (TPM, vPro if relevant), battery for meeting-to-meeting days, keyboard comfort, display clarity for spreadsheets and presentations.\n"
            "Tone: Professional and outcome-focused — say 'reliable enough you'll never miss a deadline', 'crisp display for hours of spreadsheet work'. Mention Teams, Outlook, multi-monitor setups.\n"
            "Avoid: Gaming specs, RGB lighting references. This is a tool purchase, not a toy."
        )

    if uc == "office_finance" or "finance" in uc or "accounting" in uc:
        return (
            "Shopper: Finance / accounting professional. Lives in Excel, ERP systems, and multi-monitor setups.\n"
            "Emphasize: Keyboard comfort (numbers entry for hours), display clarity (dense spreadsheets), multi-monitor support (Thunderbolt/USB-C docking), 32 GB RAM (large workbooks with pivot tables + Power Query).\n"
            "Tone: Efficiency-focused — say 'handles your largest workbooks without lag', 'connects to dual monitors with a single cable'. Mention Excel, Power BI, ERP systems.\n"
            "Avoid: GPU/gaming language. A discrete GPU is wasted spend here."
        )

    if uc == "medical_student":
        return (
            "Shopper: Medical student. Long study sessions, anatomy software, and clinical placement demands.\n"
            "Emphasize: Battery life (clinical placements without outlets), portability (ward rounds), display quality (anatomy diagrams and imaging), reliability.\n"
            "Tone: Supportive and practical — say 'lasts through a full day on the ward', 'clear enough for detailed anatomy diagrams'. Mention Anki, anatomy apps, clinical databases.\n"
            "Avoid: Gaming specs. A discrete GPU is unnecessary for med school."
        )

    if uc == "law_student":
        return (
            "Shopper: Law student. Case briefs, legal research databases, long reading/writing sessions. Pure productivity.\n"
            "Emphasize: Battery life (long library sessions), keyboard comfort (typing-heavy work — briefs, essays, memos), display clarity (reading-heavy), reliability.\n"
            "Tone: No-nonsense and direct. Say 'handles long case brief sessions without slowing down', 'comfortable to type on for hours'. Pure productivity focus.\n"
            "Avoid: GPU/gaming specs. A discrete GPU is wasted spend for a law student."
        )

    if bp == "traveler" or "travel" in uc:
        return (
            "Shopper: Frequent traveler. Works from airports, hotels, and client sites. Every gram and every hour of battery counts.\n"
            "Emphasize: Weight (lighter is always better), battery life (8+ hours real-world), build quality (bumps happen in transit), USB-C charging (one less adapter to carry).\n"
            "Tone: Practical and liberating. Say 'light enough to forget you're carrying it', 'lasts through a long-haul flight', 'tough enough for carry-on life'. Mention USB-C charging if available.\n"
            "Avoid: Heavy workstation specs. Freedom from outlets and weight are the wins."
        )

    if bp == "job_hunter":
        return (
            "Shopper: Job hunter or career changer. Starting a new chapter — needs something professional-looking, reliable, and interview-ready.\n"
            "Emphasize: Professional build and appearance (makes an impression), reliability, webcam and microphone quality (video interviews), keyboard comfort.\n"
            "Tone: Encouraging and practical. Say 'professional build for interviews and the first day on the job', 'reliable enough that it never lets you down in a crucial moment'.\n"
            "Avoid: Gaming specs. Focus on professionalism, reliability, and first impressions."
        )

    return None
