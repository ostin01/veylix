from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from enums import AlertSeverity, DeviceConnectionStatus
from events import EventType, publish_event
from models import Alert, Device, Vehicle


def _alert_event_data(alert: Alert) -> dict[str, Any]:
    return {
        "alert_id": str(alert.id),
        "code": alert.code,
        "severity": alert.severity.value,
        "message": alert.message,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "simulated": alert.is_simulated,
    }


def mark_stale_devices_offline(
    db: Session,
    checked_at: datetime,
    offline_after_seconds: int,
    *,
    simulated: bool = False,
    device_ids: set[object] | None = None,
) -> int:
    if offline_after_seconds <= 0:
        raise ValueError("offline_after_seconds must be positive")

    stale_before = checked_at - timedelta(seconds=offline_after_seconds)
    device_query = select(Device).where(
        Device.connection_status == DeviceConnectionStatus.ONLINE,
        Device.last_seen_at.is_not(None),
        Device.last_seen_at <= stale_before,
    )
    if device_ids is not None:
        device_query = device_query.where(Device.id.in_(device_ids))
    devices = db.scalars(device_query.with_for_update(skip_locked=True)).all()
    vehicle_fleets: dict[object, object] = {}
    if devices:
        vehicle_ids = {device.vehicle_id for device in devices if device.vehicle_id is not None}
        if vehicle_ids:
            vehicle_fleets = dict(
                db.execute(
                    select(Vehicle.id, Vehicle.fleet_id).where(Vehicle.id.in_(vehicle_ids))
                ).all()
            )

    changed_alerts: list[tuple[EventType, Device, Alert]] = []
    for device in devices:
        device.connection_status = DeviceConnectionStatus.OFFLINE
        if device.vehicle_id is None:
            continue
        alert = db.scalar(
            select(Alert)
            .where(
                Alert.vehicle_id == device.vehicle_id,
                Alert.code == "device_offline",
                Alert.is_simulated.is_(simulated),
                Alert.resolved_at.is_(None),
            )
            .with_for_update()
        )
        if alert is None:
            alert = Alert(
                vehicle_id=device.vehicle_id,
                device_id=device.id,
                is_simulated=simulated,
                code="device_offline",
                signal_name="connection_status",
                severity=AlertSeverity.CRITICAL,
                message="Device stopped reporting telemetry",
                value_numeric=None,
                value_text=DeviceConnectionStatus.OFFLINE.value,
                unit="status",
                threshold=f"No telemetry for more than {offline_after_seconds} seconds",
                first_observed_at=checked_at,
                last_observed_at=checked_at,
            )
            db.add(alert)
            changed_alerts.append(("alert.created", device, alert))
        else:
            alert.device_id = device.id
            alert.last_observed_at = checked_at
            alert.value_text = DeviceConnectionStatus.OFFLINE.value
            alert.threshold = (
                f"No telemetry for more than {offline_after_seconds} seconds"
            )
            changed_alerts.append(("alert.updated", device, alert))

    db.flush()
    alert_events = [
        (event_type, device, _alert_event_data(alert))
        for event_type, device, alert in changed_alerts
    ]
    db.commit()

    for device in devices:
        if device.vehicle_id is None:
            continue
        fleet_id = vehicle_fleets.get(device.vehicle_id)
        if fleet_id is None:
            continue
        payload = {
            "connection_status": DeviceConnectionStatus.OFFLINE.value,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "simulated": simulated,
        }
        publish_event(
            "device.status.updated",
            fleet_id=fleet_id,
            vehicle_id=device.vehicle_id,
            device_id=device.id,
            data=payload,
        )
        publish_event(
            "device.disconnected",
            fleet_id=fleet_id,
            vehicle_id=device.vehicle_id,
            device_id=device.id,
            data=payload,
        )

    for event_type, device, payload in alert_events:
        if device.vehicle_id is None:
            continue
        fleet_id = vehicle_fleets.get(device.vehicle_id)
        if fleet_id is not None:
            publish_event(
                event_type,
                fleet_id=fleet_id,
                vehicle_id=device.vehicle_id,
                device_id=device.id,
                data=payload,
            )
    return len(devices)
