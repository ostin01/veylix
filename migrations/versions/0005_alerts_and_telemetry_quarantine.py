"""Persist telemetry alerts and quarantined messages.

Revision ID: 0005_alerts_and_telemetry_quarantine
Revises: 0004_telemetry_readings
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_alerts_and_telemetry_quarantine"
down_revision: str | None = "0004_telemetry_readings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("signal_name", sa.String(length=50), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "warning",
                "critical",
                name="alert_severity",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("value_text", sa.String(length=50), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("threshold", sa.String(length=100), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_alerts_active_vehicle_code",
        "alerts",
        ["vehicle_id", "code"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
        sqlite_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "ix_alerts_vehicle_created_at",
        "alerts",
        ["vehicle_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_alerts_resolved_at", "alerts", ["resolved_at"], unique=False)

    op.create_table(
        "telemetry_dead_letters",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("error_type", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_hash",
            name="uq_telemetry_dead_letters_message_hash",
        ),
    )
    op.create_index(
        "ix_telemetry_dead_letters_last_seen_at",
        "telemetry_dead_letters",
        ["last_seen_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telemetry_dead_letters_last_seen_at",
        table_name="telemetry_dead_letters",
    )
    op.drop_table("telemetry_dead_letters")
    op.drop_index("ix_alerts_resolved_at", table_name="alerts")
    op.drop_index("ix_alerts_vehicle_created_at", table_name="alerts")
    op.drop_index("uq_alerts_active_vehicle_code", table_name="alerts")
    op.drop_table("alerts")
