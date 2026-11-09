"""Create fleet and vehicle tables.

Revision ID: 0001_fleets_vehicles
Revises:
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_fleets_vehicles"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fleets",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("fleet_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=True),
        sa.Column("vin", sa.String(length=17), nullable=True),
        sa.Column("registration_number", sa.String(length=20), nullable=True),
        sa.Column("make", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "vehicle_type",
            sa.Enum(
                "electric",
                "hybrid",
                "petrol",
                "diesel",
                name="vehicle_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "inactive",
                "maintenance",
                name="vehicle_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fleet_id"], ["fleets.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("year >= 1900 AND year <= 2100", name="ck_vehicles_year_range"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vin"),
    )
    op.create_index(
        "uq_vehicles_registration_number_lower",
        "vehicles",
        [sa.text("lower(registration_number)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_vehicles_registration_number_lower", table_name="vehicles")
    op.drop_table("vehicles")
    op.drop_table("fleets")
