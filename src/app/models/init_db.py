from src.app.models.db import engine
from src.app.models.orm import Base


def ensure_metadata() -> None:
    try:
        Base.metadata.create_all(engine)
    except Exception:
        # Silent best-effort; schema may already exist via SQL
        pass
