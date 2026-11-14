import json
import logging
import os
import signal
import threading
import time

import paho.mqtt.client as mqtt

from simulator.vehicle import create_simulated_vehicles


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
    count = int(os.getenv("SIMULATOR_VEHICLE_COUNT", "3"))
    interval = float(os.getenv("SIMULATOR_PUBLISH_INTERVAL_SECONDS", "5"))
    seed = int(os.getenv("SIMULATOR_RANDOM_SEED", "42"))
    if interval <= 0:
        raise ValueError("SIMULATOR_PUBLISH_INTERVAL_SECONDS must be positive")

    vehicles = create_simulated_vehicles(count, seed)
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
        "Simulating %d vehicles; publishing to MQTT broker %s:%d every %.1fs",
        len(vehicles),
        host,
        port,
        interval,
    )

    try:
        while not stop_event.is_set():
            started_at = time.monotonic()
            for vehicle in vehicles:
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
