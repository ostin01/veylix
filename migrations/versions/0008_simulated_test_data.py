"""Mark test simulations and isolate their active alerts."""
from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008_simulated_test_data"
down_revision: str | None = "0007_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("telemetry_readings") as batch:
        batch.add_column(sa.Column("is_simulated", sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table("alerts") as batch:
        batch.add_column(sa.Column("is_simulated", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.drop_index("uq_alerts_active_vehicle_code", table_name="alerts")
    op.create_index(
        "uq_alerts_active_vehicle_code",
        "alerts",
        ["vehicle_id", "code", "is_simulated"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
        sqlite_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_active_vehicle_code", table_name="alerts")
    op.create_index(
        "uq_alerts_active_vehicle_code",
        "alerts",
        ["vehicle_id", "code"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
        sqlite_where=sa.text("resolved_at IS NULL"),
    )
    with op.batch_alter_table("alerts") as batch:
        batch.drop_column("is_simulated")
    with op.batch_alter_table("telemetry_readings") as batch:
        batch.drop_column("is_simulated")