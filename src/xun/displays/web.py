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
from typing import Annotated, Any, AsyncGenerator, Literal, Optional, TYPE_CHECKING, Union
from urllib.parse import quote, urlencode, urlsplit

import uvicorn
import jinja2
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, TypeAdapter
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, Response

from ..config import ASSET_DIR
from ..context import execution_context
from ..display_abstract import AgentInfo, DisplayAbstract, DisplayEvent, UserMessageEvent
from ..types import CancelledError

if TYPE_CHECKING:
    from ..agent import Agent


DEFAULT_WEB_ASSETS = ASSET_DIR / "web"
LOGIN_TEMPLATE = jinja2.Environment(autoescape=True).from_string(
    (ASSET_DIR / "login.template.html").read_text(encoding="utf-8")
)
TEXT_SUFFIXES = {
    ".css", ".csv", ".html", ".ini", ".js", ".json", ".log", ".md",
    ".py", ".rst", ".sh", ".toml", ".ts", ".tsx", ".txt", ".vue",
    ".xml", ".yaml", ".yml",
}
_COOKIE_NAME = "xun_web_token"


class ChatMessage(BaseModel):
    type: Literal["message"]
    agent_id: str
    content: str = ""
    images: list[UserMessageEvent.ImageDescriptor] = Field(default_factory=list, max_length=8)


class CommandMessage(BaseModel):
    type: Literal["command"]
    agent_id: str
    name: str
    arguments: Optional[str] = None


class ChoiceMessage(BaseModel):
    type: Literal["choice"]
    prompt_id: str
    value: str


class CancelMessage(BaseModel):
    type: Literal["cancel"]
    agent_id: str


WebMessage = Annotated[Union[ChatMessage, CommandMessage, ChoiceMessage, CancelMessage], Field(discriminator="type")]
WEB_MESSAGE_ADAPTER = TypeAdapter(WebMessage)


class _EventStore:
    def __init__(self, max_events: int) -> None:
        self._events: deque[DisplayEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def append(self, event: DisplayEvent) -> None:
        with self._lock:
            self._events.append(event)

    def list(self) -> list[DisplayEvent]:
        with self._lock:
            return list(self._events)


class _PendingPrompts:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prompts: dict[str, dict[str, Any]] = {}
        self._responses: dict[str, str] = {}
        self._events: dict[str, threading.Event] = {}

    def set(self, agent_id: Optional[str], prompt: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            prompt_id = secrets.token_urlsafe(12)
            pending = {"id": prompt_id, "agent_id": agent_id, **prompt}
            self._prompts[prompt_id] = pending
            self._events[prompt_id] = threading.Event()
            return pending.copy()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [prompt.copy() for prompt in self._prompts.values()]

    def respond(self, prompt_id: str, value: str) -> bool:
        with self._lock:
            event = self._events.get(prompt_id)
            if event is None:
                return False
            self._responses[prompt_id] = value
            event.set()
            return True

    def wait(self, prompt_id: str) -> str:
        with self._lock:
            event = self._events[prompt_id]
        event.wait()
        with self._lock:
            self._prompts.pop(prompt_id, None)
            self._events.pop(prompt_id, None)
            return self._responses.pop(prompt_id)


class _TokenAuthMiddleware:
    def __init__(self, app: Any, token: str, mounts: dict[str, WebDisplay]) -> None:
        self.app = app
        self.token = token
        self.mounts = mounts

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        root_path = scope.get("root_path", "").rstrip("/")
        bearer = connection.headers.get("authorization", "")
        header_token = bearer[7:] if bearer.lower().startswith("bearer ") else ""
        cookie_token = connection.cookies.get(_COOKIE_NAME, "")
        if _tokens_match(header_token, self.token) or _tokens_match(cookie_token, self.token):
            await self.app(scope, receive, send)
            return

        request_path = connection.url.path
        if root_path and request_path.startswith(root_path):
            request_path = request_path[len(root_path):] or "/"
        mount_path = request_path.rstrip("/")
        if request_path == "/login":
            await self.app(scope, receive, send)
            return
        query_token = connection.query_params.get("token")
        if scope["type"] == "http" and mount_path in self.mounts and _tokens_match(query_token or "", self.token):
            response = RedirectResponse("./", status_code=303)
            response.set_cookie(
                _COOKIE_NAME,
                self.token,
                httponly=True,
                samesite="strict",
                secure=connection.url.scheme == "https",
                path=f"{root_path}/" if root_path else "/",
            )
            await response(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        elif self._is_display_page_request(scope, connection, request_path):
            login_path = f"{root_path}/login" if root_path else "/login"
            target = request_path
            if connection.url.query:
                target = f"{target}?{connection.url.query}"
            response = RedirectResponse(f"{login_path}?{urlencode({'next': target})}", status_code=303)
            await response(scope, receive, send)
        else:
            response = JSONResponse({"detail": "Not authenticated"}, status_code=401)
            await response(scope, receive, send)

    def _is_display_page_request(
        self,
        scope: dict[str, Any],
        connection: HTTPConnection,
        request_path: str,
    ) -> bool:
        if scope.get("method") not in {"GET", "HEAD"}:
            return False
        for mount_path in self.mounts:
            if mount_path and request_path != mount_path and not request_path.startswith(f"{mount_path}/"):
                continue
            relative_path = request_path[len(mount_path):] if mount_path else request_path
            if relative_path in {"", "/"}:
                return True
            if relative_path == "/api" or relative_path.startswith("/api/") or relative_path == "/ws":
                return False
            return "text/html" in connection.headers.get("accept", "")
        return False


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
    """Build a web interface and bridge browser input to agents."""

    def __init__(
        self,
        assets_dir: Path = DEFAULT_WEB_ASSETS,
        frontend_url: Optional[str] = None,
        expose_files: bool = False,
        max_events: int = 2000,
    ) -> None:
        super().__init__()
        self.assets_dir = assets_dir
        self.frontend_url = frontend_url
        self.expose_files = expose_files
        self._store = _EventStore(max_events)
        self._pending = _PendingPrompts()
        self._clients: set[WebSocket] = set()
        self._running_agents: set[str] = set()
        self._running_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._executor: Optional[ThreadPoolExecutor] = None

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncGenerator[None, None]:
        self._attach(asyncio.get_running_loop())
        try:
            yield
        finally:
            self._detach()

    def _attach(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is not None:
            raise RuntimeError("WebDisplay is already attached to a running app")
        self._loop = loop

    def _detach(self) -> None:
        self._loop = None
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def build_app(self) -> FastAPI:
        app = FastAPI(title="Xun Web", docs_url=None, redoc_url=None, lifespan=self._lifespan)
        app.include_router(self.build_routes())
        if self.assets_dir.is_dir() and not self.frontend_url:
            app.mount("/", StaticFiles(directory=self.assets_dir, html=True), name="web")
        return app

    def on_event(self, event: DisplayEvent) -> None:
        payload = event.to_json()
        self._store.append(event)
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
        context = execution_context.get()
        data = {
            "prompt": prompt, "choices": choices, "message": message,
            "title": title, "subtitle": subtitle, "default": default,
            "allow_extra": allow_extra,
        }
        data = self._pending.set(context.agent.identifier if context else None, data)
        self._broadcast({"type": "pending_prompt", "data": data})
        return self._pending.wait(data["id"])

    def _agent(self, identifier: str) -> Agent:
        agent = self.agents.get(identifier)
        if agent is None:
            raise HTTPException(404, "Agent not found")
        return agent

    def _supports_vision(self, agent: Agent) -> bool:
        return "vision" in agent.app_config.provider.model_capabilities

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
        if isinstance(message, ChatMessage):
            agent = self._agent(message.agent_id)
            content = message.content.strip()
            if not content and not message.images:
                return
            if message.images and not self._supports_vision(agent):
                self.error("The configured model does not support image input")
                return
            images = [image.value for image in message.images]
            self._enqueue(self._execute_message, agent, content, images)
        elif isinstance(message, CommandMessage):
            agent = self._agent(message.agent_id)
            name = message.name.strip().lstrip("/")
            if name:
                self._enqueue(self._execute_command, agent, name, message.arguments)
        elif isinstance(message, CancelMessage):
            agent = self._agent(message.agent_id)
            with self._running_lock:
                running = message.agent_id in self._running_agents
            if running:
                agent.cancel()
        else:
            if self._pending.respond(message.prompt_id, message.value):
                self._broadcast({"type": "prompt_resolved", "prompt_id": message.prompt_id})

    def _execute_message(self, agent: Agent, content: str, images: list[str]) -> None:
        with self._running_lock:
            self._running_agents.add(agent.identifier)
        self._broadcast({"type": "execution_state", "agent_id": agent.identifier, "running": True})
        try:
            agent.instruct(content, images=images or None).execute()
        except CancelledError:
            pass
        except Exception as exc:
            self.error(f"Error executing instruction: {exc}")
        finally:
            with self._running_lock:
                self._running_agents.discard(agent.identifier)
            self._broadcast({"type": "execution_state", "agent_id": agent.identifier, "running": False})

    def _execute_command(self, agent: Agent, name: str, arguments: Optional[str]) -> None:
        agent.execute_command(name, arguments)
        if name == "retry":
            agent.execute()

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

    def build_routes(self) -> APIRouter:
        router = APIRouter()

        @router.websocket("/ws")
        async def websocket(websocket: WebSocket) -> None:
            await websocket.accept()
            self._clients.add(websocket)
            try:
                while True:
                    self._submit(WEB_MESSAGE_ADAPTER.validate_python(await websocket.receive_json()))
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)

        @router.get("/api/events")
        async def events() -> list[DisplayEvent]:
            return self._store.list()

        @router.get("/api/prompts")
        async def pending_prompts() -> list[dict[str, Any]]:
            return self._pending.list()

        @router.post("/api/prompts/{prompt_id}")
        async def respond_to_prompt(prompt_id: str, response: ChoiceMessage) -> dict[str, bool]:
            if response.prompt_id != prompt_id or not self._pending.respond(prompt_id, response.value):
                raise HTTPException(409, "Prompt is no longer pending")
            self._broadcast({"type": "prompt_resolved", "prompt_id": prompt_id})
            return {"resolved": True}

        @router.get("/api/agents")
        async def agents() -> list[AgentInfo]:
            return [AgentInfo.from_agent(agent) for agent in self.agents.values()]

        @router.get("/api/running")
        async def running() -> list[str]:
            with self._running_lock:
                return sorted(self._running_agents)

        @router.get("/api/config")
        async def config() -> dict[str, bool]:
            return {"expose_files": self.expose_files}

        @router.get("/api/commands/{agent_id}")
        async def commands(agent_id: str) -> list[dict[str, str]]:
            agent = self._agent(agent_id)
            values = [{"name": "help", "description": "Show available commands."}]
            values.extend(
                {"name": command.name, "description": command.description}
                for command in agent.command.commands.values()
            )
            return values

        @router.get("/api/capabilities/{agent_id}")
        async def capabilities(agent_id: str) -> dict[str, Any]:
            provider = self._agent(agent_id).app_config.provider
            return {"model": provider.openai_model, "capabilities": sorted(provider.model_capabilities)}

        if self.expose_files:
            router.include_router(self._build_file_routes())

        if self.frontend_url:
            frontend_url = self.frontend_url

            @router.get("/")
            async def frontend_redirect() -> RedirectResponse:
                return RedirectResponse(frontend_url)

        return router

    def _build_file_routes(self) -> APIRouter:
        router = APIRouter()

        @router.get("/api/files/{agent_id}")
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

        @router.get("/api/files/{agent_id}/view")
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

        @router.get("/api/files/{agent_id}/download")
        async def download_file(agent_id: str, path: str) -> FileResponse:
            target = self._resolve_path(self._agent(agent_id), path)
            if not target.is_file():
                raise HTTPException(404, "File not found")
            return FileResponse(target, filename=target.name)

        @router.post("/api/files/{agent_id}/upload")
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

        @router.delete("/api/files/{agent_id}")
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

        return router


class WebDisplayService:
    """Mount and serve one or more isolated web displays."""

    def __init__(self, host: str = "localhost", port: int = 18960, token: str = "") -> None:
        self.host = host
        self.port = port
        self.token = token or secrets.token_urlsafe(24)
        self._displays: dict[str, WebDisplay] = {}
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None
        self._started = threading.Event()
        self.app = FastAPI(docs_url=None, redoc_url=None, lifespan=self._lifespan)
        self._configure_login()
        self.app.add_middleware(_TokenAuthMiddleware, token=self.token, mounts=self._displays)

    def _configure_login(self) -> None:
        @self.app.get("/login", response_class=HTMLResponse)
        async def login_page(request: Request, next: str = "/") -> HTMLResponse:
            return self._login_response(request, next)

        @self.app.post("/login")
        async def login(
            request: Request,
            token: str = Form(...),
            next: str = Form("/"),
        ) -> Response:
            target = self._login_target(next)
            if not _tokens_match(token, self.token):
                return self._login_response(request, target, error="Invalid access token", status_code=401)
            root_path = request.scope.get("root_path", "").rstrip("/")
            response = RedirectResponse(f"{root_path}{target}" if root_path else target, status_code=303)
            response.set_cookie(
                _COOKIE_NAME,
                self.token,
                httponly=True,
                samesite="strict",
                secure=request.url.scheme == "https",
                path=f"{root_path}/" if root_path else "/",
            )
            return response

    def _login_target(self, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
            return self._default_path()
        path = parsed.path.rstrip("/")
        if not any(not mount or path == mount or path.startswith(f"{mount}/") for mount in self._displays):
            return self._default_path()
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")

    def _default_path(self) -> str:
        mount_path = next(iter(self._displays), "")
        return f"{mount_path}/" if mount_path else "/"

    def _login_response(
        self,
        request: Request,
        next_path: str,
        *,
        error: str = "",
        status_code: int = 200,
    ) -> HTMLResponse:
        target = self._login_target(next_path)
        root_path = request.scope.get("root_path", "").rstrip("/")
        action = f"{root_path}/login" if root_path else "/login"
        return HTMLResponse(
            LOGIN_TEMPLATE.render(action=action, target=target, error=error),
            status_code=status_code,
        )

    def mount(self, path: str, display: WebDisplay) -> WebDisplayService:
        if self._started.is_set():
            raise RuntimeError("Cannot mount displays after the service has started")
        mount_path = _normalize_base_path(path)
        if mount_path in self._displays:
            raise ValueError(f"A display is already mounted at {mount_path or '/'}")
        if display in self._displays.values():
            raise ValueError("A WebDisplay can only be mounted once")
        if not mount_path and self._displays:
            raise ValueError("The root display must be the only mounted display")
        if mount_path and "" in self._displays:
            raise ValueError("Cannot add displays alongside a root display")
        if any(
            mount_path.startswith(f"{existing}/") or existing.startswith(f"{mount_path}/")
            for existing in self._displays
        ):
            raise ValueError("Display mount paths cannot overlap")
        self._displays[mount_path] = display
        self.app.mount(mount_path or "/", display.build_app())
        return self

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncGenerator[None, None]:
        loop = asyncio.get_running_loop()
        if any(display._loop is not None for display in self._displays.values()):
            raise RuntimeError("A mounted WebDisplay is already attached to a running app")
        for display in self._displays.values():
            display._attach(loop)
        self._started.set()
        try:
            yield
        finally:
            for display in self._displays.values():
                display._detach()
            self._started.clear()

    def url(self, path: str = "") -> str:
        mount_path = _normalize_base_path(path)
        return f"http://{self.host}:{self.port}{mount_path}/"

    def access_url(self, path: str = "") -> str:
        mount_path = _normalize_base_path(path)
        if mount_path not in self._displays:
            raise ValueError(f"No display mounted at {mount_path or '/'}")
        return f"{self.url(mount_path)}?token={quote(self.token)}"

    def start(self, *, blocking: bool = False) -> threading.Thread:
        if not self._displays:
            raise RuntimeError("Mount at least one WebDisplay before starting the service")
        if self._thread and self._thread.is_alive():
            return self._thread
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
            raise RuntimeError("WebDisplayService failed to start")
        print("Agents are available at the following URLs:")
        for path in self._displays:
            print(f"{self.access_url(path)}")
        if blocking:
            self._thread.join()
        return self._thread

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        if self._socket:
            self._socket.close()
        self._server = None
        self._thread = None
        self._socket = None
