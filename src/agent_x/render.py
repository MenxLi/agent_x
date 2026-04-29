from __future__ import annotations

import rich
import rich.panel
import rich.markdown
from contextlib import contextmanager

from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from .agent import Agent

JsonType = str | int | float | bool | None | dict[str, Any] | list["JsonType"]

class Renderer:
    console = rich.console.Console()

    def __init__(self, agent: Agent):
        self.agent = agent
    
    def render_model_message_content(self, content: str):
        self.console.print(
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
        self.console.print(f"{leading} [bold green]{tool_name}[/bold green]({arg_str(arguments)})")
        try:
            yield
            self.console.print(f"{leading} [bold green]Done[/bold green]")
        except Exception as e:
            self.console.print(f"{leading} [bold red]Error[/bold red]")
            raise e
        finally:
            ...
    
    @contextmanager
    def working_context(self, description: str):
        with self.console.status(f"[bold gray]{description}[/bold gray]", spinner="dots"):
            yield
    
    def error(self, message: str):
        self.console.print(f"[bold red]Error:[/bold red] {message}")
    