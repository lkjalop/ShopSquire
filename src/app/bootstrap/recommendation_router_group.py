"""Recommendation API registration, including the retained V2 compatibility boundary."""
from __future__ import annotations

from fastapi import FastAPI

from src.app.bootstrap.router_registration import RequiredRouter, register_required_routers
from src.app.routers.recommend_aux import router as recommend_aux_router
from src.app.routers.recommend_compat import router as recommend_compat_router
from src.app.routers.recommendation_checkout import router as recommendation_checkout_router
from src.app.routers.recommendation_explain import router as recommendation_explain_router
from src.app.routers.recommendation_feedback import router as recommendation_feedback_router
from src.app.routers.recommendation_nqe import router as recommendation_nqe_router


RECOMMENDATION_ROUTER_GROUP = (
    RequiredRouter("recommend_v2_compatibility", recommend_compat_router),
    RequiredRouter("recommend_aux", recommend_aux_router),
    RequiredRouter("recommendation_checkout", recommendation_checkout_router),
    RequiredRouter("recommendation_explain", recommendation_explain_router),
    RequiredRouter("recommendation_nqe", recommendation_nqe_router),
    RequiredRouter("recommendation_feedback", recommendation_feedback_router),
)


def register_recommendation_router_group(app: FastAPI) -> tuple[str, ...]:
    registered = register_required_routers(app, RECOMMENDATION_ROUTER_GROUP)
    app.state.recommendation_router_group = registered
    app.state.recommend_v2_compatibility_retained = True
    return registered


__all__ = ["RECOMMENDATION_ROUTER_GROUP", "register_recommendation_router_group"]
