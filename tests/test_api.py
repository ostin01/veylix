from collections.abc import Generator
from datetime import datetime, timedelta, timezone
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db import Base, get_db
from enums import DeviceConnectionStatus
from main import app
from models import Device, TelemetryReading
from telemetry.connectivity import mark_stale_devices_offline
from telemetry.consumer import store_dead_letter
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
    telemetry = client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry",
        params={"signal_name": "speed_kmh", "page_size": 1},
    )
    assert telemetry.status_code == 200
    assert telemetry.json()["pagination"]["total_items"] == 1
    assert telemetry.json()["items"][0]["signal_name"] == "speed_kmh"
    assert telemetry.json()["items"][0]["value_numeric"] == 42.5
    assert telemetry.json()["items"][0]["value_text"] is None

    all_telemetry = client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry",
        params={"page": 2, "page_size": 3},
    )
    assert all_telemetry.status_code == 200
    assert all_telemetry.json()["pagination"]["total_items"] == 10
    assert len(all_telemetry.json()["items"]) == 3
    assert all_telemetry.json()["pagination"]["total_pages"] == 4
    assert client.get(
        f"/api/v1/vehicles/{vehicle_id}/telemetry",
        params={"start_time": "2026-11-15T00:00:00Z", "end_time": "2026-11-14T00:00:00Z"},
    ).status_code == 422
    assert client.get(
        "/api/v1/vehicles/00000000-0000-0000-0000-000000000001/telemetry"
    ).status_code == 404


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


def test_latest_telemetry_returns_latest_dashboard_signals_for_each_vehicle(
    client: TestClient,
) -> None:
    fleet_id = create_fleet(client)
    vehicle_id = create_vehicle(client, fleet_id)["id"]
    empty_vehicle_id = create_vehicle(
        client,
        fleet_id,
        vin="2HGCM82633A123456",
        registration_number="XYZ-456-AB",
    )["id"]
    device_response = client.post(
        "/api/v1/devices",
        json={"serial_number": "TEL-LATEST", "device_type": "telematics"},
    )
    assert device_response.status_code == 201
    device_id = UUID(device_response.json()["id"])
    observed_at = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        db.add_all(
            [
                TelemetryReading(
                    vehicle_id=UUID(vehicle_id),
                    device_id=device_id,
                    signal_name="latitude",
                    value_numeric=37.0,
                    value_text=None,
                    unit="degrees",
                    observed_at=observed_at,
                    schema_version=1,
                    message_id=uuid4(),
                ),
                TelemetryReading(
                    vehicle_id=UUID(vehicle_id),
                    device_id=device_id,
                    signal_name="latitude",
                    value_numeric=38.0,
                    value_text=None,
                    unit="degrees",
                    observed_at=observed_at.replace(minute=5),
                    schema_version=1,
                    message_id=uuid4(),
                ),
                TelemetryReading(
                    vehicle_id=UUID(vehicle_id),
                    device_id=device_id,
                    signal_name="longitude",
                    value_numeric=-122.0,
                    value_text=None,
                    unit="degrees",
                    observed_at=observed_at,
                    schema_version=1,
                    message_id=uuid4(),
                ),
                TelemetryReading(
                    vehicle_id=UUID(vehicle_id),
                    device_id=device_id,
                    signal_name="speed_kmh",
                    value_numeric=42.5,
                    value_text=None,
                    unit="km/h",
                    observed_at=observed_at,
                    schema_version=1,
                    message_id=uuid4(),
                ),
                TelemetryReading(
                    vehicle_id=UUID(vehicle_id),
                    device_id=device_id,
                    signal_name="battery_soc_percent",
                    value_numeric=84.9,
                    value_text=None,
                    unit="%",
                    observed_at=observed_at,
                    schema_version=1,
                    message_id=uuid4(),
                ),
            ]
        )
        db.commit()
    finally:
        db_generator.close()

    response = client.get("/api/v1/telemetry/latest")
    assert response.status_code == 200
    items = {item["vehicle_id"]: item for item in response.json()["items"]}
    assert set(items) == {vehicle_id, empty_vehicle_id}
    assert items[vehicle_id]["latitude"]["value"] == 38.0
    assert items[vehicle_id]["latitude"]["observed_at"].startswith("2026-11-14T01:05:00")
    assert items[vehicle_id]["longitude"]["value"] == -122.0
    assert items[vehicle_id]["speed_kmh"]["value"] == 42.5
    assert items[vehicle_id]["battery_soc_percent"]["value"] == 84.9
    assert all(
        items[empty_vehicle_id][signal] is None
        for signal in ("latitude", "longitude", "speed_kmh", "battery_soc_percent")
    )


def test_vehicle_health_and_alerts_follow_latest_diagnostics(client: TestClient) -> None:
    fleet_id = create_fleet(client)
    vehicle_id = create_vehicle(client, fleet_id)["id"]
    device_response = client.post(
        "/api/v1/devices",
        json={
            "serial_number": "TEL-HEALTH",
            "device_type": "telematics",
            "vehicle_id": vehicle_id,
        },
    )
    device_id = device_response.json()["id"]

    def ingest(observed_at: datetime, signals: dict[str, object]) -> None:
        message = {
            "schema_version": 1,
            "message_id": str(uuid4()),
            "vehicle_id": vehicle_id,
            "device_id": device_id,
            "observed_at": observed_at.isoformat(),
            "signals": signals,
        }
        db_generator = app.dependency_overrides[get_db]()
        db = next(db_generator)
        try:
            ingest_telemetry(
                db,
                f"veylix/v1/vehicles/{vehicle_id}/telemetry",
                json.dumps(message).encode(),
            )
        finally:
            db_generator.close()

    baseline_signals: dict[str, object] = {
        "latitude": 37.7749,
        "longitude": -122.4194,
        "speed_kmh": 170.0,
        "odometer_km": 12500.5,
        "battery_soc_percent": 8.0,
        "battery_voltage_v": 330.0,
        "motor_temperature_c": 130.0,
        "rpm": 5000,
        "tire_pressure_psi": 20.0,
        "vehicle_state": "driving",
    }
    observed_at = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
    ingest(observed_at, baseline_signals)

    health = client.get(f"/api/v1/vehicles/{vehicle_id}/health")
    assert health.status_code == 200
    assert health.json()["status"] == "critical"
    indicators = {item["signal_name"]: item for item in health.json()["indicators"]}
    assert indicators["motor_temperature_c"]["status"] == "critical"
    assert indicators["battery_soc_percent"]["status"] == "critical"
    assert indicators["tire_pressure_psi"]["status"] == "critical"
    assert indicators["speed_kmh"]["status"] == "warning"

    active_alerts = client.get(
        "/api/v1/alerts",
        params={"vehicle_id": vehicle_id, "active": True},
    )
    assert active_alerts.status_code == 200
    alerts_by_code = {item["code"]: item for item in active_alerts.json()["items"]}
    assert set(alerts_by_code) == {
        "motor_temperature_high",
        "battery_soc_low",
        "tire_pressure_low",
        "speed_high",
    }
    acknowledged = client.post(
        f"/api/v1/alerts/{alerts_by_code['motor_temperature_high']['id']}/acknowledge"
    )
    assert acknowledged.status_code == 200
    acknowledged_at = acknowledged.json()["acknowledged_at"]
    assert acknowledged_at is not None
    assert client.post(
        f"/api/v1/alerts/{alerts_by_code['motor_temperature_high']['id']}/acknowledge"
    ).json()["acknowledged_at"] == acknowledged_at

    healthy_signals = {
        **baseline_signals,
        "speed_kmh": 50.0,
        "battery_soc_percent": 50.0,
        "motor_temperature_c": 80.0,
        "rpm": 2500,
        "tire_pressure_psi": 35.0,
    }
    ingest(observed_at + timedelta(minutes=5), healthy_signals)
    assert client.get(
        "/api/v1/alerts",
        params={"vehicle_id": vehicle_id, "active": True},
    ).json()["pagination"]["total_items"] == 0
    history = client.get("/api/v1/alerts", params={"vehicle_id": vehicle_id}).json()
    assert len(history["items"]) == 4
    assert all(item["resolved_at"] is not None for item in history["items"])
    assert client.get(f"/api/v1/vehicles/{vehicle_id}/health").json()["status"] == "healthy"


def test_connectivity_monitor_marks_only_stale_online_devices_offline(
    client: TestClient,
) -> None:
    device_ids = []
    for serial_number in ("TEL-STALE", "TEL-RECENT", "TEL-UNKNOWN"):
        response = client.post(
            "/api/v1/devices",
            json={"serial_number": serial_number, "device_type": "telematics"},
        )
        assert response.status_code == 201
        device_ids.append(UUID(response.json()["id"]))

    checked_at = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        stale, recent, unknown = [db.get(Device, device_id) for device_id in device_ids]
        assert stale is not None and recent is not None and unknown is not None
        stale.connection_status = DeviceConnectionStatus.ONLINE
        stale.last_seen_at = checked_at - timedelta(seconds=120)
        recent.connection_status = DeviceConnectionStatus.ONLINE
        recent.last_seen_at = checked_at - timedelta(seconds=30)
        unknown.connection_status = DeviceConnectionStatus.UNKNOWN
        unknown.last_seen_at = None
        db.commit()

        assert mark_stale_devices_offline(db, checked_at, offline_after_seconds=60) == 1
        db.refresh(stale)
        db.refresh(recent)
        db.refresh(unknown)
        assert stale.connection_status == DeviceConnectionStatus.OFFLINE
        assert recent.connection_status == DeviceConnectionStatus.ONLINE
        assert unknown.connection_status == DeviceConnectionStatus.UNKNOWN
    finally:
        db_generator.close()


def test_dead_letter_endpoint_returns_quarantined_payload(client: TestClient) -> None:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        store_dead_letter(
            db,
            "veylix/v1/vehicles/invalid/telemetry",
            b"\xffinvalid",
            "TelemetryRejected",
            "invalid payload",
            attempts=1,
        )
        db.commit()
        store_dead_letter(
            db,
            "veylix/v1/vehicles/invalid/telemetry",
            b"\xffinvalid",
            "TelemetryRejected",
            "invalid payload",
            attempts=2,
        )
        db.commit()
    finally:
        db_generator.close()

    response = client.get("/api/v1/telemetry/dead-letters")
    assert response.status_code == 200
    assert response.json()["pagination"]["total_items"] == 1
    assert response.json()["items"][0]["payload_base64"] == "/2ludmFsaWQ="
    assert response.json()["items"][0]["attempts"] == 3
