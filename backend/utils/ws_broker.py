"""
Iter 77n — Real-time WebSocket broker.

A tiny in-process pub/sub that fans out event dicts to every WebSocket
subscribed to a firm (``company_id``) OR a specific ``user_id``.

Design goals
------------
* Zero external dependencies (Redis / Kafka would be overkill for a
  single-process FastAPI deployment).
* Broadcasts are best-effort — a dead / stalled socket is silently
  discarded (the client is expected to reconnect with backoff on its
  side, see ``/app/frontend/src/hooks/useLiveSync.ts``).
* All ``send_json`` calls are wrapped in ``try/except`` so one bad
  socket cannot block or crash the caller.

Wire-format of an event
-----------------------
Just a JSON object with a mandatory ``type`` field. Callers are free to
add any other keys the frontend needs to act on the event. Example::

    {"type": "punch.created", "firm": "cmp_abc", "user_id": "usr_1",
     "date": "2026-06-15", "at": "2026-06-15T09:15:00+05:30",
     "kind": "in"}

Usage
-----
::

    from utils.ws_broker import broker

    # In an endpoint after successful DB write:
    await broker.broadcast_firm(company_id, {
        "type": "punch.created",
        "user_id": uid,
        "date": date_iso,
        ...,
    })
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

log = logging.getLogger("ws_broker")


class WSBroker:
    """Fan-out websocket broker keyed by ``company_id`` + ``user_id``."""

    def __init__(self) -> None:
        # firm_id -> set of live sockets
        self._firm: Dict[str, Set[WebSocket]] = {}
        # user_id -> set of live sockets (for personal notifications)
        self._user: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    # -- connection management -------------------------------------------
    async def connect(
        self,
        ws: WebSocket,
        firm_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        async with self._lock:
            if firm_id:
                self._firm.setdefault(firm_id, set()).add(ws)
            if user_id:
                self._user.setdefault(user_id, set()).add(ws)

    async def disconnect(
        self,
        ws: WebSocket,
        firm_id: Optional[str],
        user_id: Optional[str],
    ) -> None:
        async with self._lock:
            if firm_id and firm_id in self._firm:
                self._firm[firm_id].discard(ws)
                if not self._firm[firm_id]:
                    self._firm.pop(firm_id, None)
            if user_id and user_id in self._user:
                self._user[user_id].discard(ws)
                if not self._user[user_id]:
                    self._user.pop(user_id, None)

    # -- broadcast helpers -----------------------------------------------
    async def _safe_send(self, ws: WebSocket, payload: Dict[str, Any]) -> bool:
        """Send JSON to a single socket. Return True on success."""
        try:
            await ws.send_json(payload)
            return True
        except Exception as exc:
            log.debug("ws send failed: %s", exc)
            return False

    async def broadcast_firm(self, firm_id: str, event: Dict[str, Any]) -> int:
        """Broadcast to every socket subscribed to ``firm_id``.

        Returns the number of successful deliveries. Dead sockets are
        garbage-collected on the fly.
        """
        if not firm_id:
            return 0
        payload = {**event, "firm": event.get("firm") or firm_id}
        sockets: Set[WebSocket] = self._firm.get(firm_id, set()).copy()
        if not sockets:
            return 0
        results = await asyncio.gather(
            *[self._safe_send(ws, payload) for ws in sockets],
            return_exceptions=True,
        )
        # Purge sockets that failed to send.
        dead = [ws for ws, ok in zip(sockets, results) if ok is not True]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._firm.get(firm_id, set()).discard(ws)
        return sum(1 for r in results if r is True)

    async def broadcast_user(self, user_id: str, event: Dict[str, Any]) -> int:
        """Broadcast to every socket owned by a specific user."""
        if not user_id:
            return 0
        sockets: Set[WebSocket] = self._user.get(user_id, set()).copy()
        if not sockets:
            return 0
        payload = {**event, "user": event.get("user") or user_id}
        results = await asyncio.gather(
            *[self._safe_send(ws, payload) for ws in sockets],
            return_exceptions=True,
        )
        dead = [ws for ws, ok in zip(sockets, results) if ok is not True]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._user.get(user_id, set()).discard(ws)
        return sum(1 for r in results if r is True)

    # -- introspection (for /admin/ws/stats debug endpoint) --------------
    def stats(self) -> Dict[str, Any]:
        return {
            "firm_channels": len(self._firm),
            "user_channels": len(self._user),
            "total_sockets": sum(len(s) for s in self._firm.values())
            + sum(len(s) for s in self._user.values()),
            "firm_counts": {k: len(v) for k, v in self._firm.items()},
        }


# Module-level singleton — every part of the app imports and uses this.
broker = WSBroker()
