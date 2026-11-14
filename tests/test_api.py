from collections.abc import Generator
import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db import Base, get_db
from main import app
from models import Device, TelemetryReading
from telemetry.service import TelemetryRejected, ingest_telemetry


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_fleet(client: TestClient) -> str:
    response = client.post("/api/v1/fleets", json={"name": "North Depot"})
    assert response.status_code == 201
    return response.json()["id"]


def create_vehicle(
    client: TestClient,
    fleet_id: str,
    vin: str = "1HGCM82633A123456",
    registration_number: str = "ABC-123-XY",
) -> dict:
    response = client.post(
        "/api/v1/vehicles",
        json={
            "fleet_id": fleet_id,
            "vin": vin,
            "registration_number": registration_number,
            "make": "Honda",
            "model": "Accord",
            "year": 2025,
            "vehicle_type": "hybrid",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_fleet_and_vehicle_crud_persist_between_requests(client: TestClient) -> None:
    fleet_id = create_fleet(client)
    vehicle = create_vehicle(client, fleet_id)
    vehicle_id = vehicle["id"]

    assert client.get(f"/api/v1/fleets/{fleet_id}").status_code == 200
    assert client.get(f"/api/v1/vehicles/{vehicle_id}").json()["status"] == "active"

    updated = client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        json={"status": "maintenance"},
    )
    assert updated.status_code == 200
    assert client.get(f"/api/v1/vehicles/{vehicle_id}").json()["status"] == "maintenance"

    listing = client.get(
        "/api/v1/vehicles",
        params={"fleet_id": fleet_id, "status": "maintenance", "search": "honda"},
    )
    assert listing.json()["pagination"]["total_items"] == 1
    assert listing.json()["items"][0]["id"] == vehicle_id


def test_foreign_keys_duplicate_identifiers_and_delete_rules(client: TestClient) -> None:
    fleet_id = create_fleet(client)
    vehicle = create_vehicle(client, fleet_id)
    vehicle_id = vehicle["id"]

    assert client.delete(f"/api/v1/fleets/{fleet_id}").status_code == 409
    duplicate = client.post(
        "/api/v1/vehicles",
        json={
            "fleet_id": fleet_id,
            "vin": "1HGCM82633A123456",
            "registration_number": "other",
            "make": "Honda",
            "model": "Civic",
            "year": 2025,
            "vehicle_type": "hybrid",
        },
    )
    assert duplicate.status_code == 409
    duplicate_registration = client.post(
        "/api/v1/vehicles",
        json={
            "fleet_id": fleet_id,
            "vin": "2HGCM82633A123456",
            "registration_number": "abc-123-xy",
            "make": "Honda",
            "model": "Civic",
            "year": 2025,
            "vehicle_type": "hybrid",
        },
    )
    assert duplicate_registration.status_code == 409

    assert client.delete(f"/api/v1/vehicles/{vehicle_id}").status_code == 204
    assert client.delete(f"/api/v1/fleets/{fleet_id}").status_code == 204
    assert client.get(f"/api/v1/fleets/{fleet_id}").status_code == 404


def test_vehicle_creation_requires_existing_fleet(client: TestClient) -> None:
    response = client.post(
        "/api/v1/vehicles",
        json={
            "fleet_id": "00000000-0000-0000-0000-000000000001",
            "make": "Honda",
            "model": "Accord",
            "year": 2025,
            "vehicle_type": "hybrid",
        },
    )
    assert response.status_code == 404


def test_device_registration_assignment_filtering_and_update(client: TestClient) -> None:
    fleet_id = create_fleet(client)
    vehicle_id = create_vehicle(client, fleet_id)["id"]

    created = client.post(
        "/api/v1/devices",
        json={
            "serial_number": "TEL-001",
            "device_type": "telematics",
            "firmware_version": "1.2.0",
            "connection_status": "online",
        },
    )
    assert created.status_code == 422
    created = client.post(
        "/api/v1/devices",
        json={
            "serial_number": "TEL-001",
            "device_type": "telematics",
            "firmware_version": "1.2.0",
        },
    )
    assert created.status_code == 201
    device = created.json()
    device_id = device["id"]
    assert device["vehicle_id"] is None
    assert device["connection_status"] == "unknown"
    assert device["last_seen_at"] is None

    assigned = client.post(
        f"/api/v1/devices/{device_id}/assign",
        json={"vehicle_id": vehicle_id},
    )
    assert assigned.status_code == 200
    assert assigned.json()["vehicle_id"] == vehicle_id

    updated = client.patch(
        f"/api/v1/devices/{device_id}",
        json={
            "firmware_version": "1.3.0",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["connection_status"] == "unknown"
    assert updated.json()["firmware_version"] == "1.3.0"
    assert updated.json()["last_seen_at"] is None
    rejected_status_update = client.patch(
        f"/api/v1/devices/{device_id}",
        json={"connection_status": "online"},
    )
    assert rejected_status_update.status_code == 422
    rejected_last_seen_update = client.patch(
        f"/api/v1/devices/{device_id}",
        json={"last_seen_at": "2026-11-09T12:00:00Z"},
    )
    assert rejected_last_seen_update.status_code == 422

    listing = client.get(
        "/api/v1/devices",
        params={"vehicle_id": vehicle_id, "connection_status": "unknown", "search": "TEL"},
    )
    assert listing.status_code == 200
    assert listing.json()["pagination"]["total_items"] == 1
    assert listing.json()["items"][0]["id"] == device_id
    assert client.get(f"/api/v1/devices/{device_id}").status_code == 200
    history = client.get(f"/api/v1/devices/{device_id}/assignments")
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["vehicle_id"] == vehicle_id
    assert history.json()[0]["unassigned_at"] is None


def test_device_reassignment_preserves_history_and_protects_vehicle(client: TestClient) -> None:
    first_fleet_id = create_fleet(client)
    second_fleet = client.post("/api/v1/fleets", json={"name": "South Depot"})
    assert second_fleet.status_code == 201
    first_vehicle_id = create_vehicle(client, first_fleet_id)["id"]
    second_vehicle_id = create_vehicle(
        client,
        second_fleet.json()["id"],
        vin="2HGCM82633A123456",
        registration_number="XYZ-456-AB",
    )["id"]
    created = client.post(
        "/api/v1/devices",
        json={
            "serial_number": "TEL-HISTORY",
            "device_type": "telematics",
            "vehicle_id": first_vehicle_id,
        },
    )
    assert created.status_code == 201
    device_id = created.json()["id"]

    history_before = client.get(f"/api/v1/devices/{device_id}/assignments").json()
    assert len(history_before) == 1
    assert history_before[0]["vehicle_id"] == first_vehicle_id
    assert client.delete(f"/api/v1/vehicles/{first_vehicle_id}").status_code == 409

    reassigned = client.post(
        f"/api/v1/devices/{device_id}/assign",
        json={"vehicle_id": second_vehicle_id},
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["vehicle_id"] == second_vehicle_id
    history = client.get(f"/api/v1/devices/{device_id}/assignments").json()
    assert len(history) == 2
    assert history[0]["vehicle_id"] == first_vehicle_id
    assert history[0]["unassigned_at"] is not None
    assert history[1]["vehicle_id"] == second_vehicle_id
    assert history[1]["unassigned_at"] is None

    unassigned = client.delete(f"/api/v1/devices/{device_id}/assignment")
    assert unassigned.status_code == 200
    assert unassigned.json()["vehicle_id"] is None
    final_history = client.get(f"/api/v1/devices/{device_id}/assignments").json()
    assert len(final_history) == 2
    assert final_history[1]["unassigned_at"] is not None
    assert client.delete(f"/api/v1/vehicles/{first_vehicle_id}").status_code == 409


def test_device_duplicate_serial_and_invalid_assignments(client: TestClient) -> None:
    created = client.post(
        "/api/v1/devices",
        json={"serial_number": "TEL-001", "device_type": "telematics"},
    )
    assert created.status_code == 201
    device_id = created.json()["id"]

    duplicate = client.post(
        "/api/v1/devices",
        json={"serial_number": "tel-001", "device_type": "diagnostic"},
    )
    assert duplicate.status_code == 409

    invalid_assignment = client.post(
        f"/api/v1/devices/{device_id}/assign",
        json={"vehicle_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert invalid_assignment.status_code == 404
    assert client.get(f"/api/v1/devices/{device_id}").json()["vehicle_id"] is None
    assert client.get(f"/api/v1/devices/{device_id}/assignments").json() == []


def test_telemetry_is_validated_stored_idempotently_and_updates_device_status(
    client: TestClient,
) -> None:
    fleet_id = create_fleet(client)
    vehicle_id = create_vehicle(client, fleet_id)["id"]
    device_response = client.post(
        "/api/v1/devices",
        json={
            "serial_number": "TEL-TELEMETRY",
            "device_type": "telematics",
            "vehicle_id": vehicle_id,
        },
    )
    assert device_response.status_code == 201
    device_id = device_response.json()["id"]
    message = {
        "schema_version": 1,
        "message_id": "fc3d08b0-0082-4c72-8b12-e7d15ae59a01",
        "vehicle_id": vehicle_id,
        "device_id": device_id,
        "observed_at": "2026-11-14T01:00:00Z",
        "signals": {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "speed_kmh": 42.5,
            "odometer_km": 12500.5,
            "battery_soc_percent": 84.9,
            "battery_voltage_v": 387.9,
            "motor_temperature_c": 57.6,
            "rpm": 2040,
            "tire_pressure_psi": 35.1,
            "vehicle_state": "driving",
        },
    }
    topic = f"veylix/v1/vehicles/{vehicle_id}/telemetry"
    payload = json.dumps(message).encode()

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        assert ingest_telemetry(db, topic, payload) == 10
        assert ingest_telemetry(db, topic, payload) == 0
        readings = db.query(TelemetryReading).all()
        assert len(readings) == 10
        speed = next(reading for reading in readings if reading.signal_name == "speed_kmh")
        assert speed.value_numeric == 42.5
        assert speed.value_text is None
        assert speed.unit == "km/h"
        state = next(reading for reading in readings if reading.signal_name == "vehicle_state")
        assert state.value_text == "driving"
        assert state.value_numeric is None
        device = db.get(Device, UUID(device_id))
        assert device is not None
        assert device.connection_status.value == "online"
        assert device.last_seen_at is not None
    finally:
        db_generator.close()
    assert client.delete(f"/api/v1/vehicles/{vehicle_id}").status_code == 409


def test_telemetry_rejects_unregistered_or_mismatched_sender(client: TestClient) -> None:
    fleet_id = create_fleet(client)
    vehicle_id = create_vehicle(client, fleet_id)["id"]
    device_response = client.post(
        "/api/v1/devices",
        json={"serial_number": "TEL-UNASSIGNED", "device_type": "telematics"},
    )
    device_id = device_response.json()["id"]
    message = {
        "schema_version": 1,
        "message_id": "fc3d08b0-0082-4c72-8b12-e7d15ae59a02",
        "vehicle_id": vehicle_id,
        "device_id": device_id,
        "observed_at": "2026-11-14T01:00:00Z",
        "signals": {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "speed_kmh": 42.5,
            "odometer_km": 12500.5,
            "battery_soc_percent": 84.9,
            "battery_voltage_v": 387.9,
            "motor_temperature_c": 57.6,
            "rpm": 2040,
            "tire_pressure_psi": 35.1,
            "vehicle_state": "driving",
        },
    }

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        with pytest.raises(TelemetryRejected, match="not currently assigned"):
            ingest_telemetry(
                db,
                f"veylix/v1/vehicles/{vehicle_id}/telemetry",
                json.dumps(message).encode(),
            )
        message["signals"]["latitude"] = 91
        with pytest.raises(TelemetryRejected, match="invalid telemetry payload"):
            ingest_telemetry(
                db,
                f"veylix/v1/vehicles/{vehicle_id}/telemetry",
                json.dumps(message).encode(),
            )
    finally:
        db_generator.close()
