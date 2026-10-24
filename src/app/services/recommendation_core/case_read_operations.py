"""Bounded, read-only references to an already owned procurement case."""
import re as _re

CASE_READ_OPERATION = _re.compile(
    r"\b(?:status|progress|where\s+(?:are|is)|what(?:'s|\s+is)\s+happening|"
    r"summari[sz]e|recap)\b|"
    r"\bremind\s+me\b.{0,80}\b(?:requested|quantity|budget|deadline|destination|order)\b|"
    r"\bhow\s+many\b.{0,80}\b(?:i|we)\s+(?:ask(?:ed)?|request(?:ed)?|order(?:ed)?)\b|"
    r"\bwhat\s+(?:is|was|are|were)\s+(?:my|our)\s+(?:budget|quantity|destination|deadline)\b|"
    r"\b(?:market\s+intelligence|supply\s+outlook)\b.{0,160}\b(?:current|existing|same)\s+(?:request|case|order)\b",
    _re.IGNORECASE,
)
