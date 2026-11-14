from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TelemetrySignals(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    speed_kmh: Annotated[float, Field(ge=0, le=500)]
    odometer_km: Annotated[float, Field(ge=0)]
    battery_soc_percent: Annotated[float, Field(ge=0, le=100)]
    battery_voltage_v: Annotated[float, Field(ge=0, le=1000)]
    motor_temperature_c: Annotated[float, Field(ge=-50, le=300)]
    rpm: Annotated[int, Field(ge=0, le=30000)]
    tire_pressure_psi: Annotated[float, Field(ge=0, le=200)]
    vehicle_state: Literal["parked", "driving", "charging", "offline"]


class TelemetryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    message_id: UUID
    vehicle_id: UUID
    device_id: UUID
    observed_at: datetime
    signals: TelemetrySignals

    def validate_timestamp(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
