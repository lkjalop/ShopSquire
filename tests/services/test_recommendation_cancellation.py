from src.app.services.recommendation_core.cancellation import (
    RecommendationCancellation,
    RecommendationCancelled,
)


def test_cancellation_is_cooperative_and_reasoned() -> None:
    token = RecommendationCancellation.with_timeout(10)
    token.raise_if_cancelled()
    token.cancel("buyer_disconnected")

    try:
        token.raise_if_cancelled()
    except RecommendationCancelled as exc:
        assert str(exc) == "buyer_disconnected"
    else:
        raise AssertionError("cancelled stage was allowed to continue")


def test_expired_deadline_cancels_without_an_explicit_event() -> None:
    token = RecommendationCancellation(deadline_monotonic=0)
    try:
        token.raise_if_cancelled()
    except RecommendationCancelled as exc:
        assert str(exc) == "request_deadline_exceeded"
    else:
        raise AssertionError("expired deadline was ignored")
