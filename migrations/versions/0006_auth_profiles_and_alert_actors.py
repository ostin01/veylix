"""Add local accounts, diagnostic profiles, and alert acknowledgement actors.

Revision ID: 0006_auth_profiles
Revises: 0005_alerts_telemetry_dlq
"""
from datetime import datetime, timezone
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "0006_auth_profiles"
down_revision: str | None = "0005_alerts_telemetry_dlq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_THRESHOLDS = {
    "motor_temperature_c": {"warning_max": 100, "critical_max": 125},
    "battery_soc_percent": {"warning_min": 20, "critical_min": 10},
    "tire_pressure_psi": {
        "warning_min": 28,
        "critical_min": 25,
        "warning_max": 42,
        "critical_max": 48,
    },
    "speed_kmh": {"warning_max": 160, "critical_max": 200},
    "rpm": {"warning_max": 8000, "critical_max": 12000},
}

BATTERY_THRESHOLDS = {
    "electric": (
        "high-voltage",
        {"warning_min": 300, "critical_min": 280, "warning_max": 450, "critical_max": 500},
    ),
    "hybrid": (
        "high-voltage",
        {"warning_min": 300, "critical_min": 280, "warning_max": 450, "critical_max": 500},
    ),
    "petrol": (
        "12v-low-voltage",
        {"warning_min": 12.2, "critical_min": 11.5, "warning_max": 15, "critical_max": 16},
    ),
    "diesel": (
        "12v-low-voltage",
        {"warning_min": 12.2, "critical_min": 11.5, "warning_max": 15, "critical_max": 16},
    ),
}


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "operator",
                "viewer",
                name="user_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "diagnostic_profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "vehicle_type",
            sa.Enum(
                "electric",
                "hybrid",
                "petrol",
                "diesel",
                name="profile_vehicle_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("battery_configuration", sa.String(length=100), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "uq_diagnostic_profiles_default_type",
        "diagnostic_profiles",
        ["vehicle_type"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )

    profile_rows = []
    profile_ids = {}
    for vehicle_type, (battery_configuration, battery_thresholds) in (
        BATTERY_THRESHOLDS.items()
    ):
        profile_id = uuid5(NAMESPACE_URL, f"veylix:diagnostic-profile:{vehicle_type}")
        profile_ids[vehicle_type] = profile_id
        profile_rows.append(
            {
                "id": profile_id,
                "name": f"{vehicle_type.title()} default",
                "vehicle_type": vehicle_type,
                "battery_configuration": battery_configuration,
                "thresholds": {
                    **DEFAULT_THRESHOLDS,
                    "battery_voltage_v": battery_thresholds,
                },
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    op.bulk_insert(
        sa.table(
            "diagnostic_profiles",
            sa.column("id", sa.Uuid(as_uuid=True)),
            sa.column("name", sa.String()),
            sa.column("vehicle_type", sa.String()),
            sa.column("battery_configuration", sa.String()),
            sa.column("thresholds", sa.JSON()),
            sa.column("is_default", sa.Boolean()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        profile_rows,
    )

    with op.batch_alter_table("vehicles") as batch_op:
        batch_op.add_column(
            sa.Column(
                "diagnostic_profile_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey(
                    "diagnostic_profiles.id",
                    name="fk_vehicles_diagnostic_profile_id",
                    ondelete="RESTRICT",
                ),
                nullable=True,
            )
        )
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "uq_vehicles_registration_number_lower",
            "vehicles",
            [sa.text("lower(registration_number)")],
            unique=True,
        )
    vehicles = sa.table(
        "vehicles",
        sa.column("vehicle_type", sa.String()),
        sa.column("diagnostic_profile_id", sa.Uuid(as_uuid=True)),
    )
    connection = op.get_bind()
    for vehicle_type, profile_id in profile_ids.items():
        connection.execute(
            sa.update(vehicles)
            .where(vehicles.c.vehicle_type == vehicle_type)
            .values(diagnostic_profile_id=profile_id)
        )

    with op.batch_alter_table("alerts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "acknowledged_by_id",
                sa.Uuid(as_uuid=True),
                sa.ForeignKey(
                    "users.id",
                    name="fk_alerts_acknowledged_by_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
    with op.batch_alter_table("telemetry_readings") as batch_op:
        batch_op.alter_column(
            "schema_version",
            existing_type=sa.Integer(),
            type_=sa.String(length=20),
            existing_nullable=False,
            postgresql_using="schema_version::text",
        )
    op.execute(
        sa.text(
            "UPDATE telemetry_readings "
            "SET schema_version = '1.0' WHERE schema_version = '1'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE telemetry_readings "
            "SET schema_version = '1' WHERE schema_version = '1.0'"
        )
    )
    with op.batch_alter_table("telemetry_readings") as batch_op:
        batch_op.alter_column(
            "schema_version",
            existing_type=sa.String(length=20),
            type_=sa.Integer(),
            existing_nullable=False,
            postgresql_using="schema_version::integer",
        )
    op.drop_column("alerts", "acknowledged_by_id")
    op.drop_column("vehicles", "diagnostic_profile_id")
    op.drop_index(
        "uq_diagnostic_profiles_default_type",
        table_name="diagnostic_profiles",
    )
    op.drop_table("diagnostic_profiles")
    op.drop_table("users")
