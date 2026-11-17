import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request

import events
from enums import UserRole


def test_event_envelope_has_unique_id_timestamp_and_small_payload() -> None:
    first = events.EventEnvelope(type="vehicle.location.updated", fleet_id=uuid4(), data={"latitude": 1.2})
    second = events.EventEnvelope(type="vehicle.location.updated", fleet_id=first.fleet_id)
    assert first.id != second.id
    assert first.timestamp.tzinfo is not None
    assert first.model_dump(mode="json")["data"] == {"latitude": 1.2}
    assert "id:" not in events.encode_sse(first)


def test_publisher_serializes_events_and_handles_redis_failure(monkeypatch) -> None:
    published = []

    class Publisher:
        def publish(self, channel, payload):
            published.append((channel, json.loads(payload)))

    monkeypatch.setattr(events, "_publisher", lambda: Publisher())
    fleet_id = uuid4()
    assert events.publish_event("device.connected", fleet_id=fleet_id, data={"status": "online"})
    assert published[0][0] == events.EVENT_CHANNEL
    assert published[0][1]["fleet_id"] == str(fleet_id)
    assert published[0][1]["type"] == "device.connected"

    class BrokenPublisher:
        def publish(self, *_args):
            raise events.RedisError("offline")

    monkeypatch.setattr(events, "_publisher", lambda: BrokenPublisher())
    assert not events.publish_event("device.disconnected", fleet_id=fleet_id)


def test_stream_delivers_event_and_closes_subscriber(monkeypatch) -> None:
    envelope = events.EventEnvelope(type="alert.created", fleet_id=uuid4(), data={"alert_id": "a1"})
    closed = []

    class PubSub:
        async def subscribe(self, _channel): pass
        async def get_message(self, **_kwargs):
            if hasattr(self, "sent"):
                return None
            self.sent = True
            return {"type": "message", "data": envelope.model_dump_json()}
        async def aclose(self): closed.append("pubsub")

    class Client:
        def pubsub(self): return PubSub()
        async def aclose(self): closed.append("client")

    class FakeRequest:
        checks = 0
        async def is_disconnected(self):
            self.checks += 1
            return self.checks > 2

    monkeypatch.setattr(events.AsyncRedis, "from_url", lambda *_a, **_kw: Client())

    async def collect():
        return [chunk async for chunk in events.stream_events(FakeRequest(), UserRole.VIEWER)]

    chunks = asyncio.run(collect())
    assert any(str(envelope.id) in chunk for chunk in chunks)
    assert closed == ["pubsub", "client"]
