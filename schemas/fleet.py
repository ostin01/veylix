from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import PaginationMeta


class FleetCreate(BaseModel):
    """What the client sends to create a fleet."""
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    location: str | None = None


class FleetUpdate(BaseModel):
    """What the client sends to PATCH a fleet. Everything optional."""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    location: str | None = None

    @model_validator(mode="after")
    def name_cannot_be_null(self):
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class FleetRead(BaseModel):
    """What the API returns."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    location: str | None
    created_at: datetime
    updated_at: datetime


class FleetListResponse(BaseModel):
    items: list[FleetRead]
    pagination: PaginationMeta