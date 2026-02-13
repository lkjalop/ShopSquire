import os
import pytest

from src.app.services.llm_provider import select_ollama_model, is_complex_query

@pytest.mark.parametrize("q,expected_complex", [
    ("under $1500 16GB RAM", False),
    ("compare and explain tradeoffs between business laptops for CAD and virtualization needing GPU passthrough with compliance", True),
])
def test_is_complex_query_basic(q, expected_complex):
    assert is_complex_query(q) == expected_complex


def test_select_ollama_model_defaults():
    # Defaults are set in service; ensure returns a non-empty model
    m = select_ollama_model("budget under $1000")
    assert isinstance(m, str) and len(m) > 0
