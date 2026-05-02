from __future__ import annotations

import rich
import rich.box
import rich.console
import rich.markdown
import rich.panel
import rich.table

import threading
from contextlib import contextmanager

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
    
    def render_model_message_content(self, content: str):
        self._print(
            rich.panel.Panel(
                rich.markdown.Markdown(
                    content, 
                    code_theme="monokai",
                    hyperlinks=True,
                ),
                title=f"[bold blue]{self.agent.name}[/bold blue]",
                border_style="blue",
            ), 
        )

    def render_history(self):
        history = self.agent.conversation.to_history()

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
    def tool_call_context(self, tool_call_id: str, tool_name: str, arguments: JsonType):
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

        tool_call_id = tool_call_id[:12]
        leading = f"[ {self.agent.name}/{tool_call_id} ]"
        self._print(f"{leading} [bold green]{tool_name}[/bold green]({arg_str(arguments)})")
        try:
            yield
            self._print(f"{leading} [bold green]Done[/bold green]")
        except Exception as e:
            self._print(f"{leading} [bold red]Error[/bold red]")
            raise e
        finally:
            ...
    
    @contextmanager
    def working_context(self, description: str):
        # with self.console.status(f"[bold gray]{description}[/bold gray]", spinner="dots"):
        self._print(f":green_circle: [bold gray]{description}[/bold gray]")
        yield
    
    def error(self, message: str):
        self._print(f":red_circle: {message}")
    