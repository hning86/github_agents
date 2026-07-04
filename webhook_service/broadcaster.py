"""Real-time Server-Sent Events (SSE) broadcaster and ring buffer."""
import asyncio
import datetime
import json
import logging
from typing import Optional

logger = logging.getLogger("webhook_service.broadcaster")

_event_listeners: set[asyncio.Queue] = set()
_event_history: list[dict] = []
_MAX_HISTORY = 150

def broadcast_event(level: str, event_type: str, agent: str, message: str, pr_info: Optional[dict] = None) -> None:
    """Broadcast real-time log event to all connected SSE web clients and save to ring buffer."""
    evt = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "level": level,
        "event_type": event_type,
        "agent": agent,
        "message": message,
        "pr_info": pr_info or {}
    }
    _event_history.append(evt)
    if len(_event_history) > _MAX_HISTORY:
        _event_history.pop(0)
    
    # Log to standard Python logger as well
    log_msg = f"[{agent}] {message}"
    if level == "ERROR":
        logger.error(log_msg)
    elif level == "WARNING":
        logger.warning(log_msg)
    else:
        logger.info(log_msg)

    # Send to active subscribers
    for queue in list(_event_listeners):
        try:
            queue.put_nowait(evt)
        except asyncio.QueueFull:
            pass

async def sse_event_generator(request_disconnect_checker):
    """Generator yielding formatted Server-Sent Events for connected clients."""
    # Send existing history first
    for evt in _event_history:
        yield f"data: {json.dumps(evt)}\n\n"
    
    # Create queue for live stream
    queue = asyncio.Queue(maxsize=200)
    _event_listeners.add(queue)
    try:
        while True:
            if await request_disconnect_checker():
                break
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {json.dumps(evt)}\n\n"
            except asyncio.TimeoutError:
                # Send heartbeat ping to keep connection alive
                yield ": heartbeat\n\n"
    finally:
        _event_listeners.discard(queue)
