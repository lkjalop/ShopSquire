"""Screenshot 31 residual: "gaming development" must classify as the DEVELOPER persona, not the
consumer GAMER persona. The use-case already resolves to game_development, but the persona detector
matched gamer's `\\bgaming\\b` while developer's pattern required literal "game" (not "gaming"), so
buyer_persona lied (gamer) on a game-dev workstation request."""
from __future__ import annotations

from src.app.services.recommend_persona import detect_buyer_persona, reset_cache


def test_gaming_development_is_developer_not_gamer():
    reset_cache()
    assert detect_buyer_persona(
        "i need 25 laptops for gaming development, total budget is 41000") == "developer"


def test_game_development_variants_are_developer():
    reset_cache()
    for q in ("laptops for game development", "gaming developer workstation",
              "we build games in unity and unreal", "game dev machine"):
        assert detect_buyer_persona(q) == "developer", q


def test_plain_gaming_stays_gamer():
    reset_cache()
    for q in ("gaming laptop under 2000 with rtx", "best laptop for valorant at 144fps",
              "fortnite and fps gaming"):
        assert detect_buyer_persona(q) == "gamer", q
