from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from enums import VehicleType
from schemas.common import PaginationMeta


class DiagnosticThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warning_min: float | None = Field(default=None, allow_inf_nan=False)
    critical_min: float | None = Field(default=None, allow_inf_nan=False)
    warning_max: float | None = Field(default=None, allow_inf_nan=False)
    critical_max: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_order(self) -> "DiagnosticThreshold":
        if (self.warning_min is None) != (self.critical_min is None):
            raise ValueError("warning_min and critical_min must be set together")
        if (self.warning_max is None) != (self.critical_max is None):
            raise ValueError("warning_max and critical_max must be set together")
        if self.warning_min is None and self.warning_max is None:
            raise ValueError("at least one warning/critical threshold pair is required")
        if (
            self.warning_min is not None
            and self.critical_min is not None
            and self.critical_min >= self.warning_min
        ):
            raise ValueError("critical_min must be lower than warning_min")
        if (
            self.warning_max is not None
            and self.critical_max is not None
            and self.critical_max <= self.warning_max
        ):
            raise ValueError("critical_max must be greater than warning_max")
        if (
            self.critical_min is not None
            and self.warning_max is not None
            and self.critical_min >= self.warning_max
        ):
            raise ValueError("minimum and maximum threshold ranges overlap")
        return self


ProfileName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
BatteryConfiguration = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class DiagnosticProfileCreate(BaseModel):
    name: ProfileName
    vehicle_type: VehicleType
    battery_configuration: BatteryConfiguration
    thresholds: dict[str, DiagnosticThreshold]

    @model_validator(mode="after")
    def validate_threshold_signals(self) -> "DiagnosticProfileCreate":
        allowed_signals = {
            "motor_temperature_c",
            "battery_soc_percent",
            "battery_voltage_v",
            "tire_pressure_psi",
            "speed_kmh",
            "rpm",
        }
        if not self.thresholds:
            raise ValueError("at least one diagnostic threshold is required")
        if self.thresholds.keys() - allowed_signals:
            raise ValueError("thresholds contain an unsupported signal")
        return self


class DiagnosticProfileUpdate(BaseModel):
    name: ProfileName | None = None
    battery_configuration: BatteryConfiguration | None = None
    thresholds: dict[str, DiagnosticThreshold] | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> "DiagnosticProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one profile field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        if "battery_configuration" in self.model_fields_set:
            if self.battery_configuration is None:
                raise ValueError("battery_configuration cannot be null")
        if "thresholds" in self.model_fields_set:
            if not self.thresholds:
                raise ValueError("at least one diagnostic threshold is required")
            allowed_signals = {
                "motor_temperature_c",
                "battery_soc_percent",
                "battery_voltage_v",
                "tire_pressure_psi",
                "speed_kmh",
                "rpm",
            }
            if self.thresholds.keys() - allowed_signals:
                raise ValueError("thresholds contain an unsupported signal")
        return self


class DiagnosticProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    vehicle_type: VehicleType
    battery_configuration: str
    thresholds: dict[str, DiagnosticThreshold]
    is_default: bool
    created_at: datetime
    updated_at: datetime


class DiagnosticProfileListResponse(BaseModel):
    items: list[DiagnosticProfileRead]
    pagination: PaginationMeta
