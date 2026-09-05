"""
CampusResolve WebSocket Manager
Maintains active WebSocket connections and broadcasts real-time activity events across the application.
"""

import asyncio
import logging
from typing import List, Optional
from fastapi import WebSocket

logger = logging.getLogger("CampusResolveWS")


class ConnectionManager:
    """Manages active WebSocket client connections for real-time streaming."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast JSON message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket client: {e}")
                disconnected.append(connection)

        for dead_conn in disconnected:
            if dead_conn in self.active_connections:
                self.active_connections.remove(dead_conn)


manager = ConnectionManager()
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_event_loop(loop: asyncio.AbstractEventLoop):
    global _main_loop
    _main_loop = loop


def broadcast_activity_sync(data: dict):
    """
    Thread-safe synchronous helper to broadcast activity payload to all active WebSocket clients.
    Works from both FastAPI request threads and APScheduler background worker threads.
    """
    global _main_loop
    if _main_loop and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(data), _main_loop)
    else:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.create_task(manager.broadcast(data))
        except RuntimeError:
            pass
