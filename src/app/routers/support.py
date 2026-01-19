from fastapi import APIRouter


router = APIRouter(prefix="/api/v1/support", tags=["support"])


@router.post("/answer")
def answer(question: str):
    # MVP stub response
    return {"answer": f"Thanks! We'll get back on: {question[:80]}"}


@router.post("/intents")
def intents(text: str):
    lower = text.lower()
    rules = [
        ("refund", "refund_request", 0.9),
        ("price", "pricing", 0.8),
        ("discount", "pricing", 0.8),
        ("order", "order_status", 0.85),
        ("help", "general_support", 0.7),
        ("support", "general_support", 0.7),
    ]
    for kw, intent, conf in rules:
        if kw in lower:
            return {"intent": intent, "confidence": conf}
    return {"intent": "unknown", "confidence": 0.3}
