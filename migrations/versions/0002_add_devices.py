"""Add device management.

Revision ID: 0002_devices
Revises: 0001_fleets_vehicles
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_devices"
down_revision: str | None = "0001_fleets_vehicles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("serial_number", sa.String(length=100), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("device_type", sa.String(length=50), nullable=False),
        sa.Column("firmware_version", sa.String(length=50), nullable=True),
        sa.Column(
            "connection_status",
            sa.Enum(
                "unknown",
                "online",
                "offline",
                name="device_connection_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_devices_vehicle_id", "devices", ["vehicle_id"], unique=False)
    op.create_index(
        "ix_devices_connection_status",
        "devices",
        ["connection_status"],
        unique=False,
    )
    op.create_index(
        "uq_devices_serial_number_lower",
        "devices",
        [sa.text("lower(serial_number)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_devices_serial_number_lower", table_name="devices")
    op.drop_index("ix_devices_connection_status", table_name="devices")
    op.drop_index("ix_devices_vehicle_id", table_name="devices")
    op.drop_table("devices")
