from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from enums import DeviceConnectionStatus
from models import Alert, Device, DeviceAssignment, TelemetryReading, Vehicle
from telemetry.constants import SIGNAL_UNITS
from telemetry.health import evaluate_diagnostics
from telemetry.protocol import parse_telemetry_topic
from telemetry.schemas import TelemetryMessage


class TelemetryRejected(ValueError):
    pass


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _update_vehicle_alerts(
    db: Session,
    vehicle: Vehicle,
    device: Device,
    message: TelemetryMessage,
    received_at: datetime,
) -> None:
    latest_observed_at = db.scalar(
        select(func.max(TelemetryReading.observed_at)).where(
            TelemetryReading.vehicle_id == vehicle.id
        )
    )
    if latest_observed_at is not None and _as_utc(message.observed_at) < _as_utc(
        latest_observed_at
    ):
        return

    findings = evaluate_diagnostics(message.signals.model_dump())
    findings_by_code = {finding.code: finding for finding in findings}
    active_alerts = db.scalars(
        select(Alert).where(
            Alert.vehicle_id == vehicle.id,
            Alert.resolved_at.is_(None),
        )
    ).all()
    alerts_by_code = {alert.code: alert for alert in active_alerts}

    for code, alert in alerts_by_code.items():
        if code not in findings_by_code and _as_utc(
            alert.last_observed_at
        ) <= _as_utc(message.observed_at):
            alert.resolved_at = received_at

    for code, finding in findings_by_code.items():
        alert = alerts_by_code.get(code)
        if alert is None:
            db.add(
                Alert(
                    vehicle_id=vehicle.id,
                    device_id=device.id,
                    code=finding.code,
                    signal_name=finding.signal_name,
                    severity=finding.severity,
                    message=finding.message,
                    value_numeric=finding.value_numeric,
                    value_text=finding.value_text,
                    unit=finding.unit,
                    threshold=finding.threshold,
                    first_observed_at=message.observed_at,
                    last_observed_at=message.observed_at,
                )
            )
        elif _as_utc(alert.last_observed_at) <= _as_utc(message.observed_at):
            alert.severity = finding.severity
            alert.message = finding.message
            alert.value_numeric = finding.value_numeric
            alert.value_text = finding.value_text
            alert.unit = finding.unit
            alert.threshold = finding.threshold
            alert.last_observed_at = message.observed_at


def parse_telemetry(payload: bytes) -> TelemetryMessage:
    try:
        message = TelemetryMessage.model_validate_json(payload)
        message.validate_timestamp()
    except (ValidationError, ValueError) as error:
        raise TelemetryRejected(f"invalid telemetry payload: {error}") from error
    return message


def ingest_telemetry(db: Session, topic: str, payload: bytes) -> int:
    message = parse_telemetry(payload)
    try:
        topic_vehicle_id = parse_telemetry_topic(topic)
    except ValueError as error:
        raise TelemetryRejected(str(error)) from error
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
    _update_vehicle_alerts(db, vehicle, device, message, received_at)
    device.connection_status = DeviceConnectionStatus.ONLINE
    device.last_seen_at = received_at
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise TelemetryRejected("telemetry message was already ingested") from error
    return len(readings)
