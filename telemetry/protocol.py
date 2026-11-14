from uuid import UUID


TELEMETRY_TOPIC_FILTER = "veylix/v1/vehicles/+/telemetry"


def telemetry_topic(vehicle_id: UUID) -> str:
    return f"veylix/v1/vehicles/{vehicle_id}/telemetry"


def parse_telemetry_topic(topic: str) -> UUID:
    topic_parts = topic.split("/")
    if (
        len(topic_parts) != 5
        or topic_parts[:3] != ["veylix", "v1", "vehicles"]
        or topic_parts[4] != "telemetry"
    ):
        raise ValueError("unexpected telemetry topic")
    try:
        return UUID(topic_parts[3])
    except ValueError as error:
        raise ValueError("topic contains an invalid vehicle ID") from error
