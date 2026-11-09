from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import get_db
from models import Fleet, Vehicle
from schemas.common import PaginationMeta
from schemas.fleet import FleetCreate, FleetListResponse, FleetRead, FleetUpdate


router = APIRouter(prefix="/api/v1/fleets", tags=["fleets"])


@router.post("", response_model=FleetRead, status_code=status.HTTP_201_CREATED)
def create_fleet(payload: FleetCreate, db: Session = Depends(get_db)) -> Fleet:
    fleet = Fleet(**payload.model_dump())
    db.add(fleet)
    db.commit()
    db.refresh(fleet)
    return fleet


@router.get("", response_model=FleetListResponse)
def list_fleets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FleetListResponse:
    total_items = db.scalar(select(func.count()).select_from(Fleet)) or 0
    items = db.scalars(
        select(Fleet)
        .order_by(Fleet.created_at.asc(), Fleet.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return FleetListResponse(
        items=items,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=ceil(total_items / page_size) if total_items else 0,
        ),
    )


@router.get("/{fleet_id}", response_model=FleetRead)
def get_fleet(fleet_id: UUID, db: Session = Depends(get_db)) -> Fleet:
    fleet = db.get(Fleet, fleet_id)
    if fleet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found")
    return fleet


@router.patch("/{fleet_id}", response_model=FleetRead)
def update_fleet(
    fleet_id: UUID,
    payload: FleetUpdate,
    db: Session = Depends(get_db),
) -> Fleet:
    fleet = db.get(Fleet, fleet_id)
    if fleet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(fleet, field, value)
    db.commit()
    db.refresh(fleet)
    return fleet


@router.delete("/{fleet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fleet(fleet_id: UUID, db: Session = Depends(get_db)) -> Response:
    fleet = db.get(Fleet, fleet_id)
    if fleet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found")
    if db.scalar(select(Vehicle.id).where(Vehicle.fleet_id == fleet_id).limit(1)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fleet cannot be deleted while it contains vehicles",
        )

    db.delete(fleet)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fleet cannot be deleted while it contains vehicles",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
