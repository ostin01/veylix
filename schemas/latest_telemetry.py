from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LatestTelemetrySignal(BaseModel):
    value: float | None
    unit: str
    observed_at: datetime


class VehicleLatestTelemetry(BaseModel):
    vehicle_id: UUID
    latitude: LatestTelemetrySignal | None
    longitude: LatestTelemetrySignal | None
    speed_kmh: LatestTelemetrySignal | None
    battery_soc_percent: LatestTelemetrySignal | None


class LatestTelemetryResponse(BaseModel):
    items: list[VehicleLatestTelemetry]
