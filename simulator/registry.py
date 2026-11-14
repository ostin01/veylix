from uuid import UUID

from sqlalchemy import select

from db import SessionLocal
from models import Device, DeviceAssignment


def get_active_assignments() -> list[tuple[UUID, UUID]]:
    with SessionLocal() as db:
        rows = db.execute(
            select(Device.id, Device.vehicle_id)
            .join(DeviceAssignment, DeviceAssignment.device_id == Device.id)
            .where(
                Device.vehicle_id == DeviceAssignment.vehicle_id,
                DeviceAssignment.unassigned_at.is_(None),
            )
            .order_by(Device.id)
        )
        return [(device_id, vehicle_id) for device_id, vehicle_id in rows]
