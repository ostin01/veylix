from math import ceil
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import get_db
from enums import DeviceConnectionStatus
from models import Device, DeviceAssignment, Vehicle, utc_now
from schemas.common import PaginationMeta
from schemas.device import (
    DeviceAssign,
    DeviceAssignmentRead,
    DeviceCreate,
    DeviceListResponse,
    DeviceRead,
    DeviceUpdate,
)


router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


def _commit_device(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device conflicts with an existing serial number or vehicle",
        ) from error


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
def create_device(payload: DeviceCreate, db: Session = Depends(get_db)) -> Device:
    if payload.vehicle_id is not None and db.get(Vehicle, payload.vehicle_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if db.scalar(
        select(Device.id).where(
            func.lower(Device.serial_number) == payload.serial_number.lower()
        )
    ) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A device with this serial number already exists",
        )

    device = Device(id=uuid4(), **payload.model_dump())
    db.add(device)
    if device.vehicle_id is not None:
        db.add(
            DeviceAssignment(
                device_id=device.id,
                vehicle_id=device.vehicle_id,
            )
        )
    _commit_device(db)
    db.refresh(device)
    return device


@router.get("", response_model=DeviceListResponse)
def list_devices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    vehicle_id: UUID | None = None,
    connection_status: DeviceConnectionStatus | None = None,
    search: str | None = None,
    sort_by: Literal["created_at", "serial_number"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
) -> DeviceListResponse:
    filters = []
    if vehicle_id is not None:
        filters.append(Device.vehicle_id == vehicle_id)
    if connection_status is not None:
        filters.append(Device.connection_status == connection_status)
    if search is not None and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                Device.serial_number.ilike(term),
                Device.device_type.ilike(term),
                Device.firmware_version.ilike(term),
            )
        )

    sort_column = {
        "created_at": Device.created_at,
        "serial_number": func.lower(Device.serial_number),
    }[sort_by]
    sort_column = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    query = select(Device).where(*filters)
    total_items = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(sort_column, Device.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return DeviceListResponse(
        items=items,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=ceil(total_items / page_size) if total_items else 0,
        ),
    )


@router.get("/{device_id}", response_model=DeviceRead)
def get_device(device_id: UUID, db: Session = Depends(get_db)) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.get("/{device_id}/assignments", response_model=list[DeviceAssignmentRead])
def list_device_assignments(
    device_id: UUID,
    db: Session = Depends(get_db),
) -> list[DeviceAssignment]:
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return db.scalars(
        select(DeviceAssignment)
        .where(DeviceAssignment.device_id == device_id)
        .order_by(DeviceAssignment.assigned_at.asc(), DeviceAssignment.id.asc())
    ).all()


@router.patch("/{device_id}", response_model=DeviceRead)
def update_device(
    device_id: UUID,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    _commit_device(db)
    db.refresh(device)
    return device


@router.post("/{device_id}/assign", response_model=DeviceRead)
def assign_device(
    device_id: UUID,
    payload: DeviceAssign,
    db: Session = Depends(get_db),
) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if db.get(Vehicle, payload.vehicle_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    if device.vehicle_id == payload.vehicle_id:
        return device

    assigned_at = utc_now()
    current_assignment = db.scalar(
        select(DeviceAssignment).where(
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.unassigned_at.is_(None),
        )
    )
    if current_assignment is not None:
        current_assignment.unassigned_at = assigned_at
    device.vehicle_id = payload.vehicle_id
    db.add(
        DeviceAssignment(
            device_id=device.id,
            vehicle_id=payload.vehicle_id,
            assigned_at=assigned_at,
        )
    )
    _commit_device(db)
    db.refresh(device)
    return device


@router.delete("/{device_id}/assignment", response_model=DeviceRead)
def unassign_device(device_id: UUID, db: Session = Depends(get_db)) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if device.vehicle_id is None:
        return device

    assigned_at = utc_now()
    current_assignment = db.scalar(
        select(DeviceAssignment).where(
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.unassigned_at.is_(None),
        )
    )
    if current_assignment is not None:
        current_assignment.unassigned_at = assigned_at
    device.vehicle_id = None
    _commit_device(db)
    db.refresh(device)
    return device
