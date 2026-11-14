from uuid import UUID

import pytest

from simulator.vehicle import SimulatedVehicle, create_simulated_vehicles


def test_simulated_vehicle_emits_valid_correlated_signals() -> None:
    vehicle = SimulatedVehicle(
        vehicle_id=UUID("00000000-0000-0000-0000-000000000001"),
        device_id=UUID("00000000-0000-0000-0000-000000000002"),
        latitude=37.7749,
        longitude=-122.4194,
        seed=7,
    )

    first = vehicle.step(5)
    initial_odometer = first["signals"]["odometer_km"]
    second = vehicle.step(5)

    assert second["schema_version"] == 1
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
    assert signals["motor_temperature_c"] >= 0
    assert signals["rpm"] >= 0
    assert 20 <= signals["tire_pressure_psi"] <= 50


def test_simulator_ids_are_stable_and_unique() -> None:
    first = create_simulated_vehicles(3, seed=10)
    again = create_simulated_vehicles(3, seed=10)

    assert [vehicle.vehicle_id for vehicle in first] == [
        vehicle.vehicle_id for vehicle in again
    ]
    assert len({vehicle.vehicle_id for vehicle in first}) == 3
    assert len({vehicle.device_id for vehicle in first}) == 3


@pytest.mark.parametrize("count", [0, 101])
def test_simulator_rejects_invalid_vehicle_count(count: int) -> None:
    with pytest.raises(ValueError):
        create_simulated_vehicles(count, seed=0)


def test_simulator_rejects_nonpositive_elapsed_time() -> None:
    vehicle = create_simulated_vehicles(1, seed=0)[0]
    with pytest.raises(ValueError):
        vehicle.step(0)
