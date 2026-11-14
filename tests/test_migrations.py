from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from enums import VehicleType
from models import Device, DeviceAssignment, Fleet, Vehicle


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
    with Session(engine) as session:
        fleet = Fleet(name="Migration test")
        session.add(fleet)
        session.flush()
        vehicle = Vehicle(
            fleet_id=fleet.id,
            make="Test",
            model="Van",
            year=2025,
            vehicle_type=VehicleType.HYBRID,
        )
        session.add(vehicle)
        session.flush()
        device = Device(
            serial_number="MIGRATION-DEVICE",
            vehicle_id=vehicle.id,
            device_type="telematics",
        )
        session.add(device)
        session.commit()
        device_id = device.id
        vehicle_id = vehicle.id

    command.upgrade(config, "head")

    assert {"alerts", "telemetry_dead_letters"}.issubset(
        set(inspect(engine).get_table_names())
    )

    with Session(engine) as session:
        assignment = session.scalar(
            select(DeviceAssignment).where(DeviceAssignment.device_id == device_id)
        )
        assert assignment is not None
        assert assignment.vehicle_id == vehicle_id
        assert assignment.unassigned_at is None

    engine.dispose()
