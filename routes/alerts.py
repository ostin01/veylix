from math import ceil
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from auth.principal import Principal
from auth.security import require_roles
from db import get_db
from enums import AlertSeverity, UserRole
from models import Alert, utc_now
from schemas.alerts import AlertListResponse, AlertRead, AlertSummary
from schemas.common import PaginationMeta


router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get(
    "",
    response_model=AlertListResponse,
    dependencies=[
        Depends(require_roles(UserRole.ADMIN, UserRole.OPERATOR, UserRole.VIEWER))
    ],
)
def list_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    vehicle_id: UUID | None = None,
    active: bool | None = None,
    severity: AlertSeverity | None = None,
    sort_by: Literal["created_at", "last_observed_at", "severity"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
) -> AlertListResponse:
    filters = []
    if vehicle_id is not None:
        filters.append(Alert.vehicle_id == vehicle_id)
    if active is not None:
        filters.append(
            Alert.resolved_at.is_(None) if active else Alert.resolved_at.is_not(None)
        )
    if severity is not None:
        filters.append(Alert.severity == severity)

    query = select(Alert).where(*filters)
    total_items = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    sort_columns = {
        "created_at": Alert.created_at,
        "last_observed_at": Alert.last_observed_at,
        "severity": case(
            (Alert.severity == AlertSeverity.CRITICAL, 2),
            else_=1,
        ),
    }
    sort_column = sort_columns[sort_by]
    sort_column = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    items = db.scalars(
        query.order_by(sort_column, Alert.id.desc())
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


@router.get(
    "/summary",
    response_model=AlertSummary,
    dependencies=[
        Depends(require_roles(UserRole.ADMIN, UserRole.OPERATOR, UserRole.VIEWER))
    ],
)
def get_alert_summary(
    vehicle_id: UUID | None = None,
    db: Session = Depends(get_db),
) -> AlertSummary:
    filters = [Alert.resolved_at.is_(None)]
    if vehicle_id is not None:
        filters.append(Alert.vehicle_id == vehicle_id)

    active_alerts = db.scalar(
        select(func.count()).select_from(Alert).where(*filters)
    ) or 0
    vehicles_with_active_alerts = db.scalar(
        select(func.count(func.distinct(Alert.vehicle_id))).where(*filters)
    ) or 0
    severity_rows = db.execute(
        select(Alert.severity, func.count())
        .where(*filters)
        .group_by(Alert.severity)
    ).all()
    active_by_severity = {
        AlertSeverity.WARNING: 0,
        AlertSeverity.CRITICAL: 0,
    }
    active_by_severity.update(
        {severity: count for severity, count in severity_rows}
    )
    return AlertSummary(
        active_alerts=active_alerts,
        vehicles_with_active_alerts=vehicles_with_active_alerts,
        active_by_severity=active_by_severity,
    )


@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
def acknowledge_alert(
    alert_id: UUID,
    principal: Principal = Depends(
        require_roles(UserRole.ADMIN, UserRole.OPERATOR)
    ),
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
        alert.acknowledged_by_id = principal.user_id
        db.commit()
        db.refresh(alert)
    return alert
