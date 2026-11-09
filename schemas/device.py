from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enums import DeviceConnectionStatus
from schemas.common import PaginationMeta


class DeviceCreate(BaseModel):
    """What the client sends to register a device."""

    serial_number: str = Field(min_length=1, max_length=100)
    device_type: str = Field(min_length=1, max_length=50)
    firmware_version: str | None = Field(default=None, max_length=50)
    vehicle_id: UUID | None = None
    connection_status: DeviceConnectionStatus = DeviceConnectionStatus.UNKNOWN
    last_seen_at: datetime | None = None


class DeviceUpdate(BaseModel):
    """What the client sends to PATCH device metadata and connection state."""

    device_type: str | None = Field(default=None, min_length=1, max_length=50)
    firmware_version: str | None = Field(default=None, max_length=50)
    connection_status: DeviceConnectionStatus | None = None
    last_seen_at: datetime | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_null(self):
        for field in ("device_type", "connection_status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DeviceAssign(BaseModel):
    vehicle_id: UUID


class DeviceRead(BaseModel):
    """What the API returns."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    serial_number: str
    vehicle_id: UUID | None
    device_type: str
    firmware_version: str | None
    connection_status: DeviceConnectionStatus
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeviceListResponse(BaseModel):
    items: list[DeviceRead]
    pagination: PaginationMeta
