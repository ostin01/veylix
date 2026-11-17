"""Authenticated SSE endpoint for compact domain events."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from auth.principal import Principal
from auth.security import require_roles
from enums import UserRole
from events import stream_events


router = APIRouter(prefix="/api/v1/events", tags=["events"])
READ_ROLES = (UserRole.ADMIN, UserRole.OPERATOR, UserRole.VIEWER)


@router.get("/stream", response_class=StreamingResponse)
async def event_stream(
    request: Request,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
) -> StreamingResponse:
    """Stream events authorized by the API's current global read roles."""
    return StreamingResponse(
        stream_events(request, principal.role),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
