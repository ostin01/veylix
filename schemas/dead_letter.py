from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from schemas.common import PaginationMeta


class TelemetryDeadLetterRead(BaseModel):
    id: UUID
    message_hash: str
    topic: str
    payload_base64: str
    error_type: str
    reason: str
    attempts: int
    first_seen_at: datetime
    last_seen_at: datetime


class TelemetryDeadLetterListResponse(BaseModel):
    items: list[TelemetryDeadLetterRead]
    pagination: PaginationMeta
