from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


HealthIndicatorStatus = Literal["unknown", "normal", "warning", "critical"]
VehicleHealthStatus = Literal["unknown", "healthy", "warning", "critical"]


class HealthIndicator(BaseModel):
    signal_name: str
    status: HealthIndicatorStatus
    value: float | str | None
    unit: str | None
    observed_at: datetime | None
    threshold: str | None
    message: str


class VehicleHealthResponse(BaseModel):
    vehicle_id: UUID
    status: VehicleHealthStatus
    score: int | None
    indicators: list[HealthIndicator]
