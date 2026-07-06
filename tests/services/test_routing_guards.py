"""Routing guards — greeting + off-domain must short-circuit the product pipeline, and must NOT swallow
real product queries. Pure detector tests (the endpoint wiring is exercised by the conversation battery)."""
from __future__ import annotations

import pytest

from src.app.routers.recommend import _query_signals_greeting, _query_signals_off_domain


@pytest.mark.parametrize("q", [
    "hi", "hello", "hey", "yo", "hiya", "howdy", "good morning", "good afternoon",
    "hello there", "hey there", "help", "menu", "get started",
    "what can you do?", "what do you do", "who are you", "how does this work", "can you help me",
])
def test_greetings_are_caught(q):
    assert _query_signals_greeting(q) is True


@pytest.mark.parametrize("q", [
    "help me find a gaming laptop", "hi-res monitor", "laptop for work",
    "gaming laptop under 2000", "start with a budget of 1500", "who makes the best laptop",
    "compare the dell and lenovo", "i need 20 laptops for my team",
])
def test_product_queries_are_not_greetings(q):
    assert _query_signals_greeting(q) is False


@pytest.mark.parametrize("q", [
    "what's the weather?", "will it rain today", "recipe for pasta", "how to cook rice",
    "who won the game last night", "the football score", "tell me a joke", "write me a poem",
    "what is the capital of france", "who is the president", "what is 15 x 32",
])
def test_off_domain_is_caught(q):
    assert _query_signals_off_domain(q) is True


@pytest.mark.parametrize("q", [
    "gaming laptop", "laptop with good battery life", "thinkpad for work",
    "is 1800 enough for gaming", "compare these two laptops", "laptop with 32gb ram",
    "cheapest laptop you have", "best laptop for university",
])
def test_product_queries_are_not_off_domain(q):
    assert _query_signals_off_domain(q) is False
