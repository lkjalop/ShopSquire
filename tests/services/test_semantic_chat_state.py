from src.app.routers.chat import _persist_chat_structured_state
from src.app.services.recommendation_facade import _read_session_slice


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.store[key] = value

    def sadd(self, *_args) -> None:
        return None

    def expire(self, *_args) -> None:
        return None


BLOCKED = {
    "outcome": "clarify",
    "desired_outcome": "Run engine digital-twin simulations",
    "catalog_authority": "blocked",
    "next_permitted_action": "answer_material_questions",
    "concepts": [
        {
            "concept_id": "concept-digital-twin",
            "text": "digital twin",
            "relation": "required_capability",
            "status": "unresolved",
        }
    ],
    "questions": [
        {
            "question_id": "software",
            "question": "Which software and version will run?",
            "required_for": ["catalog_recommendation"],
        }
    ],
    "state_prevented": ["catalog_recommendation", "commerce_execution"],
}


def test_blocked_semantic_authority_round_trips_through_scoped_chat_memory() -> None:
    redis = FakeRedis()

    _persist_chat_structured_state(
        redis=redis,
        uid="buyer-1",
        query="Recommend a laptop for digital-twin simulation",
        products=[],
        trace_id="trace-1",
        assistant_message="I need the software and execution details first.",
        semantic_resolution=BLOCKED,
        case_anchor={"case_id": "semantic-case-1", "kind": "semantic_qualification"},
        tenant_id="tenant-a",
        session_epoch="epoch-7",
    )

    session = _read_session_slice(
        redis,
        "buyer-1",
        "tenant-a",
        session_epoch="epoch-7",
    )

    assert session["semantic_resolution"] == BLOCKED
    assert session["case_anchor"]["case_id"] == "semantic-case-1"
    assert session["session_epoch"] == "epoch-7"


def test_permitted_resolution_explicitly_clears_the_prior_blocker() -> None:
    redis = FakeRedis()
    values = dict(
        redis=redis,
        uid="buyer-1",
        products=[],
        trace_id="trace-1",
        tenant_id="tenant-a",
        session_epoch="epoch-7",
    )
    _persist_chat_structured_state(
        **values,
        query="Recommend a laptop for digital-twin simulation",
        semantic_resolution=BLOCKED,
    )
    _persist_chat_structured_state(
        **values,
        query="Siemens NX 2412, local execution, interactive results",
        semantic_resolution={"catalog_authority": "permitted", "outcome": "proceed"},
    )

    session = _read_session_slice(
        redis,
        "buyer-1",
        "tenant-a",
        session_epoch="epoch-7",
    )

    assert session["semantic_resolution"] is None
