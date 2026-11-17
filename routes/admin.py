"""Admin-only operations endpoints for safe, clearly marked UI simulations.

Simulation requests publish preview events only. They do not write telemetry,
change device or vehicle state, or issue vehicle commands.
"""
from __future__ import annotations

import json
import queue
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth.principal import Principal
from auth.security import require_roles
from db import get_db
from enums import UserRole
from models import Alert, Device, Fleet, TelemetryReading, Vehicle

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

Scenario = Literal[
    "vehicle_moves",
    "battery_drops",
    "overspeed",
    "device_offline",
    "device_reconnects",
    "engine_fault",
]

SCENARIOS: dict[str, tuple[str, str]] = {
    "vehicle_moves": ("vehicle.location.updated", "Preview location update"),
    "battery_drops": ("alert.created", "Preview low battery alert"),
    "overspeed": ("alert.created", "Preview overspeed alert"),
    "device_offline": ("device.status.changed", "Preview offline status"),
    "device_reconnects": ("device.status.changed", "Preview online status"),
    "engine_fault": ("vehicle.health.updated", "Preview health change"),
}

EVENT_LIMIT = 100
_events: deque[dict[str, object]] = deque(maxlen=EVENT_LIMIT)
_subscribers: set[queue.Queue[dict[str, object]]] = set()
_event_lock = threading.Lock()


class SimulationRequest(BaseModel):
    vehicle_id: UUID
    scenario: Scenario


def _publish(event: dict[str, object]) -> None:
    with _event_lock:
        _events.append(event)
        for subscriber in tuple(_subscribers):
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                # A slow SSE client should not block simulation requests.
                pass


@router.get(
    "/system",
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def get_admin_system(db: Session = Depends(get_db)) -> dict[str, object]:
    """Return API/database health and the resource totals shown in the console."""
    try:
        db.execute(text("SELECT 1"))
        counts = {
            "fleets": db.scalar(select(func.count()).select_from(Fleet)) or 0,
            "vehicles": db.scalar(select(func.count()).select_from(Vehicle)) or 0,
            "devices": db.scalar(select(func.count()).select_from(Device)) or 0,
            "active_alerts": db.scalar(
                select(func.count()).select_from(Alert).where(Alert.resolved_at.is_(None))
            ) or 0,
            "telemetry_readings": db.scalar(
                select(func.count()).select_from(TelemetryReading)
            ) or 0,
        }
        database_status = "healthy"
    except SQLAlchemyError:
        db.rollback()
        database_status = "unavailable"
        counts = None

    return {
        "api": "healthy",
        "database": database_status,
        "counts": counts,
    }


@router.post(
    "/simulations",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def create_simulation(
    payload: SimulationRequest,
    principal: Principal = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Add a simulated event to the admin event stream without touching fleet data."""
    vehicle = db.get(Vehicle, payload.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    event_type, detail = SCENARIOS[payload.scenario]
    vehicle_label = vehicle.name or vehicle.registration_number or f"{vehicle.year} {vehicle.make} {vehicle.model}"
    event = {
        "id": str(uuid4()),
        "type": event_type,
        "vehicle_id": str(vehicle.id),
        "vehicle": vehicle_label,
        "scenario": payload.scenario,
        "at": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
        "simulated": True,
        "triggered_by": principal.username,
        "outcome": "preview_created",
    }
    _publish(event)
    return event


@router.get(
    "/events",
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def list_admin_events(
    limit: int = Query(default=30, ge=1, le=EVENT_LIMIT),
) -> dict[str, list[dict[str, object]]]:
    """Return recent preview events, newest first."""
    with _event_lock:
        events = list(_events)
    return {"items": list(reversed(events[-limit:]))}


@router.get(
    "/events/stream",
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def stream_admin_events() -> StreamingResponse:
    """Stream admin events using Server-Sent Events."""
    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=EVENT_LIMIT)
    with _event_lock:
        replay = list(_events)
        _subscribers.add(subscriber)

    def stream():
        try:
            for event in replay:
                yield f"id: {event['id']}\nevent: admin.event\ndata: {json.dumps(event)}\n\n"
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    yield f"id: {event['id']}\nevent: admin.event\ndata: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with _event_lock:
                _subscribers.discard(subscriber)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete(
    "/events/simulated",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def clear_simulated_events() -> None:
    """Clear in-memory preview events; no telemetry or fleet records are deleted."""
    with _event_lock:
        _events.clear()
        for subscriber in tuple(_subscribers):
            try:
                subscriber.put_nowait({
                    "id": str(uuid4()),
                    "type": "admin.events.cleared",
                    "vehicle_id": None,
                    "vehicle": "—",
                    "at": datetime.now(timezone.utc).isoformat(),
                    "detail": "Simulated preview events cleared",
                    "simulated": True,
                    "outcome": "cleared",
                })
            except queue.Full:
                pass
