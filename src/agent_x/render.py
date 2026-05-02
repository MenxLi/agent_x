from __future__ import annotations

import rich
import rich.box
import rich.console
import rich.markdown
import rich.panel
import rich.table
from rich.prompt import Confirm

from hashlib import sha1
import threading
from contextlib import contextmanager
from selectors import DefaultSelector, EVENT_READ
import sys
import time

from .config import app_config
from .context import execution_context

from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from .agent import Agent

JsonType = str | int | float | bool | None | dict[str, Any] | list["JsonType"]

class Renderer:
    console = rich.console.Console()
    lock = threading.Lock()

    def __init__(self, agent: Agent):
        self.agent = agent
    
    def _print(self, *args, **kwargs):
        with self.lock:
            self.console.print(*args, **kwargs)
    
    @property
    def agent_name(self) -> str:
        ctx = execution_context.get()
        if ctx:
            return ctx.agent.name
        else:
            return ""
    
    def render_model_message_content(self, content: str):
        self._print(
            rich.panel.Panel(
                rich.markdown.Markdown(
                    content, 
                    code_theme="monokai",
                    hyperlinks=True,
                ),
                title=f"[bold blue]{self.agent_name}[/bold blue]",
                border_style="blue",
            ), 
        )

    def render_history(self, agent: Agent):
        history = agent.conversation.to_history()

        def role_color(role: str) -> str:
            if role == "system": return "magenta"
            elif role == "user": return "cyan"
            elif role == "assistant": return "green"
            elif role == "tool": return "yellow"
            else: return "white"

        if not history:
            self._print(
                rich.panel.Panel(
                    "[dim]No conversation history yet.[/dim]",
                    title="[bold blue]Conversation History[/bold blue]",
                    border_style="green",
                    box=rich.box.ROUNDED,
                    padding=(0, 1),
                )
            )
            return

        sub_panels: list[rich.panel.Panel] = []
        counter = 0
        for record in history:
            if not record['content']:
                continue
            counter += 1
            color = role_color(record["role"])
            row = rich.table.Table.grid(expand=True)
            row.add_column(style=f"bold {color}", width=10)
            row.add_column(ratio=1)
            row.add_row(
                record["role"],
                rich.markdown.Markdown(
                    record["content"],
                    code_theme="monokai",
                    hyperlinks=True,
                ),
            )
            sub_panels.append(
                rich.panel.Panel(
                    row,
                    border_style=color,
                    box=rich.box.ROUNDED,
                    padding=(0, 0),
                )
            )

        self._print(
            rich.panel.Panel(
                rich.console.Group(*sub_panels),
                title="[bold blue]Conversation History[/bold blue]",
                subtitle=f"[dim]{counter} msgs[/dim]",
                box=rich.box.ROUNDED,
                padding=(0, 1),
            )
        )
    
    @contextmanager
    def tool_call_mgr(self, tool_call_id: str, tool_name: str, arguments: JsonType):
        def arg_str(args: JsonType) -> str:
            if isinstance(args, (str, int, float, bool, type(None))):
                return repr(args)
            elif isinstance(args, list):
                return "[" + ", ".join(arg_str(item) for item in args) + "]"
            assert isinstance(args, dict)

            s = []
            for k, v in args.items():
                if isinstance(v, str):
                    if len(v) > 50:
                        v = v[:47] + "..."
                    v = "\'" + v + "\'"
                s.append(f"[bold yellow]{k}[/bold yellow]: {v}")
            return ", ".join(s)

        tool_call_sha = sha1(tool_call_id.encode()).hexdigest()[:6]
        leading = f":wrench: {self.agent_name} [dim]{tool_call_sha}[/dim]"
        self._print(f"{leading} [bold green]{tool_name}[/bold green]({arg_str(arguments)})")
        try:
            yield
        except Exception as e:
            self._print(f"{leading} [bold red]Error[/bold red]")
            raise e
        finally:
            ...
    
    @contextmanager
    def working_mgr(self, description: str):
        # with self.console.status(f"[bold gray]{description}[/bold gray]", spinner="dots"):
        self._print(f":green_circle: [bold gray]{description}[/bold gray]")
        yield
    
    def error(self, message: str):
        self._print(f":red_circle: {message}")
    
def _confirm(prompt: str, default: bool = False) -> bool:

    cfg = app_config()
    console = Renderer.console
    if not cfg.auto_confirm:
        ret = Confirm.ask(prompt, default=default)
        console.print()  # add a newline after the prompt
        return ret
    else:
        if cfg.auto_confirm_timeout <= 0 or not sys.stdin.isatty():
            return default

        def parse_confirmation(response: str) -> bool | None:
            normalized = response.strip().lower()
            if normalized == "":
                return default
            if normalized in {"y", "yes"}:
                return True
            if normalized in {"n", "no"}:
                return False
            return None

        selector = DefaultSelector()
        try:
            selector.register(sys.stdin, EVENT_READ)
        except (ValueError, OSError, PermissionError):
            return default

        deadline = time.monotonic() + cfg.auto_confirm_timeout
        suffix = "[Y/n]" if default else "[y/N]"
        try:
            while True:
                remaining = deadline - time.monotonic() + 0.01
                if remaining <= 0:
                    console.print()
                    return default

                console.print(
                    f"{prompt} {suffix} (auto-confirming in {max(1, int(remaining))} seconds): ",
                    end="",
                    markup=False,
                    soft_wrap=True,
                )
                if not selector.select(remaining):
                    console.print()
                    return default

                response = sys.stdin.readline()
                if response == "":
                    console.print()
                    return default

                approved = parse_confirmation(response)
                if approved is not None:
                    return approved

                console.print("[prompt.invalid]Please enter Y or N[/prompt.invalid]")
        finally:
            selector.close()

def note(message: str, title: str = "Note", subtitle: str | None = None) -> None:
    panel = rich.panel.Panel(
        message, border_style="yellow", 
        title=f"[bold yellow]{title}[/bold yellow]",
        subtitle=f"[dim]{subtitle}[/dim]" if subtitle else None,
        )
    Renderer.console.print(panel)

_confirm_lock = threading.Lock()
def confirm(prompt: str, default: bool = False) -> bool:
    with _confirm_lock:
        return _confirm(prompt, default)

def confirm_with_note(
    prompt: str, 
    message: str, 
    title: str = "Note",
    subtitle: str | None = None,
    default: bool = True, 
    ) -> bool:
    with Renderer.lock:
        note(message, title=title, subtitle=subtitle)
        return confirm(prompt, default)