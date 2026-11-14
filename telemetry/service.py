import json
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from enums import DeviceConnectionStatus
from models import Device, DeviceAssignment, TelemetryReading, Vehicle
from telemetry.schemas import TelemetryMessage


SIGNAL_UNITS = {
    "latitude": "degrees",
    "longitude": "degrees",
    "speed_kmh": "km/h",
    "odometer_km": "km",
    "battery_soc_percent": "%",
    "battery_voltage_v": "V",
    "motor_temperature_c": "degC",
    "rpm": "rpm",
    "tire_pressure_psi": "psi",
    "vehicle_state": "enum",
}


class TelemetryRejected(ValueError):
    pass


def parse_telemetry(payload: bytes) -> TelemetryMessage:
    try:
        message = TelemetryMessage.model_validate_json(payload)
        message.validate_timestamp()
    except (ValidationError, ValueError) as error:
        raise TelemetryRejected(f"invalid telemetry payload: {error}") from error
    return message


def ingest_telemetry(db: Session, topic: str, payload: bytes) -> int:
    message = parse_telemetry(payload)
    topic_parts = topic.split("/")
    if (
        len(topic_parts) != 5
        or topic_parts[:3] != ["veylix", "v1", "vehicles"]
        or topic_parts[4] != "telemetry"
    ):
        raise TelemetryRejected("unexpected telemetry topic")
    try:
        topic_vehicle_id = UUID(topic_parts[3])
    except ValueError as error:
        raise TelemetryRejected("topic contains an invalid vehicle ID") from error
    if topic_vehicle_id != message.vehicle_id:
        raise TelemetryRejected("topic vehicle ID does not match payload")

    vehicle = db.get(Vehicle, message.vehicle_id)
    if vehicle is None:
        raise TelemetryRejected("vehicle is not registered")
    device = db.get(Device, message.device_id)
    if device is None:
        raise TelemetryRejected("device is not registered")
    if device.vehicle_id != vehicle.id:
        raise TelemetryRejected("device is not currently assigned to this vehicle")
    active_assignment = db.scalar(
        select(DeviceAssignment.id).where(
            DeviceAssignment.device_id == device.id,
            DeviceAssignment.vehicle_id == vehicle.id,
            DeviceAssignment.unassigned_at.is_(None),
        )
    )
    if active_assignment is None:
        raise TelemetryRejected("device assignment is not active")

    existing_message = db.execute(
        select(TelemetryReading.vehicle_id, TelemetryReading.device_id)
        .where(TelemetryReading.message_id == message.message_id)
        .limit(1)
    ).first()
    if existing_message is not None:
        if existing_message.vehicle_id != vehicle.id or existing_message.device_id != device.id:
            raise TelemetryRejected("message ID was already used by another vehicle or device")
        return 0

    received_at = datetime.now(timezone.utc)
    readings = []
    for signal_name, value in message.signals.model_dump().items():
        is_text_value = isinstance(value, str)
        readings.append(
            TelemetryReading(
                vehicle_id=vehicle.id,
                device_id=device.id,
                signal_name=signal_name,
                value_numeric=None if is_text_value else value,
                value_text=value if is_text_value else None,
                unit=SIGNAL_UNITS[signal_name],
                observed_at=message.observed_at,
                received_at=received_at,
                schema_version=message.schema_version,
                message_id=message.message_id,
            )
        )

    db.add_all(readings)
    device.connection_status = DeviceConnectionStatus.ONLINE
    device.last_seen_at = received_at
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise TelemetryRejected("telemetry message was already ingested") from error
    return len(readings)
