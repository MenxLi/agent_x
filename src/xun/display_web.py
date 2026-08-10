"""Authenticated FastAPI web display for interactive agents."""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import socket
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Literal, Optional, TYPE_CHECKING, Union
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, TypeAdapter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from .attachments import AttachmentError, AttachmentStore
from .display_abstract import CommandEvent, DisplayAbstract, DisplayEvent, UserMessageEvent

if TYPE_CHECKING:
    from .agent import Agent


DEFAULT_WEB_ASSETS = Path(__file__).parent / "assets" / "web"
TEXT_SUFFIXES = {
    ".css", ".csv", ".html", ".ini", ".js", ".json", ".log", ".md",
    ".py", ".rst", ".sh", ".toml", ".ts", ".tsx", ".txt", ".vue",
    ".xml", ".yaml", ".yml",
}
_COOKIE_NAME = "xun_web_token"


class ChatMessage(BaseModel):
    type: Literal["message"]
    content: str = ""
    attachments: list[str] = Field(default_factory=list, max_length=8)


class CommandMessage(BaseModel):
    type: Literal["command"]
    name: str
    arguments: Optional[str] = None


class ChoiceMessage(BaseModel):
    type: Literal["choice"]
    value: str


WebMessage = Annotated[Union[ChatMessage, CommandMessage, ChoiceMessage], Field(discriminator="type")]
WEB_MESSAGE_ADAPTER = TypeAdapter(WebMessage)


class _EventStore:
    def __init__(self, max_events: int) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def append(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(event)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)


class _PendingPrompt:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prompt: Optional[dict[str, Any]] = None
        self._response: Optional[str] = None
        self._event = threading.Event()

    def set(self, prompt: dict[str, Any]) -> None:
        with self._lock:
            self._prompt = prompt
            self._response = None
            self._event.clear()

    def respond(self, value: str) -> None:
        with self._lock:
            if self._prompt is None:
                return
            self._response = value
            self._event.set()

    def wait(self, timeout: float) -> Optional[str]:
        if not self._event.wait(timeout):
            return None
        with self._lock:
            response = self._response
            self._prompt = None
            self._response = None
            self._event.clear()
            return response


class _TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, token: str, cookie_path: str) -> None:
        super().__init__(app)
        self.token = token
        self.cookie_path = cookie_path

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        query_token = request.query_params.get("token")
        if request.url.path in {"/", self.cookie_path} and query_token and _tokens_match(query_token, self.token):
            response = RedirectResponse("./", status_code=303)
            response.set_cookie(
                _COOKIE_NAME,
                self.token,
                httponly=True,
                samesite="strict",
                secure=request.url.scheme == "https",
                path=self.cookie_path,
            )
            return response

        bearer = request.headers.get("authorization", "")
        header_token = bearer[7:] if bearer.lower().startswith("bearer ") else ""
        cookie_token = request.cookies.get(_COOKIE_NAME, "")
        if _tokens_match(header_token, self.token) or _tokens_match(cookie_token, self.token):
            return await call_next(request)
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)


def _tokens_match(value: str, expected: str) -> bool:
    return bool(value) and hmac.compare_digest(value, expected)


def _normalize_base_path(value: str) -> str:
    stripped = value.strip().strip("/")
    if not stripped:
        return ""
    if any(part in {".", ".."} for part in stripped.split("/")):
        raise ValueError("base_path cannot contain '.' or '..'")
    return f"/{stripped}"


class WebDisplay(DisplayAbstract):
    """Serve the Vue UI and bridge authenticated browser input to agents.

    ``token=""`` generates a secure token. Chat images persist under the primary
    agent's ``.xun/attachments`` directory unless ``attachments_dir`` is set.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18960,
        assets_dir: Path = DEFAULT_WEB_ASSETS,
        frontend_url: Optional[str] = None,
        base_path: str = "",
        token: str = "",
        attachments_dir: Optional[Path] = None,
        max_events: int = 2000,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.assets_dir = assets_dir
        self.frontend_url = frontend_url
        self.base_path = _normalize_base_path(base_path)
        self.token = token or secrets.token_urlsafe(24)
        self.attachments_dir = attachments_dir
        self._attachments: Optional[AttachmentStore] = None
        self._store = _EventStore(max_events)
        self._pending = _PendingPrompt()
        self._agents: dict[str, Agent] = {}
        self._primary_agent_id: Optional[str] = None
        self._clients: set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None
        self._started = threading.Event()

        self.web_app = FastAPI(title="Xun Web", docs_url=None, redoc_url=None)
        cookie_path = f"{self.base_path}/" if self.base_path else "/"
        self.web_app.add_middleware(_TokenAuthMiddleware, token=self.token, cookie_path=cookie_path)
        self._configure_routes()

        self.app = FastAPI(docs_url=None, redoc_url=None, lifespan=self._lifespan)
        if self.base_path:
            self.app.mount(self.base_path, self.web_app)
        else:
            self.app.mount("/", self.web_app)

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        self._loop = asyncio.get_running_loop()
        self._started.set()
        try:
            yield
        finally:
            self._loop = None
            self._started.clear()

    def bind_agent(self, agent: Agent) -> None:
        self._agents[agent.identifier] = agent
        if self._primary_agent_id is None:
            self._primary_agent_id = agent.identifier
            directory = self.attachments_dir or agent.workdir / ".xun" / "attachments"
            self._attachments = AttachmentStore(directory)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{self.base_path}/"

    @property
    def access_url(self) -> str:
        return f"{self.url}?token={quote(self.token)}"

    def start(self, *, blocking: bool = False) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.listen()
        self.port = self._socket.getsockname()[1]
        self._server = uvicorn.Server(uvicorn.Config(self.app, log_level="warning"))
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [self._socket]},
            daemon=True,
            name="xun-web-server",
        )
        self._thread.start()
        if not self._started.wait(timeout=5):
            self.stop()
            raise RuntimeError("WebDisplay failed to start")
        print(f"Xun web: {self.access_url}")
        if blocking:
            self._thread.join()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        if self._socket:
            self._socket.close()
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        self._server = None
        self._thread = None
        self._socket = None

    def on_event(self, event: DisplayEvent) -> None:
        payload = event.to_json()
        self._store.append(payload)
        self._broadcast(payload)

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
        data = {
            "prompt": prompt, "choices": choices, "message": message,
            "title": title, "subtitle": subtitle, "default": default,
            "allow_extra": allow_extra,
        }
        self._pending.set(data)
        self._broadcast({"type": "pending_prompt", "data": data})
        response = self._pending.wait(timeout=120)
        return response or default or (choices[0] if choices else "")

    def _primary_agent(self) -> Agent:
        if self._primary_agent_id is None:
            raise HTTPException(503, "No agent is attached")
        return self._agents[self._primary_agent_id]

    def _agent(self, identifier: str) -> Agent:
        agent = self._agents.get(identifier)
        if agent is None:
            raise HTTPException(404, "Agent not found")
        return agent

    def _attachment_store(self) -> AttachmentStore:
        if self._attachments is None:
            raise HTTPException(503, "No agent is attached")
        return self._attachments

    def _supports_vision(self) -> bool:
        return "vision" in self._primary_agent().app_config.provider.model_capabilities

    def _resolve_path(self, agent: Agent, relative_path: str, *, follow_symlinks: bool = True) -> Path:
        root = agent.workdir.expanduser().resolve()
        target = Path(os.path.abspath(root / relative_path))
        if target != root and root not in target.parents:
            raise HTTPException(400, "Path escapes the agent workdir")
        if follow_symlinks:
            target = target.resolve()
            if target != root and root not in target.parents:
                raise HTTPException(400, "Path escapes the agent workdir")
        return target

    def _enqueue(self, function: Any, *args: Any) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xun-web-agent")
        self._executor.submit(function, *args)

    def _submit(self, message: WebMessage) -> None:
        agent = self._primary_agent()
        if isinstance(message, ChatMessage):
            content = message.content.strip()
            if not content and not message.attachments:
                return
            if message.attachments and not self._supports_vision():
                self.error("The configured model does not support image input")
                return
            try:
                images = [str(self._attachment_store().resolve(value)) for value in message.attachments]
            except AttachmentError as exc:
                self.error(str(exc))
                return
            self.emit(UserMessageEvent(content=content, attachments=message.attachments))
            self._enqueue(self._execute_message, agent, content, images)
        elif isinstance(message, CommandMessage):
            name = message.name.strip().lstrip("/")
            if name:
                self.emit(CommandEvent(name=name, arguments=message.arguments))
                self._enqueue(self._execute_command, agent, name, message.arguments)
        else:
            self._pending.respond(message.value)

    def _execute_message(self, agent: Agent, content: str, images: list[str]) -> None:
        try:
            agent.instruct(content, images=images or None).execute()
        except Exception as exc:
            self.error(f"Error executing instruction: {exc}")

    def _execute_command(self, agent: Agent, name: str, arguments: Optional[str]) -> None:
        command = agent.command.get(name)
        if command is None:
            self.error(f"Unknown command: /{name}")
            return
        try:
            command.invoke(agent, arguments)
            if name == "retry":
                agent.execute()
        except Exception as exc:
            self.error(f"Error executing command '/{name}': {exc}")

    def _broadcast(self, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return

        async def send() -> None:
            stale: list[WebSocket] = []
            for client in tuple(self._clients):
                try:
                    await client.send_json(payload)
                except Exception:
                    stale.append(client)
            self._clients.difference_update(stale)

        asyncio.run_coroutine_threadsafe(send(), loop)

    def _websocket_authenticated(self, websocket: WebSocket) -> bool:
        bearer = websocket.headers.get("authorization", "")
        header_token = bearer[7:] if bearer.lower().startswith("bearer ") else ""
        cookie_token = websocket.cookies.get(_COOKIE_NAME, "")
        return _tokens_match(header_token, self.token) or _tokens_match(cookie_token, self.token)

    def _configure_routes(self) -> None:
        app = self.web_app

        @app.get("/api/events")
        async def events() -> list[dict[str, Any]]:
            return self._store.list()

        @app.get("/api/agents")
        async def agents() -> list[dict[str, str]]:
            return [
                {"id": agent.identifier, "name": agent.name, "workdir": str(agent.workdir.resolve())}
                for agent in self._agents.values()
            ]

        @app.get("/api/commands")
        async def commands() -> list[dict[str, str]]:
            agent = self._primary_agent()
            values = [{"name": "help", "description": "Show available commands."}]
            values.extend(
                {"name": command.name, "description": command.description}
                for command in agent.command.commands.values()
            )
            return values

        @app.get("/api/capabilities")
        async def capabilities() -> dict[str, Any]:
            provider = self._primary_agent().app_config.provider
            return {"model": provider.openai_model, "capabilities": sorted(provider.model_capabilities)}

        @app.post("/api/attachments")
        async def upload_attachments(files: list[UploadFile] = File(...)) -> dict[str, list[str]]:
            if not self._supports_vision():
                raise HTTPException(400, "The configured model does not support image input")
            attachment_ids: list[str] = []
            store = self._attachment_store()
            for upload in files:
                try:
                    attachment_ids.append(store.save_image(await upload.read(store.max_bytes + 1)))
                except AttachmentError as exc:
                    raise HTTPException(400, str(exc)) from exc
            return {"attachments": attachment_ids}

        @app.get("/api/attachments/{attachment_id}")
        async def view_attachment(attachment_id: str) -> FileResponse:
            try:
                path = self._attachment_store().resolve(attachment_id)
            except AttachmentError as exc:
                raise HTTPException(404, str(exc)) from exc
            return FileResponse(path)

        @app.get("/api/files")
        async def list_files(agent_id: str, path: str = "") -> dict[str, Any]:
            agent = self._agent(agent_id)
            target = self._resolve_path(agent, path)
            if not target.is_dir():
                raise HTTPException(404, "Directory not found")
            entries = []
            for item in sorted(target.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "path": item.relative_to(agent.workdir.resolve()).as_posix(),
                    "kind": "directory" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else None,
                    "viewable": item.is_file() and item.suffix.lower() in TEXT_SUFFIXES,
                })
            return {"path": path, "entries": entries}

        @app.get("/api/files/view")
        async def view_file(agent_id: str, path: str) -> dict[str, str]:
            target = self._resolve_path(self._agent(agent_id), path)
            if not target.is_file():
                raise HTTPException(404, "File not found")
            if target.suffix.lower() not in TEXT_SUFFIXES:
                raise HTTPException(415, "File cannot be previewed")
            if target.stat().st_size > 1_000_000:
                raise HTTPException(413, "File is too large to preview")
            try:
                content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(415, "File is not UTF-8 text") from exc
            return {"path": path, "content": content}

        @app.get("/api/files/download")
        async def download_file(agent_id: str, path: str) -> FileResponse:
            target = self._resolve_path(self._agent(agent_id), path)
            if not target.is_file():
                raise HTTPException(404, "File not found")
            return FileResponse(target, filename=target.name)

        @app.post("/api/files/upload")
        async def upload_files(
            agent_id: str,
            path: str = Query(default=""),
            files: list[UploadFile] = File(...),
        ) -> dict[str, list[str]]:
            directory = self._resolve_path(self._agent(agent_id), path)
            if not directory.is_dir():
                raise HTTPException(404, "Directory not found")
            uploaded = []
            for upload in files:
                name = Path(upload.filename or "").name
                if not name:
                    continue
                target = self._resolve_path(self._agent(agent_id), str(Path(path) / name))
                with target.open("wb") as output:
                    while chunk := await upload.read(1024 * 1024):
                        output.write(chunk)
                uploaded.append(name)
            return {"uploaded": uploaded}

        @app.delete("/api/files")
        async def delete_file(agent_id: str, path: str) -> dict[str, bool]:
            agent = self._agent(agent_id)
            target = self._resolve_path(agent, path, follow_symlinks=False)
            if target == agent.workdir.resolve():
                raise HTTPException(400, "Cannot delete the workdir")
            if target.is_file() or target.is_symlink():
                target.unlink()
            elif target.is_dir():
                try:
                    target.rmdir()
                except OSError as exc:
                    raise HTTPException(409, "Directory is not empty") from exc
            else:
                raise HTTPException(404, "Path not found")
            return {"deleted": True}

        @app.websocket("/ws")
        async def websocket(websocket: WebSocket) -> None:
            if not self._websocket_authenticated(websocket):
                await websocket.close(code=1008)
                return
            await websocket.accept()
            self._clients.add(websocket)
            try:
                while True:
                    self._submit(WEB_MESSAGE_ADAPTER.validate_python(await websocket.receive_json()))
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)

        if self.frontend_url:
            frontend_url = self.frontend_url

            @app.get("/")
            async def frontend_redirect() -> RedirectResponse:
                return RedirectResponse(frontend_url)
        elif self.assets_dir.is_dir():
            app.mount("/", StaticFiles(directory=self.assets_dir, html=True), name="web")
