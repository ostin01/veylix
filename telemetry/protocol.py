from uuid import UUID


TELEMETRY_TOPIC_FILTER = "veylix/v1/fleets/+/vehicles/+/telemetry"


def telemetry_topic(fleet_id: UUID, vehicle_id: UUID) -> str:
    return f"veylix/v1/fleets/{fleet_id}/vehicles/{vehicle_id}/telemetry"


def parse_telemetry_topic(topic: str) -> tuple[UUID, UUID]:
    topic_parts = topic.split("/")
    if (
        len(topic_parts) != 7
        or topic_parts[:3] != ["veylix", "v1", "fleets"]
        or topic_parts[4] != "vehicles"
        or topic_parts[6] != "telemetry"
    ):
        raise ValueError("unexpected telemetry topic")
    try:
        return UUID(topic_parts[3]), UUID(topic_parts[5])
    except ValueError as error:
        raise ValueError("topic contains an invalid fleet or vehicle ID") from error
