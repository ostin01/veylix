from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from models import Alert, utc_now
from schemas.alerts import AlertListResponse, AlertRead
from schemas.common import PaginationMeta


router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse)
def list_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    vehicle_id: UUID | None = None,
    active: bool | None = None,
    db: Session = Depends(get_db),
) -> AlertListResponse:
    filters = []
    if vehicle_id is not None:
        filters.append(Alert.vehicle_id == vehicle_id)
    if active is not None:
        filters.append(
            Alert.resolved_at.is_(None) if active else Alert.resolved_at.is_not(None)
        )

    query = select(Alert).where(*filters)
    total_items = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(Alert.created_at.desc(), Alert.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return AlertListResponse(
        items=items,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=ceil(total_items / page_size) if total_items else 0,
        ),
    )


@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
def acknowledge_alert(
    alert_id: UUID,
    db: Session = Depends(get_db),
) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    if alert.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resolved alerts cannot be acknowledged",
        )
    if alert.acknowledged_at is None:
        alert.acknowledged_at = utc_now()
        db.commit()
        db.refresh(alert)
    return alert
