import json
import logging
import os
import signal
import threading
import time
from uuid import UUID

import paho.mqtt.client as mqtt

from simulator.registry import get_active_assignments
from simulator.vehicle import SimulatedVehicle, create_simulated_vehicles


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)
stop_event = threading.Event()


def stop_simulator(signum: int, frame: object) -> None:
    logger.info("Stopping vehicle simulator")
    stop_event.set()


def main() -> None:
    interval = float(os.getenv("SIMULATOR_PUBLISH_INTERVAL_SECONDS", "5"))
    seed = int(os.getenv("SIMULATOR_RANDOM_SEED", "42"))
    if interval <= 0:
        raise ValueError("SIMULATOR_PUBLISH_INTERVAL_SECONDS must be positive")

    vehicles_by_assignment: dict[tuple[UUID, UUID], SimulatedVehicle] = {}
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="veylix-vehicle-simulator",
    )
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    client.connect(host, port, keepalive=30)
    client.loop_start()

    signal.signal(signal.SIGINT, stop_simulator)
    signal.signal(signal.SIGTERM, stop_simulator)
    logger.info(
        "Publishing assigned vehicles to MQTT broker %s:%d every %.1fs",
        host,
        port,
        interval,
    )

    try:
        while not stop_event.is_set():
            started_at = time.monotonic()
            assignments = get_active_assignments()
            new_assignments = [
                (device_id, vehicle_id)
                for device_id, vehicle_id in assignments
                if (device_id, vehicle_id) not in vehicles_by_assignment
            ]
            for vehicle in create_simulated_vehicles(new_assignments, seed):
                vehicles_by_assignment[(vehicle.device_id, vehicle.vehicle_id)] = vehicle

            active_assignment_keys = set(assignments)
            vehicles_by_assignment = {
                key: vehicle
                for key, vehicle in vehicles_by_assignment.items()
                if key in active_assignment_keys
            }
            if not vehicles_by_assignment:
                logger.info("No assigned devices found; waiting for vehicle/device assignments")
                stop_event.wait(interval)
                continue

            for vehicle in vehicles_by_assignment.values():
                message = vehicle.step(interval)
                topic = f"veylix/v1/vehicles/{vehicle.vehicle_id}/telemetry"
                result = client.publish(
                    topic,
                    json.dumps(message),
                    qos=1,
                )
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.error("Failed to publish telemetry to %s", topic)
                else:
                    logger.debug("Published telemetry to %s", topic)
            stop_event.wait(max(0.0, interval - (time.monotonic() - started_at)))
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
