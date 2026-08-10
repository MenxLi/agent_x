"""
WebSocket-based display server for real-time agent monitoring and interaction.

Runs an HTTP + WebSocket server that:

- Streams display events to connected clients in real-time.
- Keeps all events in memory for retrieval via REST endpoints.
- Optionally serves a static chat page from assets/.
- Accepts user messages and choice responses via WebSocket.

Endpoints
---------
GET  /                Serve the chat HTML page (if *assets_dir* is set).
GET  /assets/<path>   Serve static files from the assets directory.
GET  /api/events      List all stored events (JSON array).
GET  /api/events/latest  Get the most recent event.
GET  /api/events/count   Get the number of stored events.
GET  /api/pending     Get the current pending prompt (for UI).
WS   /ws              WebSocket endpoint — streams events & accepts input.

Messages over WebSocket
-----------------------
Send  {"type": "message", "content": "..."}   — user chat message
Send  {"type": "choice", "value": "..."}      — respond to a pending prompt
Recv  {"type": "__pending_prompt", ...}       — a prompt needs user input
Recv  <DisplayEvent JSON>                     — real-time event stream
"""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from websockets import Headers, Request, Response, broadcast
from websockets.asyncio.server import Server, ServerConnection, serve

from .display_abstract import (
    DisplayAbstract,
    DisplayEvent,
)

if TYPE_CHECKING:
    from .agent import Agent


# ---------------------------------------------------------------------------
# Content-type helpers
# ---------------------------------------------------------------------------

_SUFFIX_CT: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".txt": "text/plain; charset=utf-8",
}


def _guess_content_type(suffix: str) -> str:
    return _SUFFIX_CT.get(suffix.lower(), "application/octet-stream")


def _make_response(
    status: int,
    body: bytes,
    content_type: str = "application/json; charset=utf-8",
) -> Response:
    return Response(
        status_code=status,
        reason_phrase=HTTPStatus(status).phrase,
        headers=Headers({"Content-Type": content_type}),
        body=body,
    )


def _json_response(obj: object) -> Response:
    body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    return _make_response(HTTPStatus.OK, body)


# ---------------------------------------------------------------------------
# Event store (thread-safe)
# ---------------------------------------------------------------------------

class _EventStore:
    """Thread-safe in-memory store for display events."""

    def __init__(self, max_events: int = 2000) -> None:
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._max_events = max_events

    def append(self, event_dict: dict) -> None:
        with self._lock:
            self._events.append(event_dict)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]

    @property
    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    @property
    def latest(self) -> Optional[dict]:
        with self._lock:
            return self._events[-1] if self._events else None

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._events)


# ---------------------------------------------------------------------------
# Pending-choice handling
# ---------------------------------------------------------------------------

class _PendingPrompt:
    """Hold a single blocking prompt and resolve it when a response arrives."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prompt: Optional[dict] = None
        self._event = threading.Event()
        self._response: Optional[str] = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._prompt is not None

    @property
    def current(self) -> Optional[dict]:
        with self._lock:
            return self._prompt

    def set(self, prompt: dict) -> None:
        with self._lock:
            self._prompt = prompt
            self._event = threading.Event()
            self._response = None

    def respond(self, value: str) -> None:
        with self._lock:
            self._response = value
            self._event.set()

    def wait(self, timeout: float = 120.0) -> Optional[str]:
        if not self._event.wait(timeout=timeout):
            return None
        with self._lock:
            resp = self._response
            self._prompt = None
            self._response = None
            self._event = threading.Event()
            return resp


# ---------------------------------------------------------------------------
# DisplayWS
# ---------------------------------------------------------------------------

class DisplayWS(DisplayAbstract):
    """
    Display implementation that runs an HTTP + WebSocket server.

    Parameters
    ----------
    host : str
        Bind address for the HTTP server.
    port : int
        Port for the HTTP server.
    assets_dir : Path | None
        Directory containing static assets.  When set, ``GET /`` serves
        ``assets_dir / "chat.html"`` and ``GET /assets/<path>`` serves files
        from that directory.
    max_events : int
        Maximum number of events to keep in memory.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18960,
        assets_dir: Optional[Path] = None,
        max_events: int = 2000,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self._assets_dir = assets_dir
        self._store = _EventStore(max_events=max_events)
        self._pending = _PendingPrompt()

        # Async state — initialised when start() is called
        self._server: Optional[Server] = None
        self._started = False
        self._started_event = threading.Event()
        self._loop_ref: Optional[asyncio.AbstractEventLoop] = None
        self._agent: Optional[Agent] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._thread: Optional[threading.Thread] = None

    # ---- lifecycle --------------------------------------------------------

    def start(self, *, blocking: bool = False) -> None:
        """Start the HTTP + WebSocket server in a background thread.

        If *blocking* is True this call does not return until the server
        shuts down.
        """
        if self._started:
            return
        self._started = True
        self._started_event.clear()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="display-ws-agent")

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop_ref = loop
            try:
                self._server = loop.run_until_complete(self._make_server())
                self._started_event.set()
                loop.run_forever()
            finally:
                if self._server:
                    self._server.close()
                    loop.run_until_complete(self._server.wait_closed())
                self._loop_ref = None
                self._server = None
                self._started = False
                loop.close()

        self._thread = threading.Thread(target=_run, daemon=True, name="display-ws-server")
        self._thread.start()
        self._started_event.wait(timeout=5)
        if blocking:
            self._thread.join()

    def stop(self) -> None:
        """Signal the server to shut down gracefully."""
        loop = self._loop_ref
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        self._thread = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # ---- DisplayAbstract interface ----------------------------------------

    def bind_agent(self, agent: Agent) -> None:
        self._agent = agent

    def on_event(self, event: DisplayEvent) -> None:
        payload = event.to_json()
        self._store.append(payload)
        self._broadcast(json.dumps(payload, ensure_ascii=False))

    def get_choice(
        self,
        prompt: str,
        choices: list[str],
        message: Optional[str] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        default: Optional[str] = None,
        allow_extra: bool = False,
    ) -> str:
        idx = self._store.count
        self._pending.set({
            "type": "choice",
            "prompt": prompt,
            "choices": choices,
            "message": message,
            "title": title,
            "subtitle": subtitle,
            "default": default,
            "allow_extra": allow_extra,
        })
        # Notify clients about the pending prompt
        self._broadcast(json.dumps({
            "type": "__pending_prompt",
            "index": idx,
            "data": self._pending.current,
        }, ensure_ascii=False))

        resp = self._pending.wait()
        if resp is None:
            return default if default else (choices[0] if choices else "")
        return resp

    # ---- private: asyncio server ------------------------------------------

    async def _make_server(self) -> Server:
        return await serve(
            self._handler,
            self.host,
            self.port,
            process_request=self._http_router,
            ping_interval=20,
            ping_timeout=20,
        )

    async def _http_router(
        self,
        _connection: ServerConnection,
        request: Request,
    ) -> Optional[Response]:
        """Intercept HTTP requests for REST / static endpoints before
        the WebSocket handshake."""

        path = request.path.split("?")[0]  # strip query string

        # --- REST API -------------------------------------------------------
        if path == "/api/events":
            return _json_response(self._store.events)
        if path == "/api/events/latest":
            ev = self._store.latest
            return _json_response(ev if ev else {"error": "no events yet"})
        if path == "/api/events/count":
            return _json_response({"count": self._store.count})
        if path == "/api/pending":
            return _json_response(self._pending.current or {})

        # --- Static assets --------------------------------------------------
        if self._assets_dir:
            if path == "/":
                chat_html = self._assets_dir / "chat.html"
                if chat_html.is_file():
                    return _make_response(
                        HTTPStatus.OK,
                        chat_html.read_bytes(),
                        "text/html; charset=utf-8",
                    )
            if path.startswith("/assets/"):
                rel = path[len("/assets/"):]
                if rel and ".." not in rel:
                    fpath = self._assets_dir / rel
                    if fpath.is_file():
                        return _make_response(
                            HTTPStatus.OK,
                            fpath.read_bytes(),
                            _guess_content_type(fpath.suffix),
                        )

        return None  # proceed with WebSocket handshake

    async def _handler(self, websocket: ServerConnection) -> None:
        # We iterate over incoming messages; broadcasting uses server.connections
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                kind = msg.get("type", "")

                if kind == "message":
                    content = str(msg.get("content", "")).strip()
                    if content:
                        self.info(f"[user] {content}")
                        if self._agent is None:
                            self.warning("No agent is attached to this display.")
                        else:
                            if self._executor is None:
                                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="display-ws-agent")
                            self._executor.submit(self._execute_message, content)

                elif kind == "choice":
                    value = msg.get("value", "")
                    if self._pending.active:
                        self._pending.respond(value)

        except Exception:
            pass

    def _execute_message(self, content: str) -> None:
        if self._agent is None:
            return
        try:
            self._agent.instruct(content).execute()
        except Exception as exc:
            self.error(f"Error executing instruction: {exc}")

    # ---- helpers ----------------------------------------------------------

    def _broadcast(self, data: str) -> None:
        if self._server is None:
            return
        connections = self._server.connections
        if not connections:
            return

        loop = self._loop_ref
        if loop is None:
            return

        async def _send() -> None:
            broadcast(connections, data)

        try:
            asyncio.run_coroutine_threadsafe(_send(), loop).result(timeout=2)
        except Exception:
            pass
