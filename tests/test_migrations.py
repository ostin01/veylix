from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, select
from sqlalchemy.orm import Session

from models import DeviceAssignment, Vehicle


def test_assignment_migration_backfills_current_device_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "migration.sqlite3"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.upgrade(config, "0002_devices")

    engine = create_engine(database_url)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    fleets = metadata.tables["fleets"]
    vehicles = metadata.tables["vehicles"]
    devices = metadata.tables["devices"]
    now = datetime.now(timezone.utc)
    fleet_id = uuid4()
    vehicle_id = uuid4()
    device_id = uuid4()
    with Session(engine) as session:
        session.execute(
            fleets.insert().values(
                id=fleet_id.hex,
                name="Migration test",
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            vehicles.insert().values(
                id=vehicle_id.hex,
                fleet_id=fleet_id.hex,
                make="Test",
                model="Van",
                year=2025,
                vehicle_type="hybrid",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            devices.insert().values(
                id=device_id.hex,
                serial_number="MIGRATION-DEVICE",
                vehicle_id=vehicle_id.hex,
                device_type="telematics",
                connection_status="unknown",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    command.upgrade(config, "head")

    assert {
        "alerts",
        "telemetry_dead_letters",
        "users",
        "diagnostic_profiles",
    }.issubset(
        set(inspect(engine).get_table_names())
    )
    with engine.connect() as connection:
        vehicle_indexes = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'vehicles'"
        ).scalars().all()
    assert "uq_vehicles_registration_number_lower" in vehicle_indexes

    with Session(engine) as session:
        assignment = session.scalar(
            select(DeviceAssignment).where(DeviceAssignment.device_id == device_id)
        )
        assert assignment is not None
        assert assignment.vehicle_id == vehicle_id
        assert assignment.unassigned_at is None
        migrated_vehicle = session.get(Vehicle, vehicle_id)
        assert migrated_vehicle is not None
        assert migrated_vehicle.diagnostic_profile_id is not None

    engine.dispose()
