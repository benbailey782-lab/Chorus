from fastapi import APIRouter

from backend.db import connect
from backend.schemas import HealthOut

router = APIRouter(prefix="/api", tags=["system"])
APP_VERSION = "0.1.0"


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    try:
        with connect() as conn:
            conn.execute("SELECT 1").fetchone()
        db_status = "ok"
    except Exception:
        db_status = "error"
    return HealthOut(version=APP_VERSION, db=db_status)
