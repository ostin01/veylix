import hashlib
import logging
import os
import queue
import signal
import threading

import paho.mqtt.client as mqtt
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import SessionLocal
from models import TelemetryDeadLetter, utc_now
from telemetry.connectivity import mark_stale_devices_offline
from telemetry.mqtt_config import configure_mqtt_client
from telemetry.protocol import TELEMETRY_TOPIC_FILTER
from telemetry.service import TelemetryRejected, ingest_telemetry


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
stop_event = threading.Event()
message_queue: queue.Queue[mqtt.MQTTMessage] = queue.Queue(maxsize=100)


def _positive_int_setting(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


MAX_PROCESSING_ATTEMPTS = _positive_int_setting("TELEMETRY_MAX_ATTEMPTS", 5)
OFFLINE_AFTER_SECONDS = _positive_int_setting("DEVICE_OFFLINE_AFTER_SECONDS", 60)
OFFLINE_CHECK_INTERVAL_SECONDS = _positive_int_setting(
    "DEVICE_OFFLINE_CHECK_INTERVAL_SECONDS", 10
)


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
    result, _ = client.subscribe(TELEMETRY_TOPIC_FILTER, qos=1)
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
        message_queue.put_nowait(message)
    except queue.Full:
        logger.error(
            "Telemetry queue is full; stopping consumer so unacknowledged messages "
            "can be redelivered"
        )
        stop_event.set()
        result = client.disconnect()
        if result != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Failed to disconnect after telemetry queue overflow")


def store_dead_letter(
    db: Session,
    topic: str,
    payload: bytes,
    error_type: str,
    reason: str,
    attempts: int,
) -> None:
    message_hash = hashlib.sha256(topic.encode("utf-8") + b"\0" + payload).hexdigest()
    dead_letter = db.scalar(
        select(TelemetryDeadLetter).where(
            TelemetryDeadLetter.message_hash == message_hash
        )
    )
    now = utc_now()
    if dead_letter is None:
        db.add(
            TelemetryDeadLetter(
                message_hash=message_hash,
                topic=topic,
                payload=payload,
                error_type=error_type[:100],
                reason=reason[:4000],
                attempts=attempts,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    else:
        dead_letter.error_type = error_type[:100]
        dead_letter.reason = reason[:4000]
        dead_letter.attempts += attempts
        dead_letter.last_seen_at = now


def persist_dead_letter(
    topic: str,
    payload: bytes,
    error_type: str,
    reason: str,
    attempts: int,
) -> None:
    with SessionLocal() as db:
        store_dead_letter(db, topic, payload, error_type, reason, attempts)
        db.commit()


def _acknowledge(client: mqtt.Client, message: mqtt.MQTTMessage) -> None:
    if message.qos > 0:
        result = client.ack(message.mid, message.qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Failed to acknowledge telemetry message %d", message.mid)


def process_message(client: mqtt.Client, message: mqtt.MQTTMessage) -> None:
    retry_delay = 1
    for attempt in range(1, MAX_PROCESSING_ATTEMPTS + 1):
        if stop_event.is_set():
            return
        try:
            rejection: TelemetryRejected | None = None
            with SessionLocal() as db:
                try:
                    inserted = ingest_telemetry(db, message.topic, message.payload)
                except TelemetryRejected as error:
                    db.rollback()
                    rejection = error

            if rejection is not None:
                error = rejection
                persist_dead_letter(
                    message.topic,
                    message.payload,
                    type(error).__name__,
                    str(error),
                    attempt,
                )
                logger.warning(
                    "Quarantined rejected telemetry from %s: %s",
                    message.topic,
                    error,
                )
                _acknowledge(client, message)
                return

            if inserted:
                logger.info("Stored %d telemetry signals from %s", inserted, message.topic)
            else:
                logger.debug("Ignored duplicate telemetry message from %s", message.topic)
            _acknowledge(client, message)
            return
        except Exception as error:
            if attempt < MAX_PROCESSING_ATTEMPTS:
                logger.exception(
                    "Unexpected failure processing telemetry from %s; retrying in %ds "
                    "(attempt %d/%d)",
                    message.topic,
                    retry_delay,
                    attempt,
                    MAX_PROCESSING_ATTEMPTS,
                )
                if stop_event.wait(retry_delay):
                    return
                retry_delay = min(retry_delay * 2, 60)
                continue

            logger.exception(
                "Telemetry processing exhausted %d attempts for %s; quarantining",
                MAX_PROCESSING_ATTEMPTS,
                message.topic,
            )
            try:
                persist_dead_letter(
                    message.topic,
                    message.payload,
                    type(error).__name__,
                    str(error),
                    attempt,
                )
            except Exception:
                logger.exception(
                    "Could not quarantine telemetry from %s; leaving it unacknowledged",
                    message.topic,
                )
                return
            _acknowledge(client, message)
            return


def process_messages(client: mqtt.Client) -> None:
    while not stop_event.is_set():
        try:
            message = message_queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            process_message(client, message)
        except Exception:
            logger.exception(
                "Unhandled consumer worker error for %s; message remains unacknowledged",
                message.topic,
            )
        finally:
            message_queue.task_done()


def monitor_device_connectivity() -> None:
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                offline_count = mark_stale_devices_offline(
                    db,
                    utc_now(),
                    OFFLINE_AFTER_SECONDS,
                )
            if offline_count:
                logger.info("Marked %d stale devices offline", offline_count)
        except Exception:
            logger.exception("Device connectivity check failed; will retry")
        if stop_event.wait(OFFLINE_CHECK_INTERVAL_SECONDS):
            return


def stop_consumer(signum: int, frame: object) -> None:
    logger.info("Stopping telemetry consumer")
    stop_event.set()


def main() -> None:
    stop_event.clear()
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "8883"))
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="veylix-telemetry-consumer",
        clean_session=False,
        manual_ack=True,
    )
    configure_mqtt_client(client)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect(host, port, keepalive=30)
    worker = threading.Thread(target=process_messages, args=(client,), daemon=True)
    connectivity_worker = threading.Thread(
        target=monitor_device_connectivity,
        daemon=True,
    )
    worker.start()
    connectivity_worker.start()
    client.loop_start()
    signal.signal(signal.SIGINT, stop_consumer)
    signal.signal(signal.SIGTERM, stop_consumer)
    logger.info("Telemetry consumer connected to MQTT broker %s:%d", host, port)
    try:
        stop_event.wait()
    finally:
        client.disconnect()
        client.loop_stop()
        worker.join(timeout=5)
        connectivity_worker.join(timeout=5)


if __name__ == "__main__":
    main()
