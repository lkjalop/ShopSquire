import hashlib
import json
from pathlib import Path

from src.app.services.case_research_plan import build_case_research_plan


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "golden" / "open_world_unseen_certification_v1.json"
SEAL = ROOT / "tests" / "golden" / "open_world_unseen_certification_v1.sha256"
LIVE_INPUTS = ROOT / "tests" / "golden" / "open_world_live_certification_inputs_v1.json"
LIVE_SEAL = ROOT / "tests" / "golden" / "open_world_live_certification_inputs_v1.sha256"


def test_unseen_certification_corpus_matches_committed_seal():
    assert hashlib.sha256(CORPUS.read_bytes()).hexdigest() == SEAL.read_text().strip()


def test_live_input_matrix_matches_committed_seal():
    assert hashlib.sha256(LIVE_INPUTS.read_bytes()).hexdigest() == LIVE_SEAL.read_text().strip()


def test_holdout_prompts_get_bounded_non_authoritative_open_world_plans():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    for row in corpus["sealed_holdout"]:
        plan = build_case_research_plan(row["prompt"], allow_open_world=True)
        assert plan is not None, row["id"]
        assert plan.publisher_status == "unresolved", row["id"]
        assert plan.source_candidate_ids == [], row["id"]
        assert 1 <= len(plan.discovery_queries) <= 3, row["id"]
        assert {query.axis for query in plan.discovery_queries} == {
            "concept_and_software",
            "requirements_and_compatibility",
            "support_and_constraints",
        }, row["id"]
        assert plan.external_calls == 0, row["id"]
        assert plan.authority == "proposal_only", row["id"]
