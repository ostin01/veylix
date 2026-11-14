from sqlalchemy import select
from sqlalchemy.orm import Session

from enums import VehicleType
from models import DiagnosticProfile


_COMMON_THRESHOLDS = {
    "motor_temperature_c": {"warning_max": 100, "critical_max": 125},
    "battery_soc_percent": {"warning_min": 20, "critical_min": 10},
    "tire_pressure_psi": {
        "warning_min": 28,
        "critical_min": 25,
        "warning_max": 42,
        "critical_max": 48,
    },
    "speed_kmh": {"warning_max": 160, "critical_max": 200},
    "rpm": {"warning_max": 8000, "critical_max": 12000},
}

_BATTERY_DEFAULTS = {
    VehicleType.ELECTRIC: (
        "high-voltage",
        {"warning_min": 300, "critical_min": 280, "warning_max": 450, "critical_max": 500},
    ),
    VehicleType.HYBRID: (
        "high-voltage",
        {"warning_min": 300, "critical_min": 280, "warning_max": 450, "critical_max": 500},
    ),
    VehicleType.PETROL: (
        "12v-low-voltage",
        {"warning_min": 12.2, "critical_min": 11.5, "warning_max": 15, "critical_max": 16},
    ),
    VehicleType.DIESEL: (
        "12v-low-voltage",
        {"warning_min": 12.2, "critical_min": 11.5, "warning_max": 15, "critical_max": 16},
    ),
}


def seed_default_profiles(db: Session) -> None:
    for vehicle_type, (battery_configuration, battery_thresholds) in (
        _BATTERY_DEFAULTS.items()
    ):
        existing = db.scalar(
            select(DiagnosticProfile.id).where(
                DiagnosticProfile.vehicle_type == vehicle_type,
                DiagnosticProfile.is_default.is_(True),
            )
        )
        if existing is not None:
            continue
        db.add(
            DiagnosticProfile(
                name=f"{vehicle_type.value.title()} default",
                vehicle_type=vehicle_type,
                battery_configuration=battery_configuration,
                thresholds={
                    **_COMMON_THRESHOLDS,
                    "battery_voltage_v": battery_thresholds,
                },
                is_default=True,
            )
        )
    db.commit()
