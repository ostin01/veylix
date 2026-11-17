"""Redis-backed domain event publishing and SSE subscription helpers.

Redis Pub/Sub is intentionally transient: consumers refresh REST snapshots after
any reconnect because this transport does not retain missed messages.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import Request
from pydantic import BaseModel, Field, ValidationError
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

from enums import UserRole


logger = logging.getLogger(__name__)
EVENT_CHANNEL = "veylix:events:v1"
EventType = Literal[
    "telemetry.received",
    "vehicle.location.updated",
    "vehicle.health.updated",
    "vehicle.status.updated",
    "device.status.updated",
    "device.connected",
    "device.disconnected",
    "alert.created",
    "alert.updated",
    "alert.acknowledged",
    "alert.resolved",
    "admin.simulation.created",
    "admin.simulation.cleared",
]


class EventEnvelope(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fleet_id: UUID
    vehicle_id: UUID | None = None
    device_id: UUID | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


@lru_cache(maxsize=1)
def _publisher() -> Redis:
    return Redis.from_url(
        redis_url(),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )


def publish_event(
    event_type: EventType,
    *,
    fleet_id: UUID,
    vehicle_id: UUID | None = None,
    device_id: UUID | None = None,
    data: dict[str, Any] | None = None,
) -> bool:
    """Publish after a successful database commit; Redis errors never undo storage."""
    envelope = EventEnvelope(
        type=event_type,
        fleet_id=fleet_id,
        vehicle_id=vehicle_id,
        device_id=device_id,
        data=data or {},
    )
    try:
        _publisher().publish(EVENT_CHANNEL, envelope.model_dump_json())
    except RedisError:
        logger.warning(
            "Could not publish Veylix event %s; clients recover from REST snapshots",
            event_type,
            exc_info=True,
        )
        return False
    return True


def encode_sse(event: EventEnvelope) -> str:
    """Encode data without an SSE id field; IDs are for dedupe, not replay."""
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


def _status_sse(name: str, detail: str) -> str:
    payload = json.dumps({"status": detail}, separators=(",", ":"))
    return f"event: {name}\ndata: {payload}\n\n"


async def stream_events(request: Request, role: UserRole):
    """Subscribe to Redis with heartbeat and bounded reconnect backoff."""
    retry_delay = 1
    subscribed_once = False
    while not await request.is_disconnected():
        client = AsyncRedis.from_url(
            redis_url(),
            decode_responses=True,
            socket_connect_timeout=3,
            health_check_interval=30,
        )
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(EVENT_CHANNEL)
            if subscribed_once:
                yield _status_sse("stream.reset", "reconnected")
            else:
                yield ": connected\n\n"
            subscribed_once = True
            retry_delay = 1
            last_heartbeat = time.monotonic()

            while not await request.is_disconnected():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message and message.get("type") == "message":
                    try:
                        event = EventEnvelope.model_validate_json(message["data"])
                    except (ValidationError, TypeError, ValueError):
                        logger.warning("Ignoring malformed event received from Redis")
                    else:
                        if event.type.startswith("admin.") and role != UserRole.ADMIN:
                            continue
                        yield encode_sse(event)

                now = time.monotonic()
                if now - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = now
        except RedisError:
            logger.warning(
                "Redis event subscription failed; retrying in %s seconds",
                retry_delay,
                exc_info=True,
            )
            yield _status_sse("stream.status", "reconnecting")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
        finally:
            try:
                await pubsub.aclose()
            except RedisError:
                pass
            await client.aclose()
