import os
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from src.app.routers import admin, pricing, inventory, support, events, payments
from src.app.routers.scoring import router as scoring_router
from src.app.routers.incident import router as incident_router
from src.app.routers.payments_paypal import router as payments_paypal
from src.app.routers.payments_revolut import router as payments_revolut
from src.app.routers.payments_googlepay import router as payments_googlepay
from src.app.routers.payments_afterpay import router as payments_afterpay
from src.app.routers.session_memory import router as session_memory_router
from src.app.routers.decisions import router as decisions_router
from src.app.routers.voice import router as voice_router
from src.app.routers.ui import router as ui_router
from src.app.models.init_db import ensure_metadata
from src.app.observability.tracing import init_tracer
from src.app.observability.metrics import router as metrics_router
from src.app.routers.sla import router as sla_router
from src.app.observability.metrics import router as metrics_router


def create_app() -> FastAPI:
    app = FastAPI(title="ShopSquire API", default_response_class=ORJSONResponse)
    ensure_metadata()
    init_tracer("shopsquire-api")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(admin.router)
    app.include_router(scoring_router)
    app.include_router(incident_router)
    app.include_router(metrics_router)
    app.include_router(sla_router)
    app.include_router(session_memory_router)
    app.include_router(decisions_router)
    app.include_router(voice_router)
    app.include_router(ui_router)
    app.include_router(metrics_router)
    app.include_router(pricing.router)
    app.include_router(inventory.router)
    app.include_router(support.router)
    app.include_router(events.router)
    app.include_router(payments.router)
    app.include_router(payments_paypal)
    app.include_router(payments_revolut)
    app.include_router(payments_googlepay)
    app.include_router(payments_afterpay)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("API_HOST", "0.0.0.0"), port=int(os.getenv("API_PORT", "8080")))
