from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db import Base, get_db
from main import app


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


def create_vehicle(client: TestClient, fleet_id: str) -> dict:
    response = client.post(
        "/api/v1/vehicles",
        json={
            "fleet_id": fleet_id,
            "vin": "1HGCM82633A123456",
            "registration_number": "ABC-123-XY",
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
