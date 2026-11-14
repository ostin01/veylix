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
