import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4, uuid5


@dataclass
class SimulatedVehicle:
    vehicle_id: UUID
    device_id: UUID
    latitude: float
    longitude: float
    seed: int
    speed_kmh: float = 0.0
    odometer_km: float = 12_500.0
    battery_soc_percent: float = 85.0
    motor_temperature_c: float = 28.0
    state: Literal["driving", "parked"] = "driving"
    elapsed_seconds: float = 0.0
    _random: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._random = random.Random(self.seed)

    def step(self, elapsed_seconds: float) -> dict[str, object]:
        if elapsed_seconds <= 0:
            raise ValueError("elapsed_seconds must be positive")

        self.elapsed_seconds += elapsed_seconds
        cycle_seconds = self.elapsed_seconds % 300
        should_move = cycle_seconds < 240 or cycle_seconds >= 270

        if should_move:
            target_speed = 55 + 15 * math.sin(self.elapsed_seconds / 24)
            self.speed_kmh += (target_speed - self.speed_kmh) * min(
                1.0, elapsed_seconds / 8
            )
        else:
            self.speed_kmh += (0.0 - self.speed_kmh) * min(1.0, elapsed_seconds / 8)
        self.state = "driving" if self.speed_kmh >= 1 else "parked"

        distance_km = self.speed_kmh * elapsed_seconds / 3600
        self.odometer_km += distance_km
        self.battery_soc_percent = max(
            0.0,
            self.battery_soc_percent
            - distance_km * 0.22
            + (0.01 if self.speed_kmh > 35 else 0.0),
        )

        bearing = math.radians(35 + 8 * math.sin(self.elapsed_seconds / 90))
        latitude_delta = distance_km * math.cos(bearing) / 111.32
        longitude_scale = max(math.cos(math.radians(self.latitude)), 0.1)
        longitude_delta = (
            distance_km * math.sin(bearing) / (111.32 * longitude_scale)
        )
        self.latitude += latitude_delta
        self.longitude += longitude_delta

        target_temperature = 27 + self.speed_kmh * 0.72
        self.motor_temperature_c += (
            target_temperature - self.motor_temperature_c
        ) * min(1.0, elapsed_seconds / 180)

        return {
            "schema_version": 1,
            "message_id": str(uuid4()),
            "vehicle_id": str(self.vehicle_id),
            "device_id": str(self.device_id),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "signals": {
                "latitude": round(self.latitude, 6),
                "longitude": round(self.longitude, 6),
                "speed_kmh": round(self.speed_kmh, 2),
                "odometer_km": round(self.odometer_km, 3),
                "battery_soc_percent": round(self.battery_soc_percent, 2),
                "battery_voltage_v": round(
                    320 + self.battery_soc_percent * 0.8, 1
                ),
                "motor_temperature_c": round(self.motor_temperature_c, 1),
                "rpm": round(self.speed_kmh * 48),
                "tire_pressure_psi": round(
                    35 + self._random.uniform(-0.3, 0.3), 1
                ),
                "vehicle_state": self.state,
            },
        }


def create_simulated_vehicles(count: int, seed: int) -> list[SimulatedVehicle]:
    if count < 1:
        raise ValueError("count must be at least 1")
    if count > 100:
        raise ValueError("count must not exceed 100")

    namespace = UUID("b962b266-f4a4-4a14-9f2d-c504f230895f")
    vehicles = []
    for index in range(count):
        vehicles.append(
            SimulatedVehicle(
                vehicle_id=uuid5(namespace, f"vehicle-{index + 1}"),
                device_id=uuid5(namespace, f"device-{index + 1}"),
                latitude=37.7749 + index * 0.01,
                longitude=-122.4194 - index * 0.01,
                seed=seed + index,
            )
        )
    return vehicles
