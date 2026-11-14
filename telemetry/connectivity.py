from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from enums import AlertSeverity, DeviceConnectionStatus
from models import Alert, Device


def mark_stale_devices_offline(
    db: Session,
    checked_at: datetime,
    offline_after_seconds: int,
) -> int:
    if offline_after_seconds <= 0:
        raise ValueError("offline_after_seconds must be positive")

    stale_before = checked_at - timedelta(seconds=offline_after_seconds)
    stale_devices = db.scalars(
        select(Device)
        .where(
            Device.connection_status == DeviceConnectionStatus.ONLINE,
            Device.last_seen_at.is_not(None),
            Device.last_seen_at <= stale_before,
        )
        .with_for_update(skip_locked=True)
    )
    devices = stale_devices.all()
    for device in devices:
        device.connection_status = DeviceConnectionStatus.OFFLINE
        if device.vehicle_id is None:
            continue
        alert = db.scalar(
            select(Alert)
            .where(
                Alert.vehicle_id == device.vehicle_id,
                Alert.code == "device_offline",
                Alert.resolved_at.is_(None),
            )
            .with_for_update()
        )
        if alert is None:
            db.add(
                Alert(
                    vehicle_id=device.vehicle_id,
                    device_id=device.id,
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
            )
        else:
            alert.device_id = device.id
            alert.last_observed_at = checked_at
            alert.value_text = DeviceConnectionStatus.OFFLINE.value
            alert.threshold = (
                f"No telemetry for more than {offline_after_seconds} seconds"
            )
    db.commit()
    return len(devices)
