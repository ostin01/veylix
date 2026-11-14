from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enums import DeviceConnectionStatus
from schemas.common import PaginationMeta


class DeviceCreate(BaseModel):
    """What the client sends to register a device."""

    model_config = ConfigDict(extra="forbid")

    serial_number: str = Field(min_length=1, max_length=100)
    device_type: str = Field(min_length=1, max_length=50)
    firmware_version: str | None = Field(default=None, max_length=50)
    vehicle_id: UUID | None = None


class DeviceUpdate(BaseModel):
    """What the client sends to PATCH device metadata."""

    model_config = ConfigDict(extra="forbid")

    device_type: str | None = Field(default=None, min_length=1, max_length=50)
    firmware_version: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def device_type_cannot_be_null(self):
        if "device_type" in self.model_fields_set and self.device_type is None:
            raise ValueError("device_type cannot be null")
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


class DeviceAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: UUID
    vehicle_id: UUID
    assigned_at: datetime
    unassigned_at: datetime | None


class DeviceListResponse(BaseModel):
    items: list[DeviceRead]
    pagination: PaginationMeta
