"""Knowledge pool (Lane-3 curated evidence) — selection, format, and fail-safe contract.

The pool must surface the RIGHT curated statements for a query (training floor for training
asks, inference tiers for inference asks, gaming tiers for gaming asks), stay silent when
nothing matches or the vertical has no pool file, cite every line as [kp:<id>], and respect
max_entries. All via the real config/knowledge_pool/electronics.json — these tests double as
a curation contract on that file.
"""
from src.app.services.knowledge_pool import knowledge_note, load_pool


def _top_line(note: str) -> str:
    """First bullet of the note (line after the header)."""
    lines = [ln for ln in note.splitlines() if ln.startswith("- ")]
    assert lines, f"note has no bullet lines: {note!r}"
    return lines[0]


def test_training_query_surfaces_16gb_floor():
    note = knowledge_note(
        "I want to train and fine-tune an LLM on this machine", profile_id="electronics"
    )
    assert note is not None
    assert "[kp:kp-vram-training-floor]" in note
    assert "16GB" in note


def test_inference_query_surfaces_7b_entry_not_training_floor_on_top():
    note = knowledge_note(
        "can I run a quantized 7B model for local inference on a laptop?",
        profile_id="electronics",
    )
    assert note is not None
    top = _top_line(note)
    assert "[kp:kp-vram-inference-7b]" in top
    assert "6-8GB" in top
    assert "[kp:kp-vram-training-floor]" not in top


def test_gaming_query_surfaces_gaming_tiers():
    note = knowledge_note(
        "gaming laptop for esports at 1080p with high fps", profile_id="electronics"
    )
    assert note is not None
    assert "[kp:kp-gaming-esports]" in note
    assert "144" in note  # the esports tier statement carries the 144 FPS / 144Hz numbers


def test_use_case_topic_bonus_boosts_matching_topic():
    # 'ai_ml' use-case slug loosely matches 'ai_*' topics (+2), lifting AI entries
    # over generic keyword-only hits for an otherwise ambiguous VRAM question.
    note = knowledge_note(
        "how much vram do I need?", use_case="ai_training", profile_id="electronics"
    )
    assert note is not None
    assert "[kp:kp-vram-training-floor]" in note


def test_no_match_query_returns_none():
    assert knowledge_note("purple giraffe wallpaper please", profile_id="electronics") is None


def test_empty_query_returns_none():
    assert knowledge_note("", profile_id="electronics") is None
    assert knowledge_note("   ", profile_id="electronics") is None


def test_missing_profile_file_returns_none():
    # A vertical with no pool file must be silence, never a crash and never an
    # electronics fallback (curated facts are vertical-specific).
    assert load_pool(profile_id="no_such_vertical_xyz") is None
    assert knowledge_note("train an llm", profile_id="no_such_vertical_xyz") is None


def test_note_format_has_header_and_citations():
    note = knowledge_note("training a large model locally", profile_id="electronics")
    assert note is not None
    assert note.startswith("DOMAIN KNOWLEDGE (platform-curated")
    assert "[kp:" in note
    for line in note.splitlines()[1:]:
        assert line.startswith("- ")
        assert "[kp:" in line and line.rstrip().endswith("]")


def test_max_entries_respected():
    broad = "gaming laptop with lots of ram and storage for video editing and esports"
    note = knowledge_note(broad, profile_id="electronics", max_entries=2)
    assert note is not None
    assert note.count("[kp:") == 2
    wider = knowledge_note(broad, profile_id="electronics", max_entries=4)
    assert wider is not None
    assert wider.count("[kp:") > 2  # the broad query really does hit more than 2 entries


def test_keyword_stem_matches_but_short_words_stay_word_bound():
    # 'train' (stem) must find 'training'; 'ram' must NOT fire inside 'program'.
    assert knowledge_note("training runs on this gpu", profile_id="electronics") is not None
    note = knowledge_note("a program for drawing", profile_id="electronics")
    if note is not None:  # if anything matched, it must not be the RAM entries
        assert "[kp:kp-ram-baseline]" not in note and "[kp:kp-ram-heavy]" not in note


def test_env_dir_override_missing_dir_is_silent(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_POOL_DIR", "config/does_not_exist_kp")
    assert knowledge_note("train an llm", profile_id="electronics") is None
