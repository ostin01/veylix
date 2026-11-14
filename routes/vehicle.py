from datetime import datetime
from math import ceil
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import get_db
from models import DeviceAssignment, Fleet, TelemetryReading, Vehicle
from schemas.common import PaginationMeta, build_pagination_meta
from schemas.health import VehicleHealthResponse
from schemas.telemetry import TelemetryReadingListResponse
from schemas.vehicle import (
    VehicleCreate,
    VehicleListResponse,
    VehicleRead,
    VehicleStatus,
    VehicleUpdate,
)
from telemetry.constants import HEALTH_SIGNAL_NAMES
from telemetry.health import build_vehicle_health


router = APIRouter(prefix="/api/v1/vehicles", tags=["vehicles"])


def _check_unique_identifiers(
    db: Session,
    payload: VehicleCreate | VehicleUpdate,
    exclude_id: UUID | None = None,
) -> None:
    data = payload.model_dump(exclude_unset=True)
    conditions = []
    if data.get("vin") is not None:
        conditions.append(Vehicle.vin == data["vin"])
    if data.get("registration_number") is not None:
        conditions.append(
            func.lower(Vehicle.registration_number)
            == data["registration_number"].lower()
        )
    if not conditions:
        return

    query = select(Vehicle.id).where(or_(*conditions))
    if exclude_id is not None:
        query = query.where(Vehicle.id != exclude_id)
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A vehicle with this VIN or registration number already exists",
        )


def _commit_vehicle(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle conflicts with an existing record or fleet",
        ) from error


@router.post("", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db)) -> Vehicle:
    if db.get(Fleet, payload.fleet_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found")
    _check_unique_identifiers(db, payload)

    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    _commit_vehicle(db)
    db.refresh(vehicle)
    return vehicle


@router.get("", response_model=VehicleListResponse)
def list_vehicles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    fleet_id: UUID | None = None,
    status_filter: VehicleStatus | None = Query(default=None, alias="status"),
    search: str | None = None,
    sort_by: Literal["created_at", "make", "model"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
) -> VehicleListResponse:
    filters = []
    if fleet_id is not None:
        filters.append(Vehicle.fleet_id == fleet_id)
    if status_filter is not None:
        filters.append(Vehicle.status == status_filter)
    if search is not None and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                Vehicle.vin.ilike(term),
                Vehicle.registration_number.ilike(term),
                Vehicle.make.ilike(term),
                Vehicle.model.ilike(term),
            )
        )

    sort_column = {
        "created_at": Vehicle.created_at,
        "make": func.lower(Vehicle.make),
        "model": func.lower(Vehicle.model),
    }[sort_by]
    sort_column = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    query = select(Vehicle).where(*filters)
    total_items = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(sort_column, Vehicle.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return VehicleListResponse(
        items=items,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=ceil(total_items / page_size) if total_items else 0,
        ),
    )


@router.get("/{vehicle_id}", response_model=VehicleRead)
def get_vehicle(vehicle_id: UUID, db: Session = Depends(get_db)) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


@router.get("/{vehicle_id}/telemetry", response_model=TelemetryReadingListResponse)
def list_vehicle_telemetry(
    vehicle_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    device_id: UUID | None = None,
    signal_name: str | None = Query(default=None, min_length=1, max_length=50),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    db: Session = Depends(get_db),
) -> TelemetryReadingListResponse:
    if db.get(Vehicle, vehicle_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if start_time is not None and (
        start_time.tzinfo is None or start_time.utcoffset() is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_time must include a timezone",
        )
    if end_time is not None and (end_time.tzinfo is None or end_time.utcoffset() is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end_time must include a timezone",
        )
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_time must be earlier than or equal to end_time",
        )

    filters = [TelemetryReading.vehicle_id == vehicle_id]
    if device_id is not None:
        filters.append(TelemetryReading.device_id == device_id)
    if signal_name is not None:
        filters.append(TelemetryReading.signal_name == signal_name)
    if start_time is not None:
        filters.append(TelemetryReading.observed_at >= start_time)
    if end_time is not None:
        filters.append(TelemetryReading.observed_at <= end_time)

    query = select(TelemetryReading).where(*filters)
    total_items = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(
            TelemetryReading.observed_at.desc(),
            TelemetryReading.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return TelemetryReadingListResponse(
        items=items,
        pagination=build_pagination_meta(total_items, page, page_size),
    )


@router.get("/{vehicle_id}/health", response_model=VehicleHealthResponse)
def get_vehicle_health(
    vehicle_id: UUID,
    db: Session = Depends(get_db),
) -> VehicleHealthResponse:
    if db.get(Vehicle, vehicle_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    latest_readings = (
        select(
            TelemetryReading.signal_name.label("signal_name"),
            TelemetryReading.value_numeric.label("value_numeric"),
            TelemetryReading.value_text.label("value_text"),
            TelemetryReading.unit.label("unit"),
            TelemetryReading.observed_at.label("observed_at"),
            func.row_number()
            .over(
                partition_by=TelemetryReading.signal_name,
                order_by=(
                    TelemetryReading.observed_at.desc(),
                    TelemetryReading.id.desc(),
                ),
            )
            .label("reading_rank"),
        )
        .where(
            TelemetryReading.vehicle_id == vehicle_id,
            TelemetryReading.signal_name.in_(HEALTH_SIGNAL_NAMES),
        )
        .subquery()
    )
    rows = db.execute(
        select(
            latest_readings.c.signal_name,
            latest_readings.c.value_numeric,
            latest_readings.c.value_text,
            latest_readings.c.unit,
            latest_readings.c.observed_at,
        ).where(latest_readings.c.reading_rank == 1)
    ).all()
    latest_signals: dict[str, tuple[float | str, str, datetime]] = {}
    for row in rows:
        value = row.value_numeric if row.value_numeric is not None else row.value_text
        if value is not None:
            latest_signals[row.signal_name] = (value, row.unit, row.observed_at)
    return build_vehicle_health(vehicle_id, latest_signals)


@router.patch("/{vehicle_id}", response_model=VehicleRead)
def update_vehicle(
    vehicle_id: UUID,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    changes = payload.model_dump(exclude_unset=True)
    fleet_id = changes.get("fleet_id")
    if fleet_id is not None and db.get(Fleet, fleet_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found")
    _check_unique_identifiers(db, payload, exclude_id=vehicle_id)

    for field, value in changes.items():
        setattr(vehicle, field, value)
    _commit_vehicle(db)
    db.refresh(vehicle)
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(vehicle_id: UUID, db: Session = Depends(get_db)) -> Response:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if db.scalar(
        select(DeviceAssignment.id)
        .where(DeviceAssignment.vehicle_id == vehicle_id)
        .limit(1)
    ) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle cannot be deleted because it has device assignment history",
        )
    if db.scalar(
        select(TelemetryReading.id)
        .where(TelemetryReading.vehicle_id == vehicle_id)
        .limit(1)
    ) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle cannot be deleted because it has telemetry history",
        )
    db.delete(vehicle)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
