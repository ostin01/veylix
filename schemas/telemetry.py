from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from schemas.common import PaginationMeta


class TelemetryReadingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vehicle_id: UUID
    device_id: UUID
    signal_name: str
    value_numeric: float | None
    value_text: str | None
    unit: str
    observed_at: datetime
    received_at: datetime
    schema_version: int
    message_id: UUID


class TelemetryReadingListResponse(BaseModel):
    items: list[TelemetryReadingRead]
    pagination: PaginationMeta
