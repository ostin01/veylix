from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from enums import AlertSeverity
from schemas.common import PaginationMeta


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vehicle_id: UUID
    device_id: UUID
    code: str
    signal_name: str
    severity: AlertSeverity
    message: str
    value_numeric: float | None
    value_text: str | None
    unit: str
    threshold: str
    first_observed_at: datetime
    last_observed_at: datetime
    created_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None


class AlertListResponse(BaseModel):
    items: list[AlertRead]
    pagination: PaginationMeta
