"""Liveness/readiness — adskilt jf. standard Kubernetes-praksis.

/health: er processen overhovedet oppe? Bruges af en liveness probe.
/ready: kan den betjene trafik (kan den nå databasen)? Bruges af en readiness probe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentops.api.dependencies import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response, session: Session = Depends(get_db_session)) -> dict:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # bevidst bredt: enhver DB-fejl betyder "not ready", uanset årsag
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "reason": str(exc)}
    return {"status": "ready"}
