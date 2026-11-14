from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from enums import DeviceConnectionStatus
from models import Device


def mark_stale_devices_offline(
    db: Session,
    checked_at: datetime,
    offline_after_seconds: int,
) -> int:
    if offline_after_seconds <= 0:
        raise ValueError("offline_after_seconds must be positive")

    stale_before = checked_at - timedelta(seconds=offline_after_seconds)
    result = db.execute(
        update(Device)
        .where(
            Device.connection_status == DeviceConnectionStatus.ONLINE,
            Device.last_seen_at.is_not(None),
            Device.last_seen_at <= stale_before,
        )
        .values(
            connection_status=DeviceConnectionStatus.OFFLINE,
            updated_at=checked_at,
        )
    )
    db.commit()
    return result.rowcount or 0
