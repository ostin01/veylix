import queue
from types import SimpleNamespace

from sqlalchemy.exc import SQLAlchemyError

from telemetry import consumer


class AckClient:
    def __init__(self) -> None:
        self.acknowledged: list[tuple[int, int]] = []

    def ack(self, message_id: int, qos: int) -> int:
        self.acknowledged.append((message_id, qos))
        return 0


def test_consumer_retries_database_errors_before_acknowledging(monkeypatch) -> None:
    attempts = 0

    class SessionContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def ingest(db, topic: str, payload: bytes) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise SQLAlchemyError("temporary database failure")
        return 10

    monkeypatch.setattr(consumer, "SessionLocal", SessionContext)
    monkeypatch.setattr(consumer, "ingest_telemetry", ingest)
    monkeypatch.setattr(consumer.stop_event, "wait", lambda timeout: False)
    consumer.stop_event.clear()

    message = SimpleNamespace(
        mid=7,
        qos=1,
        topic="veylix/v1/vehicles/vehicle-id/telemetry",
        payload=b"{}",
    )
    client = AckClient()
    consumer.process_message(client, message)

    assert attempts == 2
    assert client.acknowledged == [(7, 1)]


def test_consumer_quarantines_after_retry_limit_and_keeps_worker_alive(monkeypatch) -> None:
    attempts = 0
    quarantined = []

    class SessionContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def ingest(db, topic: str, payload: bytes) -> int:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("unexpected processing failure")

    monkeypatch.setattr(consumer, "SessionLocal", SessionContext)
    monkeypatch.setattr(consumer, "ingest_telemetry", ingest)
    monkeypatch.setattr(
        consumer,
        "persist_dead_letter",
        lambda *args: quarantined.append(args),
    )
    monkeypatch.setattr(consumer, "MAX_PROCESSING_ATTEMPTS", 3)
    monkeypatch.setattr(consumer.stop_event, "wait", lambda timeout: False)
    consumer.stop_event.clear()

    message = SimpleNamespace(
        mid=8,
        qos=1,
        topic="veylix/v1/vehicles/vehicle-id/telemetry",
        payload=b'{"bad":"payload"}',
    )
    client = AckClient()
    consumer.process_message(client, message)

    assert attempts == 3
    assert len(quarantined) == 1
    assert quarantined[0][2:] == (
        "RuntimeError",
        "unexpected processing failure",
        3,
    )
    assert client.acknowledged == [(8, 1)]


def test_rejected_messages_are_quarantined_before_acknowledgement(monkeypatch) -> None:
    quarantined = []

    class SessionContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def rollback(self) -> None:
            pass

    def reject(db, topic: str, payload: bytes) -> int:
        raise consumer.TelemetryRejected("invalid payload")

    monkeypatch.setattr(consumer, "SessionLocal", SessionContext)
    monkeypatch.setattr(consumer, "ingest_telemetry", reject)
    monkeypatch.setattr(
        consumer,
        "persist_dead_letter",
        lambda *args: quarantined.append(args),
    )
    consumer.stop_event.clear()

    message = SimpleNamespace(
        mid=9,
        qos=1,
        topic="veylix/v1/vehicles/vehicle-id/telemetry",
        payload=b"invalid",
    )
    client = AckClient()
    consumer.process_message(client, message)

    assert len(quarantined) == 1
    assert quarantined[0][2:] == ("TelemetryRejected", "invalid payload", 1)
    assert client.acknowledged == [(9, 1)]


def test_queue_overflow_does_not_block_or_acknowledge_message(monkeypatch) -> None:
    class DisconnectClient:
        def __init__(self) -> None:
            self.disconnected = False

        def disconnect(self) -> int:
            self.disconnected = True
            return 0

    bounded_queue = queue.Queue(maxsize=1)
    bounded_queue.put(object())
    monkeypatch.setattr(consumer, "message_queue", bounded_queue)
    consumer.stop_event.clear()

    client = DisconnectClient()
    message = SimpleNamespace(mid=10, qos=1, topic="test/topic", payload=b"{}")
    consumer.on_message(client, None, message)

    assert client.disconnected
    assert consumer.stop_event.is_set()
    consumer.stop_event.clear()
