"""Admin-only diagnostics, simulations, and operational summaries."""
import json
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth.principal import Principal
from auth.security import require_roles
from db import get_db
from enums import DeviceConnectionStatus, UserRole, VehicleType
from events import publish_event
from models import Alert, Device, DeviceAssignment, Fleet, TelemetryReading, Vehicle
from telemetry.connectivity import mark_stale_devices_offline
from telemetry.protocol import telemetry_topic
from telemetry.service import TelemetryRejected, ingest_telemetry

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
Scenario = Literal[
    "vehicle_moves", "battery_drops", "overspeed", "device_offline",
    "device_reconnects", "engine_fault",
]
SCENARIO_DETAILS = {
    "vehicle_moves": ("vehicle.location.updated", "Simulated vehicle location update"),
    "battery_drops": ("alert.created", "Simulated low battery alert"),
    "overspeed": ("alert.created", "Simulated overspeed alert"),
    "device_offline": ("device.disconnected", "Simulated device offline transition"),
    "device_reconnects": ("device.connected", "Simulated device reconnect"),
    "engine_fault": ("alert.created", "Simulated engine temperature alert"),
}
EVENT_LIMIT = 100
_events: deque[dict[str, object]] = deque(maxlen=EVENT_LIMIT)
_event_lock = threading.Lock()


class SimulationRequest(BaseModel):
    vehicle_id: UUID
    scenario: Scenario


@router.get("/system", dependencies=[Depends(require_roles(UserRole.ADMIN))])
def get_admin_system(db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        db.execute(text("SELECT 1"))
        counts = {
            "fleets": db.scalar(select(func.count()).select_from(Fleet)) or 0,
            "vehicles": db.scalar(select(func.count()).select_from(Vehicle)) or 0,
            "devices": db.scalar(select(func.count()).select_from(Device)) or 0,
            "active_alerts": db.scalar(select(func.count()).select_from(Alert).where(Alert.resolved_at.is_(None))) or 0,
            "telemetry_readings": db.scalar(select(func.count()).select_from(TelemetryReading)) or 0,
        }
        database_status = "healthy"
    except SQLAlchemyError:
        db.rollback()
        counts = None
        database_status = "unavailable"
    return {"api": "healthy", "database": database_status, "counts": counts}


@router.post("/simulations", status_code=status.HTTP_202_ACCEPTED)
def create_simulation(
    payload: SimulationRequest,
    principal: Principal = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Run a marked sample through the same telemetry and alert processing logic."""
    vehicle = db.get(Vehicle, payload.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    assignment = db.execute(
        select(Device, DeviceAssignment)
        .join(DeviceAssignment, DeviceAssignment.device_id == Device.id)
        .where(
            DeviceAssignment.vehicle_id == vehicle.id,
            DeviceAssignment.unassigned_at.is_(None),
            Device.vehicle_id == vehicle.id,
        )
        .order_by(DeviceAssignment.assigned_at.desc())
        .limit(1)
    ).first()
    if assignment is None:
        raise HTTPException(status_code=409, detail="Assign an active device to this vehicle before running a simulation")
    device = assignment[0]
    now = datetime.now(timezone.utc)
    vehicle_label = vehicle.name or vehicle.registration_number or f"{vehicle.year} {vehicle.make} {vehicle.model}"

    if payload.scenario == "device_offline":
        if device.connection_status != DeviceConnectionStatus.ONLINE or device.last_seen_at is None:
            raise HTTPException(status_code=409, detail="Run Device reconnects first so this device has a recent online baseline")
        # Only age the selected device and let the normal connectivity processor handle it.
        device.last_seen_at = now - timedelta(seconds=2)
        db.flush()
        mark_stale_devices_offline(db, now, 1, simulated=True, device_ids={device.id})
        outcome = "device_marked_offline"
        alert = db.scalar(select(Alert).where(
            Alert.vehicle_id == vehicle.id,
            Alert.is_simulated.is_(True),
            Alert.resolved_at.is_(None),
            Alert.code == "device_offline",
        ))
    else:
        latest_rows = db.execute(
            select(TelemetryReading.signal_name, TelemetryReading.value_numeric)
            .where(
                TelemetryReading.vehicle_id == vehicle.id,
                TelemetryReading.signal_name.in_(("latitude", "longitude", "odometer_km")),
            )
            .order_by(TelemetryReading.observed_at.desc(), TelemetryReading.id.desc())
        ).all()
        latest: dict[str, float] = {}
        for name, value in latest_rows:
            if value is not None and name not in latest:
                latest[name] = value
        base_latitude = latest.get("latitude", 37.7749)
        base_longitude = latest.get("longitude", -122.4194)
        signals: dict[str, object] = {
            "latitude": base_latitude,
            "longitude": base_longitude,
            "speed_kmh": 0.0,
            "odometer_km": latest.get("odometer_km", 1000.0),
            "battery_soc_percent": 80.0,
            "battery_voltage_v": 400.0 if vehicle.vehicle_type in (VehicleType.ELECTRIC, VehicleType.HYBRID) else 13.8,
            "motor_temperature_c": 85.0,
            "rpm": 1500,
            "tire_pressure_psi": 35.0,
            "vehicle_state": "parked",
        }
        expected_signal: str | None = None
        if payload.scenario == "vehicle_moves":
            signals.update(latitude=min(base_latitude + 0.001, 89.999), longitude=min(base_longitude + 0.001, 179.999), speed_kmh=35.0, vehicle_state="driving")
        elif payload.scenario == "battery_drops":
            signals["battery_soc_percent"] = 5.0
            expected_signal = "battery_soc_percent"
        elif payload.scenario == "overspeed":
            signals.update(speed_kmh=220.0, vehicle_state="driving")
            expected_signal = "speed_kmh"
        elif payload.scenario == "engine_fault":
            signals["motor_temperature_c"] = 130.0
            expected_signal = "motor_temperature_c"
        elif payload.scenario == "device_reconnects":
            signals.update(speed_kmh=0.0, vehicle_state="parked")

        message = {
            "schema_version": "1.0",
            "message_id": str(uuid4()),
            "vehicle_id": str(vehicle.id),
            "device_id": str(device.id),
            "observed_at": now.isoformat(),
            "sent_at": now.isoformat(),
            "signals": signals,
        }
        try:
            inserted = ingest_telemetry(
                db,
                telemetry_topic(vehicle.fleet_id, vehicle.id),
                json.dumps(message).encode(),
                simulated=True,
            )
        except TelemetryRejected as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        alert = None
        if expected_signal:
            alert = db.scalar(
                select(Alert).where(
                    Alert.vehicle_id == vehicle.id,
                    Alert.is_simulated.is_(True),
                    Alert.resolved_at.is_(None),
                    Alert.signal_name == expected_signal,
                )
            )
        outcome = "alert_created" if alert is not None else f"telemetry_processed_{inserted}_signals"

    event_type, detail = SCENARIO_DETAILS[payload.scenario]
    event: dict[str, object] = {
        "id": str(uuid4()), "type": event_type, "vehicle_id": str(vehicle.id),
        "vehicle": vehicle_label, "scenario": payload.scenario,
        "at": now.isoformat(), "detail": detail, "simulated": True,
        "triggered_by": principal.username, "outcome": outcome,
    }
    if alert is not None:
        event["alert_id"] = str(alert.id)
    with _event_lock:
        _events.append(event)
    publish_event(
        "admin.simulation.created", fleet_id=vehicle.fleet_id, vehicle_id=vehicle.id,
        device_id=device.id,
        data={"scenario": payload.scenario, "simulated": True, "detail": detail,
              "triggered_by": principal.username, "outcome": outcome,
              "alert_id": str(alert.id) if alert is not None else None},
    )
    return event


@router.get("/events", dependencies=[Depends(require_roles(UserRole.ADMIN))])
def list_admin_events(limit: int = Query(default=30, ge=1, le=EVENT_LIMIT)) -> dict[str, list[dict[str, object]]]:
    with _event_lock:
        events = list(_events)
    return {"items": list(reversed(events[-limit:]))}


@router.delete("/events/simulated", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_roles(UserRole.ADMIN))])
def clear_simulated_events(db: Session = Depends(get_db)) -> Response:
    simulated_alerts = db.scalars(select(Alert).where(Alert.is_simulated.is_(True))).all()
    simulated_readings = db.scalars(select(TelemetryReading).where(TelemetryReading.is_simulated.is_(True))).all()
    offline_device_ids = {
        alert.device_id
        for alert in simulated_alerts
        if alert.code == "device_offline" and alert.device_id is not None
    }
    simulated_devices = db.scalars(select(Device).where(Device.id.in_(offline_device_ids))).all() if offline_device_ids else []
    vehicle_ids = {alert.vehicle_id for alert in simulated_alerts} | {reading.vehicle_id for reading in simulated_readings}
    fleet_rows = db.execute(select(Vehicle.id, Vehicle.fleet_id).where(Vehicle.id.in_(vehicle_ids))).all() if vehicle_ids else []
    fleet_by_vehicle = dict(fleet_rows)
    now = datetime.now(timezone.utc)
    for device in simulated_devices:
        device.connection_status = DeviceConnectionStatus.ONLINE
        device.last_seen_at = now
    alert_events = [(alert.id, alert.vehicle_id, alert.device_id) for alert in simulated_alerts]
    for alert in simulated_alerts:
        db.delete(alert)
    for reading in simulated_readings:
        db.delete(reading)
    db.commit()
    for alert_id, vehicle_id, device_id in alert_events:
        fleet_id = next((fleet for vehicle, fleet in fleet_rows if vehicle == vehicle_id), None)
        if fleet_id:
            publish_event("alert.resolved", fleet_id=fleet_id, vehicle_id=vehicle_id, device_id=device_id,
                          data={"alert_id": str(alert_id), "simulated": True, "cleared": True})
    for vehicle_id, fleet_id in set(fleet_rows):
        publish_event("admin.simulation.cleared", fleet_id=fleet_id, vehicle_id=vehicle_id,
                      data={"simulated": True, "cleared": True})
    with _event_lock:
        _events.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)