from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enums import VehicleStatus, VehicleType
from schemas.common import PaginationMeta


class VehicleCreate(BaseModel):
    """What the client sends to register a vehicle."""
    fleet_id: UUID
    name: str | None = Field(default=None, max_length=50)
    vin: str | None = Field(default=None, pattern=r"^[A-HJ-NPR-Z0-9]{17}$")
    registration_number: str | None = Field(default=None, max_length=20)
    make: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=50)
    year: int = Field(ge=1900, le=2100)
    vehicle_type: VehicleType
    diagnostic_profile_id: UUID | None = None
    status: VehicleStatus = VehicleStatus.ACTIVE


class VehicleUpdate(BaseModel):
    """What the client sends to PATCH a vehicle. Everything optional."""
    fleet_id: UUID | None = None
    name: str | None = Field(default=None, max_length=50)
    vin: str | None = Field(default=None, pattern=r"^[A-HJ-NPR-Z0-9]{17}$")
    registration_number: str | None = Field(default=None, max_length=20)
    make: str | None = Field(default=None, min_length=1, max_length=50)
    model: str | None = Field(default=None, min_length=1, max_length=50)
    year: int | None = Field(default=None, ge=1900, le=2100)
    vehicle_type: VehicleType | None = None
    diagnostic_profile_id: UUID | None = None
    status: VehicleStatus | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_null(self):
        for field in (
            "fleet_id",
            "make",
            "model",
            "year",
            "vehicle_type",
            "diagnostic_profile_id",
            "status",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class VehicleRead(BaseModel):
    """What the API returns."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fleet_id: UUID
    diagnostic_profile_id: UUID | None
    name: str | None
    vin: str | None
    registration_number: str | None
    make: str
    model: str
    year: int
    vehicle_type: VehicleType
    status: VehicleStatus
    created_at: datetime
    updated_at: datetime


class VehicleListResponse(BaseModel):
    items: list[VehicleRead]
    pagination: PaginationMeta