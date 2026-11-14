from uuid import UUID

from sqlalchemy import select

from db import SessionLocal
from models import DiagnosticProfile, Device, DeviceAssignment, Vehicle


def _battery_voltage_range(
    thresholds: dict[str, dict[str, float]],
) -> tuple[float, float] | None:
    voltage_thresholds = thresholds.get("battery_voltage_v")
    if voltage_thresholds is None:
        return None
    voltage_min = voltage_thresholds.get("warning_min")
    voltage_max = voltage_thresholds.get("warning_max")
    if voltage_min is None or voltage_max is None:
        return None
    return voltage_min, voltage_max


def get_active_assignments() -> list[
    tuple[UUID, UUID, UUID, tuple[float, float] | None]
]:
    with SessionLocal() as db:
        rows = db.execute(
            select(
                Device.id,
                Device.vehicle_id,
                Vehicle.fleet_id,
                DiagnosticProfile.thresholds,
            )
            .join(DeviceAssignment, DeviceAssignment.device_id == Device.id)
            .join(Vehicle, Vehicle.id == Device.vehicle_id)
            .join(
                DiagnosticProfile,
                DiagnosticProfile.id == Vehicle.diagnostic_profile_id,
            )
            .where(
                Device.vehicle_id == DeviceAssignment.vehicle_id,
                DeviceAssignment.unassigned_at.is_(None),
            )
            .order_by(Device.id)
        )
        return [
            (
                device_id,
                vehicle_id,
                fleet_id,
                _battery_voltage_range(thresholds),
            )
            for device_id, vehicle_id, fleet_id, thresholds in rows
        ]
