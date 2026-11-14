import base64
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from auth.security import require_roles
from db import get_db
from enums import UserRole
from models import TelemetryDeadLetter, TelemetryReading, Vehicle
from schemas.common import PaginationMeta
from schemas.dead_letter import (
    TelemetryDeadLetterListResponse,
    TelemetryDeadLetterRead,
)
from schemas.latest_telemetry import (
    LatestTelemetryResponse,
    LatestTelemetrySignal,
    VehicleLatestTelemetry,
)
from telemetry.service import TelemetryRejected, ingest_telemetry


router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])

LATEST_SIGNALS = ("latitude", "longitude", "speed_kmh", "battery_soc_percent")


@router.get(
    "/latest",
    response_model=LatestTelemetryResponse,
    dependencies=[
        Depends(require_roles(UserRole.ADMIN, UserRole.OPERATOR, UserRole.VIEWER))
    ],
)
def get_latest_telemetry(db: Session = Depends(get_db)) -> LatestTelemetryResponse:
    ranked_readings = (
        select(
            TelemetryReading.vehicle_id.label("vehicle_id"),
            TelemetryReading.signal_name.label("signal_name"),
            TelemetryReading.value_numeric.label("value_numeric"),
            TelemetryReading.unit.label("unit"),
            TelemetryReading.observed_at.label("observed_at"),
            func.row_number()
            .over(
                partition_by=(
                    TelemetryReading.vehicle_id,
                    TelemetryReading.signal_name,
                ),
                order_by=(
                    TelemetryReading.observed_at.desc(),
                    TelemetryReading.id.desc(),
                ),
            )
            .label("reading_rank"),
        )
        .where(TelemetryReading.signal_name.in_(LATEST_SIGNALS))
        .subquery()
    )
    rows = db.execute(
        select(
            Vehicle.id,
            ranked_readings.c.signal_name,
            ranked_readings.c.value_numeric,
            ranked_readings.c.unit,
            ranked_readings.c.observed_at,
        )
        .outerjoin(
            ranked_readings,
            and_(
                ranked_readings.c.vehicle_id == Vehicle.id,
                ranked_readings.c.reading_rank == 1,
            ),
        )
        .order_by(Vehicle.id)
    ).all()

    items: dict[UUID, dict[str, LatestTelemetrySignal | None]] = {}
    for row in rows:
        signals = items.setdefault(
            row.id,
            {signal_name: None for signal_name in LATEST_SIGNALS},
        )
        if row.signal_name is not None:
            signals[row.signal_name] = LatestTelemetrySignal(
                value=row.value_numeric,
                unit=row.unit,
                observed_at=row.observed_at,
            )

    return LatestTelemetryResponse(
        items=[
            VehicleLatestTelemetry(vehicle_id=vehicle_id, **signals)
            for vehicle_id, signals in items.items()
        ]
    )


@router.get(
    "/dead-letters",
    response_model=TelemetryDeadLetterListResponse,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def list_telemetry_dead_letters(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TelemetryDeadLetterListResponse:
    query = select(TelemetryDeadLetter)
    total_items = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = db.scalars(
        query.order_by(
            TelemetryDeadLetter.last_seen_at.desc(),
            TelemetryDeadLetter.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return TelemetryDeadLetterListResponse(
        items=[
            TelemetryDeadLetterRead(
                id=record.id,
                message_hash=record.message_hash,
                topic=record.topic,
                payload_base64=base64.b64encode(record.payload).decode("ascii"),
                error_type=record.error_type,
                reason=record.reason,
                attempts=record.attempts,
                first_seen_at=record.first_seen_at,
                last_seen_at=record.last_seen_at,
            )
            for record in records
        ],
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=ceil(total_items / page_size) if total_items else 0,
        ),
    )


@router.post(
    "/dead-letters/{dead_letter_id}/replay",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def replay_telemetry_dead_letter(
    dead_letter_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    dead_letter = db.get(TelemetryDeadLetter, dead_letter_id)
    if dead_letter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead-letter message not found",
        )
    try:
        inserted = ingest_telemetry(db, dead_letter.topic, dead_letter.payload)
    except TelemetryRejected as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dead-letter message is still rejected: {error}",
        ) from error
    db.delete(dead_letter)
    db.commit()
    return {"inserted_signals": inserted}


@router.delete(
    "/dead-letters/{dead_letter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def delete_telemetry_dead_letter(
    dead_letter_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    dead_letter = db.get(TelemetryDeadLetter, dead_letter_id)
    if dead_letter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dead-letter message not found",
        )
    db.delete(dead_letter)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
