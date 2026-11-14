from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.security import require_roles
from db import get_db
from enums import UserRole, VehicleType
from models import DiagnosticProfile, Vehicle
from schemas.common import PaginationMeta
from schemas.diagnostic_profile import (
    DiagnosticProfileCreate,
    DiagnosticProfileListResponse,
    DiagnosticProfileRead,
    DiagnosticProfileUpdate,
)


router = APIRouter(prefix="/api/v1/diagnostic-profiles", tags=["diagnostic profiles"])


@router.get(
    "",
    response_model=DiagnosticProfileListResponse,
    dependencies=[
        Depends(require_roles(UserRole.ADMIN, UserRole.OPERATOR, UserRole.VIEWER))
    ],
)
def list_diagnostic_profiles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    vehicle_type: VehicleType | None = None,
    db: Session = Depends(get_db),
) -> DiagnosticProfileListResponse:
    query = select(DiagnosticProfile)
    if vehicle_type is not None:
        query = query.where(DiagnosticProfile.vehicle_type == vehicle_type)
    total_items = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    profiles = db.scalars(
        query.order_by(DiagnosticProfile.name.asc(), DiagnosticProfile.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return DiagnosticProfileListResponse(
        items=profiles,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=ceil(total_items / page_size) if total_items else 0,
        ),
    )


@router.post(
    "",
    response_model=DiagnosticProfileRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def create_diagnostic_profile(
    payload: DiagnosticProfileCreate,
    db: Session = Depends(get_db),
) -> DiagnosticProfile:
    profile = DiagnosticProfile(
        name=payload.name,
        vehicle_type=payload.vehicle_type,
        battery_configuration=payload.battery_configuration,
        thresholds={
            name: threshold.model_dump(exclude_none=True)
            for name, threshold in payload.thresholds.items()
        },
        is_default=False,
    )
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Diagnostic profile name already exists",
        ) from error
    db.refresh(profile)
    return profile


@router.patch(
    "/{profile_id}",
    response_model=DiagnosticProfileRead,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def update_diagnostic_profile(
    profile_id: UUID,
    payload: DiagnosticProfileUpdate,
    db: Session = Depends(get_db),
) -> DiagnosticProfile:
    profile = db.get(DiagnosticProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagnostic profile not found",
        )

    changes = payload.model_dump(exclude_unset=True)
    if "thresholds" in changes:
        changes["thresholds"] = {
            name: threshold.model_dump(exclude_none=True)
            for name, threshold in payload.thresholds.items()
        }
    for field, value in changes.items():
        setattr(profile, field, value)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Diagnostic profile name already exists",
        ) from error
    db.refresh(profile)
    return profile


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def delete_diagnostic_profile(profile_id: UUID, db: Session = Depends(get_db)) -> Response:
    profile = db.get(DiagnosticProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagnostic profile not found",
        )
    if profile.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Default diagnostic profiles cannot be deleted",
        )
    if db.scalar(
        select(Vehicle.id)
        .where(Vehicle.diagnostic_profile_id == profile_id)
        .limit(1)
    ) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Diagnostic profile is assigned to one or more vehicles",
        )
    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
