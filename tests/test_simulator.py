import json
from uuid import UUID

import pytest

from simulator.vehicle import SimulatedVehicle, create_simulated_vehicles
from telemetry.protocol import parse_telemetry_topic, telemetry_topic
from telemetry.schemas import TelemetryMessage


def test_simulated_vehicle_emits_valid_correlated_signals() -> None:
    vehicle = SimulatedVehicle(
        fleet_id=UUID("00000000-0000-0000-0000-000000000003"),
        vehicle_id=UUID("00000000-0000-0000-0000-000000000001"),
        device_id=UUID("00000000-0000-0000-0000-000000000002"),
        battery_voltage_range=(300, 450),
        latitude=37.7749,
        longitude=-122.4194,
        seed=7,
    )

    first = vehicle.step(5)
    initial_odometer = first["signals"]["odometer_km"]
    second = vehicle.step(5)

    message = TelemetryMessage.model_validate_json(json.dumps(second))
    message.validate_timestamp()
    topic = telemetry_topic(vehicle.fleet_id, message.vehicle_id)
    assert parse_telemetry_topic(topic) == (vehicle.fleet_id, message.vehicle_id)
    assert second["schema_version"] == "1.0"
    assert second["sent_at"]
    assert UUID(second["message_id"])
    assert second["vehicle_id"] == str(vehicle.vehicle_id)
    assert second["device_id"] == str(vehicle.device_id)
    signals = second["signals"]
    assert set(signals) == {
        "latitude",
        "longitude",
        "speed_kmh",
        "odometer_km",
        "battery_soc_percent",
        "battery_voltage_v",
        "motor_temperature_c",
        "rpm",
        "tire_pressure_psi",
        "vehicle_state",
    }
    assert -90 <= signals["latitude"] <= 90
    assert -180 <= signals["longitude"] <= 180
    assert signals["speed_kmh"] >= 0
    assert signals["odometer_km"] > initial_odometer
    assert 0 <= signals["battery_soc_percent"] <= 100
    assert 300 <= signals["battery_voltage_v"] <= 450
    assert signals["motor_temperature_c"] >= 0
    assert signals["rpm"] >= 0
    assert 20 <= signals["tire_pressure_psi"] <= 50


def test_simulator_uses_registered_device_vehicle_assignments() -> None:
    assignments = [
        (UUID(int=1), UUID(int=11), UUID(int=21), (300, 450)),
        (UUID(int=2), UUID(int=12), UUID(int=22), None),
    ]
    vehicles = create_simulated_vehicles(assignments, seed=10)

    assert [
        (
            vehicle.device_id,
            vehicle.vehicle_id,
            vehicle.fleet_id,
            vehicle.battery_voltage_range,
        )
        for vehicle in vehicles
    ] == assignments
    with pytest.raises(ValueError):
        create_simulated_vehicles(
            [(UUID(int=1), UUID(int=11), UUID(int=21), (300, 450))] * 101,
            seed=0,
        )


def test_simulator_rejects_duplicate_device_assignments() -> None:
    device_id = UUID(int=1)
    with pytest.raises(ValueError):
        create_simulated_vehicles(
            [
                (device_id, UUID(int=11), UUID(int=21), (300, 450)),
                (device_id, UUID(int=12), UUID(int=22), (300, 450)),
            ],
            seed=0,
        )


def test_simulator_rejects_nonpositive_elapsed_time() -> None:
    vehicle = create_simulated_vehicles(
        [(UUID(int=1), UUID(int=11), UUID(int=21), (300, 450))],
        seed=0,
    )[0]
    with pytest.raises(ValueError):
        vehicle.step(0)


def test_simulator_uses_profile_voltage_limits() -> None:
    vehicle = create_simulated_vehicles(
        [(UUID(int=1), UUID(int=11), UUID(int=21), (12.2, 15.0))],
        seed=0,
    )[0]
    message = vehicle.step(5)
    assert 12.2 <= message["signals"]["battery_voltage_v"] <= 15.0


def test_telemetry_topic_parser_rejects_topics_outside_the_contract() -> None:
    with pytest.raises(ValueError, match="unexpected telemetry topic"):
        parse_telemetry_topic("veylix/v1/devices/device-id/telemetry")

    with pytest.raises(ValueError, match="invalid fleet or vehicle ID"):
        parse_telemetry_topic(
            "veylix/v1/fleets/not-a-uuid/vehicles/00000000-0000-0000-0000-000000000001/telemetry"
        )
