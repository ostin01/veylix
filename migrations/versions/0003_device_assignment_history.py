"""Track device assignment history.

Revision ID: 0003_device_assignment_history
Revises: 0002_devices
"""
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID, uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "0003_device_assignment_history"
down_revision: str | None = "0002_devices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_assignments",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_device_assignments_vehicle_id",
        "device_assignments",
        ["vehicle_id"],
        unique=False,
    )
    op.create_index(
        "uq_device_assignments_active_device",
        "device_assignments",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("unassigned_at IS NULL"),
        sqlite_where=sa.text("unassigned_at IS NULL"),
    )

    connection = op.get_bind()
    existing_assignments = connection.execute(
        sa.text("SELECT id, vehicle_id FROM devices WHERE vehicle_id IS NOT NULL")
    ).all()
    now = datetime.now(timezone.utc)
    if existing_assignments:
        assignments_table = sa.table(
            "device_assignments",
            sa.column("id", sa.Uuid(as_uuid=True)),
            sa.column("device_id", sa.Uuid(as_uuid=True)),
            sa.column("vehicle_id", sa.Uuid(as_uuid=True)),
            sa.column("assigned_at", sa.DateTime(timezone=True)),
            sa.column("unassigned_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(
            assignments_table,
            [
                {
                    "id": uuid4(),
                    "device_id": UUID(str(row.id)),
                    "vehicle_id": UUID(str(row.vehicle_id)),
                    "assigned_at": now,
                    "unassigned_at": None,
                }
                for row in existing_assignments
            ],
        )


def downgrade() -> None:
    op.drop_index("uq_device_assignments_active_device", table_name="device_assignments")
    op.drop_index("ix_device_assignments_vehicle_id", table_name="device_assignments")
    op.drop_table("device_assignments")
