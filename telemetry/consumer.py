import logging
import os
import signal
import threading

import paho.mqtt.client as mqtt
from sqlalchemy.exc import SQLAlchemyError

from db import SessionLocal
from telemetry.service import TelemetryRejected, ingest_telemetry


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
stop_event = threading.Event()


def on_connect(
    client: mqtt.Client,
    userdata: object,
    connect_flags: mqtt.ConnectFlags,
    reason_code: mqtt.ReasonCode,
    properties: mqtt.Properties | None,
) -> None:
    if reason_code.is_failure:
        logger.error("MQTT connection failed: %s", reason_code)
        return
    result, _ = client.subscribe("veylix/v1/vehicles/+/telemetry", qos=1)
    if result != mqtt.MQTT_ERR_SUCCESS:
        logger.error("Failed to subscribe to vehicle telemetry")
        return
    logger.info("Subscribed to vehicle telemetry")


def on_message(
    client: mqtt.Client,
    userdata: object,
    message: mqtt.MQTTMessage,
) -> None:
    try:
        with SessionLocal() as db:
            inserted = ingest_telemetry(db, message.topic, message.payload)
    except TelemetryRejected as error:
        logger.warning("Rejected telemetry from %s: %s", message.topic, error)
        return
    except SQLAlchemyError:
        logger.exception("Database failure while processing telemetry from %s", message.topic)
        return

    if inserted:
        logger.info("Stored %d telemetry signals from %s", inserted, message.topic)
    else:
        logger.debug("Ignored duplicate telemetry message from %s", message.topic)


def stop_consumer(signum: int, frame: object) -> None:
    logger.info("Stopping telemetry consumer")
    stop_event.set()


def main() -> None:
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="veylix-telemetry-consumer",
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=30)
    client.loop_start()
    signal.signal(signal.SIGINT, stop_consumer)
    signal.signal(signal.SIGTERM, stop_consumer)
    logger.info("Telemetry consumer connected to MQTT broker %s:%d", host, port)
    try:
        stop_event.wait()
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
