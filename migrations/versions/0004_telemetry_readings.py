"""Store validated vehicle telemetry.

Revision ID: 0004_telemetry_readings
Revises: 0003_device_assignment_history
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_telemetry_readings"
down_revision: str | None = "0003_device_assignment_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telemetry_readings",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("signal_name", sa.String(length=50), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("value_text", sa.String(length=50), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "signal_name", name="uq_telemetry_message_signal"),
    )
    op.create_index(
        "ix_telemetry_vehicle_observed_at",
        "telemetry_readings",
        ["vehicle_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_signal_observed_at",
        "telemetry_readings",
        ["signal_name", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_signal_observed_at", table_name="telemetry_readings")
    op.drop_index("ix_telemetry_vehicle_observed_at", table_name="telemetry_readings")
    op.drop_table("telemetry_readings")
